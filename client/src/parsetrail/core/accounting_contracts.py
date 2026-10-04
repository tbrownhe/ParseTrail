"""Versioned parser declarations of normalized accounting evidence, never approvals."""

import json

FIELD = "ACCOUNTING_CONTRACT"
REPRESENTATION = "loan-total-and-interest"
RULE = "declared-loan-total-and-interest-1"
BALANCES = {
    "derived-opening-principal": "Opening principal is derived from closing principal and activity; not independent reconciliation.",
    "printed-principal": "Printed prior/ending principal for ordinary statements; balances remain unreviewed.",
}
PERIODS = {
    "printed-activity-range": "Printed transaction-history range; boundary timing remains unreviewed.",
    "assumed-31-days": "Parser assumes a 31-day statement period; coverage is not established.",
}


def snapshot(value):
    """Detach JSON metadata; validate known declarations and retain future formats.

    Unknown schema versions/representations are evidence only. A malformed known
    declaration is a parser error, rather than permission to guess its meaning.
    """
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("Accounting contract must be a JSON object.")
    try:
        result = json.loads(json.dumps(value, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise ValueError("Accounting contract must contain JSON values.") from exc
    if type(result.get("schema_version")) is not int or result["schema_version"] < 1:
        raise ValueError("Accounting contract requires a positive schema version.")
    if not isinstance(result.get("representation"), str) or not result["representation"].strip():
        raise ValueError("Accounting contract requires a representation.")
    if result["schema_version"] != 1 or result["representation"] != REPRESENTATION:
        return result
    fields = {
        "schema_version",
        "representation",
        "label",
        "payment_description",
        "interest_description",
        "association",
        "balance_basis",
        "period_basis",
        "date_basis",
        "excluded_descriptions",
        "unposted_descriptions",
    }
    if set(result) != fields:
        raise ValueError("Unexpected or missing loan accounting contract fields.")
    for field in ("label", "payment_description", "interest_description"):
        if not isinstance(result[field], str) or not result[field].strip():
            raise ValueError("Loan accounting contract requires nonempty labels and component selectors.")
    for field in ("excluded_descriptions", "unposted_descriptions"):
        if not isinstance(result[field], list) or any(not isinstance(s, str) or not s.strip() for s in result[field]):
            raise ValueError("Excluded and unposted selectors must be lists of nonempty descriptions.")
    selectors = [
        result["payment_description"],
        result["interest_description"],
        *result["excluded_descriptions"],
        *result["unposted_descriptions"],
    ]
    if len(selectors) != len(set(selectors)):
        raise ValueError("Accounting component selectors must be distinct.")
    if (
        result["association"] != "same-account-date-statement"
        or result["balance_basis"] not in BALANCES
        or result["period_basis"] not in PERIODS
        or result["date_basis"] != "unverified"
    ):
        raise ValueError("Unsupported component association or provenance in loan contract version one.")
    return result


def encode(value):
    value = snapshot(value)
    return None if value is None else json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def loan_workflow(value):
    """Resolve only retained, supported evidence; never consult current parser code."""
    try:
        value = snapshot(value)
    except (TypeError, ValueError):
        return None
    if value is None or value["schema_version"] != 1 or value["representation"] != REPRESENTATION:
        return None
    details = "Payment total and separate interest component; interest is recognized once."
    if value["excluded_descriptions"] or value["unposted_descriptions"]:
        details += (
            " Declared synthetic/excluded statements and separate unposted components stay outside this workflow."
        )
    return {
        "rule": RULE,
        "name": value["label"],
        "payment": value["payment_description"],
        "interest": value["interest_description"],
        "excluded": value["excluded_descriptions"],
        "balance_basis": BALANCES[value["balance_basis"]],
        "period_basis": PERIODS[value["period_basis"]],
        "component_basis": details,
    }
