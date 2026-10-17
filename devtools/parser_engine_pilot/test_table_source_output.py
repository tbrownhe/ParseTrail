"""The shared output keeps table raw fields and unknown balances on reopen."""

from pathlib import Path

from parsetrail.core.source_evidence import ActivityExportPayload, SourceEvidence
from parsetrail.core.v2_parser_engine import parse_csv

from devtools.parser_engine_pilot.table_source_output import from_table

DEFINITION = Path(__file__).parents[1] / "v2_fresh_slice" / "synthetic-posted-cash-definition.json"
SOURCE = (
    b"Date,Account,Description,Amount,ReportedBalance\n"
    b"10/01/2026,Checking A,Coffee,-$4.00,$996.00\n"
    b"10/02/2026,Checking A,Unclassified credit,$10.00,Unavailable\n"
)


def test_csv_output_roundtrip_keeps_unknown_and_locations() -> None:
    parsed = parse_csv(DEFINITION.read_bytes(), SOURCE)
    output = from_table(parsed)
    restored = SourceEvidence.model_validate_json(output.model_dump_json())
    assert restored == output
    assert isinstance(output.payload, ActivityExportPayload)
    assert output.payload.coverage_verified is False
    assert [(row.amount.minor, row.running_balance.minor) for row in output.payload.rows] == [
        (-400, 99600),
        (1000, None),
    ]
    assert output.payload.rows[1].running_balance.provenance == "unknown"
    assert output.payload.rows[1].fragments[0].raw_values[-1] == "Unavailable"
    assert output.payload.rows[1].date.locations[0].row == 3
    assert output.payload.activity_start.provenance == "derived"
