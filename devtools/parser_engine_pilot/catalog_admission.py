"""Strict pilot admission of the finite declaration operations in 2.0 scope.

This is a local catalog test boundary. It does not trust a release key or route
documents, and the pilot engine is not yet an installed client import path.
"""

from __future__ import annotations

import json
from collections.abc import Callable

from parsetrail.core.v2_data_catalog import DefinitionIdentity

from devtools.parser_engine_pilot import (
    anchored_table,
    card_lines,
    citi_layout,
    dual_text_card_lines,
    engine,
    hsa_cash_lines,
    investment_summary_lines,
    legacy_citi_lines,
    loan_history_lines,
    occu_bank_lines,
    occu_card_lines,
    savings_lines,
    single_column_summary,
    transamerica_summary_lines,
    two_date_card_lines,
    wells_loan_lines,
    wells_table,
)

MAX_DEFINITION_BYTES = 64 * 1024
Loader = Callable[[bytes], tuple[object, str]]

_OPERATIONS: dict[str, Loader] = {
    "anchored_columns_table_v1": anchored_table.load_definition,
    "card_header_charge_v1": occu_card_lines.load_definition,
    "dated_running_savings_v1": savings_lines.load_definition,
    "dual_text_card_activity_v1": dual_text_card_lines.load_definition,
    "layout_date_start_continuation_v1": legacy_citi_lines.load_definition,
    "plan_label_value_summary_v1": single_column_summary.load_plan_definition,
    "printed_account_value_summary_v1": investment_summary_lines.load_definition,
    "printed_loan_history_components_v1": loan_history_lines.load_definition,
    "printed_principal_allocations_v1": wells_loan_lines.load_definition,
    "single_column_retirement_summary_v1": transamerica_summary_lines.load_definition,
    "single_column_value_summary_v1": single_column_summary.load_definition,
    "summary_inherited_savings_v1": savings_lines.load_summary_definition,
    "two_account_running_bank_v1": occu_bank_lines.load_definition,
    "two_date_card_activity_v1": two_date_card_lines.load_definition,
}

_OTHER: dict[str, Loader] = {
    "chase_card_line_pilot": card_lines.load_definition,
    "hsa_cash_line_pilot": hsa_cash_lines.load_definition,
    "pdf_citicc_202511": citi_layout.load_definition,
    "wells_business_table_pilot": wells_table.load_definition,
}


def _unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_definition_key")
        result[key] = value
    return result


def admit_pilot_definition(content: bytes) -> DefinitionIdentity:
    """Refuse unknown operations and validate all fields with the matching schema."""
    if type(content) is not bytes or not 0 < len(content) <= MAX_DEFINITION_BYTES:
        raise ValueError("definition_size")
    try:
        raw = json.loads(content, object_pairs_hook=_unique_pairs)
    except (UnicodeError, ValueError, RecursionError):
        raise ValueError("invalid_definition_json") from None
    if type(raw) is not dict:
        raise ValueError("invalid_definition_shape")
    suffix, parser_id, operation = raw.get("suffix"), raw.get("parser_id"), raw.get("operation")
    if type(suffix) is str and suffix in {".csv", ".xlsx"}:
        loader = engine.load_definition
    elif suffix == ".pdf" and type(operation) is str:
        loader = _OPERATIONS.get(operation)
    elif suffix == ".pdf" and operation is None and type(parser_id) is str:
        loader = _OTHER.get(parser_id)
    else:
        loader = None
    if loader is None:
        raise ValueError("unsupported_definition_operation")
    try:
        admitted, _digest = loader(content)
    except (ValueError, TypeError):
        raise ValueError("invalid_definition") from None
    return DefinitionIdentity(admitted.parser_id, admitted.revision, admitted.suffix)
