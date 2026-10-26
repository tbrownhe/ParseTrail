"""Explicit cash-section scope and code-owned unknown-description treatment."""

from __future__ import annotations

HSA_CASH_PARSER = "hsa_cash_line_pilot"
UNKNOWN_HSA_ACCOUNTING_DESCRIPTION = "Reviewed HSA cash movement; source description unavailable"


def admitted_statement_scope(parser_id: str, source_scope: str, financial_kind: str, tracking_scope: str) -> bool:
    if parser_id == HSA_CASH_PARSER:
        return source_scope == tracking_scope == "cash_component" and financial_kind == "asset"
    return source_scope == tracking_scope == "account_total"


def cash_tracking_scope(parser_id: str) -> str:
    return "cash_component" if parser_id == HSA_CASH_PARSER else "account_total"


def cash_accounting_description(parser_id: str, source_scope: str, text: str | None) -> str | None:
    if text:
        return text
    if parser_id == HSA_CASH_PARSER and source_scope == "cash_component":
        return UNKNOWN_HSA_ACCOUNTING_DESCRIPTION
    return None
