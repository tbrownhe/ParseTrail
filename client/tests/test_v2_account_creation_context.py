"""Account drafts retain selected document facts without inventing product policy."""

from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest
from parsetrail.core.source_evidence import ActivityExportPayload, MoneyValue, SourceEvidence
from parsetrail.core.v2_account_creation import AccountCreationDraft, suggest_account_creation
from parsetrail.core.v2_data_catalog import (
    CatalogAccountContext,
    DefinitionIdentity,
    VerifiedCatalog,
    VerifiedDefinition,
)
from parsetrail.core.v2_occu_bank_lines import parse_occu_bank
from parsetrail.core.v2_pdf_lines import page_lines

from devtools.parser_engine_pilot import test_occu_bank_lines as occu


def _evidence(*, annotation=False):
    original = occu.lines(annotation=annotation)
    raw = [line.raw.replace("1234", "2215").replace("5678", "3479").replace("9999", "7634") for line in original.lines]
    # Checking starts on another page, so selecting it cannot silently point at
    # the first section's page or endpoint balances.
    lines = page_lines(
        b"%PDF-synthetic",
        ("\n".join(raw[:6]), "\n".join(raw[6:])),
        extraction_library="pdfplumber-bounded-simple-v1",
    )
    return parse_occu_bank(occu.DEFINITION, lines, occu.ANNOTATIONS if annotation else None)


def _catalog(evidence):
    entry = VerifiedDefinition(
        DefinitionIdentity(evidence.parser_id, evidence.definition_revision, ".pdf"),
        occu.DEFINITION,
        evidence.definition_sha256,
        CatalogAccountContext(institution_key="occu", kind="asset"),
    )
    # This is a supplied verified-catalog value; signature verification has its
    # own tests. No activation, keys, profile, decoder or private source is used.
    return VerifiedCatalog(1, "a" * 40, "synthetic", b"", b"", (entry,))


def _suggest(evidence, identity="3479", *, catalog=None):
    return suggest_account_creation(
        evidence,
        catalog=catalog,
        source_identity=identity,
        source_form="last_four",
    )


def test_exact_selected_section_retains_source_page_period_and_reported_balances():
    evidence = _evidence()
    draft = _suggest(evidence, catalog=_catalog(evidence))
    savings, checking = evidence.payload.accounts
    assert draft.name == "Occu 3479"
    assert (draft.kind, draft.tracking_scope) == ("asset", "account_total")
    assert draft.source_sha256 == evidence.source_sha256
    assert draft.source_locations == checking.identity_locations
    assert draft.source_locations[0].page == 2
    assert draft.source_locations != savings.identity_locations
    assert draft.period_start is evidence.payload.start
    assert draft.period_end is evidence.payload.end
    assert draft.period_start.iso == "2026-01-01"
    assert draft.period_end.iso == "2026-01-31"
    assert draft.period_start.provenance == draft.period_end.provenance == "observed"
    assert draft.opening_balance is checking.opening
    assert draft.closing_balance is checking.closing
    assert (draft.opening_balance.minor, draft.closing_balance.minor) == (20000, 19500)
    assert draft.opening_balance.raw == "$200.00"
    assert draft.opening_balance.provenance == "observed"
    assert draft.opening_balance.locations == checking.opening.locations
    # The parser does not retain a product label on StatementAccount. Neither
    # the institution, number nor the section's position supplies one.
    assert draft.product_label is None
    assert draft.full_account_number is None


def test_excluded_credit_line_is_not_a_selectable_account_or_source_of_balances():
    evidence = _evidence()
    assert any("7634" in raw for item in evidence.payload.dispositions for raw in item.raw_values)
    with pytest.raises(ValueError, match="selected_source_account_missing"):
        _suggest(evidence, "7634", catalog=_catalog(evidence))


def test_missing_or_mismatched_catalog_does_not_turn_section_label_into_financial_class():
    evidence = _evidence()
    catalog = _catalog(evidence)
    stale = replace(catalog, definitions=(replace(catalog.definitions[0], sha256="0" * 64),))
    for supplied in (None, stale):
        draft = _suggest(evidence, catalog=supplied)
        assert draft.name == "Account 3479"
        assert draft.kind is None and draft.institution_key == "" and not draft.verified_context
        assert draft.product_label is None
        assert draft.tracking_scope == "account_total"
        assert draft.opening_balance == evidence.payload.accounts[1].opening


def test_zero_unknown_and_absent_reported_balances_stay_distinct():
    evidence = _evidence()
    section = evidence.payload.accounts[1]
    zero = MoneyValue(raw="$0.00", minor=0, provenance="observed", locations=section.opening.locations)
    unknown = MoneyValue(raw=None, minor=None, provenance="unknown", locations=())
    for opening, closing in ((zero, unknown), (None, None)):
        selected = section.model_copy(update={"opening": opening, "closing": closing})
        payload = evidence.payload.model_copy(update={"accounts": (selected,), "independent_balance_verified": False})
        changed = SourceEvidence.model_validate_json(evidence.model_copy(update={"payload": payload}).model_dump_json())
        draft = _suggest(changed)
        assert draft.opening_balance == opening
        assert draft.closing_balance == closing
    assert zero.minor == 0 and unknown.minor is None


def test_period_annotation_provenance_and_unknown_start_are_not_replaced_with_row_dates():
    evidence = _evidence(annotation=True)
    draft = _suggest(evidence)
    assert draft.period_start.provenance == "observed"
    assert draft.period_start.locations[0].kind == "pdf_annotation"
    assert draft.period_start.locations[0].ordinal == 2
    assert draft.period_end.locations[0].ordinal == 3
    unknown_start = evidence.payload.start.model_copy(update={"raw": None, "iso": None, "provenance": "unknown"})
    changed = evidence.model_copy(update={"payload": evidence.payload.model_copy(update={"start": unknown_start})})
    assert _suggest(changed).period_start is unknown_start


@pytest.mark.parametrize("provenance", ["derived", "assumed"])
def test_period_origin_is_preserved_without_becoming_a_printed_date(provenance):
    evidence = _evidence()
    start = evidence.payload.start.model_copy(update={"raw": None, "provenance": provenance})
    changed = evidence.model_copy(update={"payload": evidence.payload.model_copy(update={"start": start})})
    draft = _suggest(changed)
    assert draft.period_start is start
    assert draft.period_start.raw is None and draft.period_start.provenance == provenance
    assert draft.period_start.locations == evidence.payload.start.locations


def test_accountless_export_uses_first_accountless_row_location_and_no_invented_endpoints():
    evidence = _evidence()
    first = evidence.payload.accounts[0].rows[0]
    accountless = (
        evidence.payload.accounts[1].rows[0].model_copy(update={"source_account": None, "source_account_form": None})
    )
    payload = ActivityExportPayload(
        kind="activity_export",
        activity_start=evidence.payload.start,
        activity_end=evidence.payload.end,
        rows=(first, accountless),
        dispositions=(),
    )
    changed = evidence.model_copy(update={"payload": payload})
    draft = suggest_account_creation(changed, catalog=None)
    assert draft.source_locations == tuple(fragment.location for fragment in accountless.fragments)
    assert draft.source_locations[0].page == 2
    assert draft.period_start is payload.activity_start and draft.period_end is payload.activity_end
    assert draft.opening_balance is draft.closing_balance is None
    assert accountless.running_balance is not None
    assert draft.source_identity is None and draft.full_account_number is None


@pytest.mark.parametrize(
    ("identity", "form", "expected_tail", "full_number"),
    [
        ("1234567890", "full", "7890", "1234567890"),
        ("3425xxxxxx7239487", "opaque", "9487", None),
        ("1234XX72", "opaque", "72", None),
        ("123456XX", "opaque", "3456", None),
        ("72", "full", "72", "72"),
        ("no digits", "opaque", "", None),
    ],
)
def test_default_name_uses_only_last_visible_run_and_preserves_separate_full_number(
    identity, form, expected_tail, full_number
):
    evidence = _evidence()
    section = evidence.payload.accounts[0].model_copy(
        update={"source_identity": identity, "source_identity_form": form, "rows": ()}
    )
    changed = evidence.model_copy(update={"payload": evidence.payload.model_copy(update={"accounts": (section,)})})
    draft = suggest_account_creation(changed, catalog=_catalog(changed), source_identity=identity, source_form=form)
    assert draft.name == " ".join(part for part in ("Occu", expected_tail) if part)
    assert draft.source_identity == identity and draft.source_form == form
    assert draft.full_account_number == full_number
    if not expected_tail:
        without_context = suggest_account_creation(changed, catalog=None, source_identity=identity, source_form=form)
        assert without_context.name == ""


def test_new_context_fields_are_optional_and_frozen_for_existing_draft_callers():
    draft = AccountCreationDraft(name="Authored account")
    assert draft.source_sha256 is None and draft.source_locations == ()
    assert draft.product_label is draft.period_start is draft.period_end is None
    assert draft.opening_balance is draft.closing_balance is None
    with pytest.raises(FrozenInstanceError):
        draft.source_sha256 = "a" * 64
