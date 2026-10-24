"""The archive audit reports only aggregate results for synthetic sources."""

from pathlib import Path

import pytest

from devtools.parser_engine_pilot.audit_full_archive import audit


def test_csv_archive_audit_checks_signed_definition_and_source_evidence(tmp_path: Path) -> None:
    source = (
        b'<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.0 Transitional//EN">'
        b"Date,Description,Principal,Interest,Fees,Total,\n"
        b"10/01/2026,Payment,-$80.00,-$20.00,$0.00,-$100.00,\n"
    )
    (tmp_path / "source.csv").write_bytes(source)

    summary, failures = audit((tmp_path,), suffix=".csv")

    assert failures == []
    assert summary["source_count"] == 1
    assert summary["parsed_counts"] == {"mohela_account_history_export": 1}
    assert summary["observation_counts"] == {"mohela_account_history_export": 1}
    assert "source.csv" not in str(summary)


def test_archive_audit_refuses_empty_source_set(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="no_archive_sources"):
        audit((tmp_path,), suffix=".csv")
