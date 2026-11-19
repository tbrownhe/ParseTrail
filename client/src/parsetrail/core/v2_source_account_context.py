"""Finite policy for institution-identifying source families.

A signed format declaration authenticates its rules, not the origin of an
arbitrary generic table. Only reviewed institution-identifying families can
supply document account context. User format selection never upgrades this.
"""

from __future__ import annotations

import hashlib
import json
import re

from parsetrail.core.source_evidence import ActivityExportPayload, SourceEvidence, StatementPayload
from parsetrail.core.v2_account_products import AccountProductProfile, account_product
from parsetrail.core.v2_data_catalog import CatalogAccountContext, VerifiedCatalog
from parsetrail.core.v2_parser_engine import ENGINE_VERSION, Definition, load_definition

_MOHELA_HEADERS = {
    "mohela_account_history_export": ("Date", "Description", "Principal", "Interest", "Fees", "Total"),
    "mohela_detailed_export": (
        "Date",
        "LoanName",
        "Description",
        "Principal",
        "Interest",
        "Fees",
        "Total",
        "UnpaidPrincipalBalanceValue",
    ),
}
_COMPONENT_COLUMNS = {"principal": "Principal", "interest": "Interest", "fees": "Fees"}

# These are client-reviewed family interpretations, independent of an account's
# authored name or a generic table's text. Multiple products stay multiple.
_FAMILY_PRODUCTS = {
    "chase_card_line_pilot": (("credit_card", "account_total"),),
    "happen_savings_line_pilot": (("savings", "account_total"),),
    "hsa_cash_line_pilot": (("hsa", "cash_component"),),
    "lendingclub_savings_line_pilot": (("savings", "account_total"),),
    "mohela_account_history_export": (("loan", "principal_component"),),
    "mohela_detailed_export": (("loan", "principal_component"),),
    "pdf_capitaloneauto_202402": (("loan", "principal_component"),),
    "pdf_citicc_201505": (("credit_card", "account_total"),),
    "pdf_citicc_202506": (("credit_card", "account_total"),),
    "pdf_citicc_202511": (("credit_card", "account_total"),),
    "pdf_fidelity401k_201810": (("investment", "account_total"),),
    "pdf_fidelityhsa_202001": (("hsa", "account_total"),),
    "pdf_lendingclublus_202506": (("savings", "account_total"),),
    "pdf_occubank_201409": (("checking", "account_total"), ("savings", "account_total")),
    "pdf_occucc_201904": (("credit_card", "account_total"),),
    "pdf_transamerica_202104": (("investment", "account_total"),),
    "pdf_usbankreicc_201405": (("credit_card", "account_total"),),
    "pdf_vanguard_202210": (("investment", "account_total"),),
    "pdf_wfbankper_202105": (("checking", "account_total"), ("savings", "account_total")),
    "pdf_wfloanper_202306": (("loan", "principal_component"),),
    "pdf_yamahafin_202306": (("loan", "account_total"),),
    "synchrony_amazon_store_card": (("credit_card", "account_total"),),
    "wells_business_table_pilot": (("checking", "account_total"), ("savings", "account_total")),
}


def _wells_printed_product(evidence: SourceEvidence) -> str | None:
    """Use an audited printed business product, never its filename or route alone."""
    payload = evidence.payload
    if (
        evidence.parser_id != "wells_business_table_pilot"
        or evidence.engine_version not in {"wells-table-pilot-2+statement-v2", "wells-table-pilot-2+statement-v3"}
        or not isinstance(payload, StatementPayload)
        or len(payload.accounts) != 1
        or payload.accounts[0].balance_scope != "account_total"
    ):
        return None
    labels = [item for item in payload.dispositions if item.code == "wells_account_product"]
    if len(labels) != 1 or len(labels[0].raw_values) != 1:
        return None
    label = labels[0]
    if label.location.kind != "pdf_line" or label.location.page != 1:
        return None
    text = " ".join(label.raw_values[0].split()).casefold()
    return {
        "initiate business checking": "checking",
        "initiate business checking sm": "checking",
        "business market rate savings": "savings",
        "business market rate savings sm": "savings",
    }.get(text)


def _identified_product(context, evidence):
    parser_id = evidence.parser_id
    if parser_id == "wells_business_table_pilot" and (context.institution_key, context.kind) == ("wellsfargo", "asset"):
        printed = _wells_printed_product(evidence)
        if printed is not None:
            # A conflicting catalog hint must not silently relabel the printed
            # account. Its institution/class remain context; product stays open.
            return context.model_copy(
                update={"product_type": printed if context.product_type in {None, printed} else None}
            )
    if context.product_type is not None:
        return context
    products = {product for product, _scope in _FAMILY_PRODUCTS.get(parser_id, ())}
    if len(products) == 1:
        product_type = next(iter(products))
        if account_product(product_type).kind == context.kind:
            return context.model_copy(update={"product_type": product_type})
    return context


def _reviewed_mohela_declaration(definition: Definition) -> bool:
    """Admit the reviewed family shape, without pinning a whole-file hash list."""
    header = _MOHELA_HEADERS.get(definition.parser_id)
    if header is None:
        return False
    detailed = definition.parser_id == "mohela_detailed_export"
    columns = {
        "date": "Date",
        "description": "Description",
        "total": "Total",
        **_COMPONENT_COLUMNS,
    }
    if detailed:
        columns.update(account="LoanName", balance="UnpaidPrincipalBalanceValue")
    actual_columns = {key: value for key, value in definition.columns.model_dump().items() if value is not None}
    return (
        definition.suffix == ".csv"
        and definition.kind == "activity_export"
        and set(definition.capabilities) == {"table_rows_v1", "components_v1"}
        and definition.header == header
        and actual_columns == columns
        and definition.date_format == "MM/DD/YYYY"
        and definition.date_role == "activity_date"
        and definition.money_format == "usd_symbol_2dp"
        and definition.first_header_cell == "after_last_gt"
        and definition.empty_trailing_column
        and definition.account_key == ("loan_id_dash_v1" if detailed else "unknown")
        and definition.unknown_balance_literals == (("Unavailable",) if detailed else ())
    )


def _csv_cell(field, *, row: int, column: int) -> bool:
    return (
        field.provenance == "observed"
        and field.raw is not None
        and len(field.locations) == 1
        and field.locations[0].kind == "csv_cell"
        and field.locations[0].row == row
        and field.locations[0].column == column
    )


def _reviewed_mohela_evidence(evidence: SourceEvidence, definition: Definition) -> bool:
    payload = evidence.payload
    if (
        not isinstance(payload, ActivityExportPayload)
        or not payload.rows
        or evidence.engine_version != ENGINE_VERSION
        or not evidence.extractor_version.startswith("python-csv-")
    ):
        return False
    columns = {name: index + 1 for index, name in enumerate(definition.header)}
    detailed = definition.parser_id == "mohela_detailed_export"
    for row in payload.rows:
        if (
            row.row_role != "activity"
            or row.date_role != "activity_date"
            or len(row.fragments) != 1
            or row.fragments[0].channel != "table"
            or row.fragments[0].location.kind != "csv_row"
            or tuple(item.role for item in row.components) != ("principal", "interest", "fee")
        ):
            return False
        source_row = row.fragments[0].location.row
        if source_row < 2 or not _csv_cell(row.date, row=source_row, column=columns["Date"]):
            return False
        if not _csv_cell(row.amount, row=source_row, column=columns["Total"]):
            return False
        for component, name in zip(row.components, ("Principal", "Interest", "Fees"), strict=True):
            if component.amount.minor is None or not _csv_cell(component.amount, row=source_row, column=columns[name]):
                return False
        if sum(component.amount.minor for component in row.components) != row.amount.minor:
            return False
        if detailed:
            if row.source_account_form != "opaque" or re.fullmatch(r"[0-9]+-[0-9]+", row.source_account or "") is None:
                return False
        elif row.source_account is not None or row.source_account_form is not None:
            return False
    return True


def verified_source_account_context(
    evidence: SourceEvidence,
    catalog: VerifiedCatalog | None,
) -> CatalogAccountContext | None:
    """Return context only when the exact signed source family identifies it.

    Generic CSV headers cannot identify an institution, even if only one format
    parses or the user chose that format. PDF keeps its exact signed context;
    mandatory unique routing is enforced by the import boundary. XLSX is excluded.
    """
    if catalog is None:
        return None
    entries = tuple(
        item
        for item in catalog.definitions
        if item.identity.parser_id == evidence.parser_id
        and item.identity.revision == evidence.definition_revision
        and item.sha256 == evidence.definition_sha256
    )
    if len(entries) != 1 or entries[0].account_context is None:
        return None
    entry = entries[0]
    if hashlib.sha256(entry.content).hexdigest() != entry.sha256:
        return None
    try:
        raw = json.loads(entry.content)
    except (UnicodeError, ValueError, TypeError):
        return None
    if not isinstance(raw, dict) or (raw.get("parser_id"), raw.get("revision"), raw.get("suffix")) != (
        entry.identity.parser_id,
        entry.identity.revision,
        entry.identity.suffix,
    ):
        return None
    if entry.identity.suffix == ".pdf":
        return _identified_product(entry.account_context, evidence)
    if entry.identity.suffix != ".csv" or (entry.account_context.institution_key, entry.account_context.kind) != (
        "mohela",
        "liability",
    ):
        return None
    try:
        definition, _digest = load_definition(entry.content)
    except (ValueError, TypeError):
        return None
    if not _reviewed_mohela_declaration(definition) or not _reviewed_mohela_evidence(evidence, definition):
        return None
    return _identified_product(entry.account_context, evidence)


def source_account_profiles(evidence: SourceEvidence, catalog: VerifiedCatalog) -> tuple[AccountProductProfile, ...]:
    """Return compatible format associations without upgrading source provenance.

    Generic CSV compatibility never supplies an institution-identifying context.
    Its current interpretation is asset cash; a catalog label cannot turn that
    into supported credit-card or loan activity. Known component exports retain
    their reviewed liability/principal interpretation.
    """
    entries = tuple(
        item
        for item in catalog.definitions
        if item.identity.parser_id == evidence.parser_id
        and item.identity.revision == evidence.definition_revision
        and item.sha256 == evidence.definition_sha256
    )
    if len(entries) != 1:
        return ()
    entry = entries[0]
    context = verified_source_account_context(evidence, catalog)
    if entry.account_profiles:
        profiles = entry.account_profiles
    else:
        pairs = _FAMILY_PRODUCTS.get(evidence.parser_id, ())
        # A renamed generic CSV must not inherit a reviewed lender's product.
        if isinstance(evidence.payload, ActivityExportPayload) and context is None:
            pairs = (
                ()
                if any(row.components for row in evidence.payload.rows)
                else (("checking", "account_total"), ("savings", "account_total"), ("cash", "account_total"))
            )
        institution = context.institution_key if context is not None else None
        profiles = tuple(AccountProductProfile(institution, product, scope) for product, scope in pairs)
    result = []
    for profile in profiles:
        if context is not None:
            if profile.institution_key not in {None, context.institution_key} or profile.kind != context.kind:
                continue
            if context.product_type is not None and profile.product_type != context.product_type:
                continue
            profile = AccountProductProfile(context.institution_key, profile.product_type, profile.tracking_scope)
        if isinstance(evidence.payload, ActivityExportPayload):
            supported_loan = (
                context is not None and context.kind == "liability" and evidence.parser_id in _MOHELA_HEADERS
            )
            if supported_loan:
                if profile.product_type != "loan" or profile.tracking_scope != "principal_component":
                    continue
            elif (
                any(row.components for row in evidence.payload.rows)
                or profile.kind != "asset"
                or profile.tracking_scope != "account_total"
            ):
                continue
        if profile not in result:
            result.append(profile)
    return tuple(result)
