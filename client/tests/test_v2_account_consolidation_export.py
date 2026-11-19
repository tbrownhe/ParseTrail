"""Export retains the consolidation mapping beside original financial identities."""

from datetime import date

from openpyxl import load_workbook
from parsetrail.core.v2_profile_store import V2ProfileStore
from parsetrail.core.v2_report_export import write_reviewed_journal_workbook

from .test_v2_account_consolidation import _confirm, _profile


def test_export_retains_original_postings_and_profile_wide_consolidation_audit(tmp_path):
    profile = tmp_path / "cards.db"
    _profile(profile)
    with V2ProfileStore.open(profile) as store:
        original = store.connection.execute("SELECT * FROM JournalEntries ORDER BY key").fetchall()
        decision = _confirm(store)
        report = store.reviewed_journal_export(start=date(2026, 3, 1), end=date(2026, 5, 1))
        assert report.account_consolidations == (decision,)
        assert {line.account_id for entry in report.entries for line in entry.postings} >= {"old", "kept"}
        assert store.connection.execute("SELECT * FROM JournalEntries ORDER BY key").fetchall() == original
    before = profile.read_bytes()
    path = write_reviewed_journal_workbook(report, tmp_path / "reviewed.xlsx")
    workbook = load_workbook(path, read_only=True, data_only=False)
    try:
        rows = list(workbook["Account Consolidations"].values)
        assert len(rows) == 2 and rows[1][:3] == (decision.consolidation_id, "kept", "old")
        assert rows[1][4:6] == (decision.reference, decision.reason)
        assert rows[1][-1] == decision.record_sha256
        assert "Account consolidations" in {row[0] for row in workbook["Scope"].values}
    finally:
        workbook.close()
    assert profile.read_bytes() == before
