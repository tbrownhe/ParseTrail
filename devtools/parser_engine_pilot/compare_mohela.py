"""Read-only comparison of the table pilot with the accepted detailed reader."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from parsetrail.core.mohela_export import COLUMNS, read_export

from devtools.parser_engine_pilot.engine import parse_csv

DEFINITION = Path(__file__).with_name("mohela-pilot-definition.json")


def compare(source: bytes, definition: bytes) -> dict[str, bool]:
    accepted = read_export(source)
    pilot = parse_csv(definition, source)
    seen: Counter[tuple[str, ...]] = Counter()
    expected_rows = []
    for row in accepted["rows"]:
        raw = tuple(row["raw"][column] for column in COLUMNS)
        occurrence = seen[raw]
        seen[raw] += 1
        expected_rows.append(
            (
                row["loan_id"],
                row["loan_name"],
                row["date"],
                row["description"],
                row["principal_minor"],
                row["interest_minor"],
                row["fees_minor"],
                row["total_minor"],
                row["reported_principal_minor"],
                row["row_number"],
                occurrence,
                raw,
            )
        )
    observed_rows = [row_tuple(row) for row in pilot.rows]
    return {
        "source_hash_equal": accepted["source_sha256"] == pilot.source_sha256,
        "rows_equal": expected_rows == observed_rows,
        "activity_span_equal": (accepted["activity_start"], accepted["activity_end"])
        == (pilot.activity_start, pilot.activity_end),
        "uncertainty_equal": accepted["coverage_verified"] is pilot.coverage_verified is False
        and accepted["balance_reconciled"] is pilot.balance_reconciled is False
        and accepted["reported_as_of"] is pilot.statement_closing_minor is None,
    }


def row_tuple(row) -> tuple:
    component = dict(row.components)
    return (
        row.account.normalized,
        row.account.raw,
        row.date.normalized,
        row.description.raw,
        component["principal"].normalized,
        component["interest"].normalized,
        component["fees"].normalized,
        row.total.normalized,
        row.balance.normalized if row.balance is not None else None,
        row.date.location.row,
        row.occurrence,
        (
            row.date.raw,
            row.account.raw,
            row.description.raw,
            component["principal"].raw,
            component["interest"].raw,
            component["fees"].raw,
            row.total.raw,
            row.balance.raw if row.balance is not None else None,
        ),
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="A detailed MOHELA CSV; read-only")
    args = parser.parse_args()
    source = args.source.read_bytes()
    before = hashlib.sha256(source).hexdigest()
    result = compare(source, DEFINITION.read_bytes())
    result["file_unchanged"] = before == hashlib.sha256(args.source.read_bytes()).hexdigest()
    print(json.dumps(result, sort_keys=True))
    return 0 if all(result.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
