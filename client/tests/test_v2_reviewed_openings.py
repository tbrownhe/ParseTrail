"""Printed opening positions require explicit source timing review in the 2.0 store."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from parsetrail.core.v2_profile_store import FinancialAccount, ProfileFormatError, V2ProfileStore
from parsetrail.core.v2_table_bank_source_output import from_anchored_bank
from parsetrail.core.v2_table_card_source_output import from_anchored_card

from devtools.parser_engine_pilot.test_table_bank_source_output import DEFINITION, SOURCE
from devtools.parser_engine_pilot.test_table_bank_source_output import evidence as bank_channels
from devtools.parser_engine_pilot.test_table_card_source_output import DEFINITION as CARD_DEFINITION
from devtools.parser_engine_pilot.test_table_card_source_output import SOURCE as CARD_SOURCE
from devtools.parser_engine_pilot.test_table_card_source_output import evidence as card_channels

from .test_v2_source_openings import _variant


def _profile(path: Path, *, amount_minor: int = 10_000):
    evidence = from_anchored_bank(DEFINITION, *bank_channels())
    source = SOURCE
    if amount_minor != 10_000:
        source = SOURCE + b"-opening-variant"
        evidence = _variant(evidence, source, opening_minor=amount_minor)
    with V2ProfileStore.create(path) as store:
        store.add_financial_account(FinancialAccount("cash", "Savings", "asset", "lendingclub"))
        store.import_source(source, DEFINITION, evidence, suffix=".pdf")
        account = evidence.payload.accounts[0]
        store.bind_source_account(evidence.source_sha256, account.source_identity, account.source_identity_form, "cash")
    return evidence


def test_reviewed_printed_opening_posts_equity_and_tracks_stale_review(tmp_path: Path):
    path = tmp_path / "opening.db"
    evidence = _profile(path)
    with V2ProfileStore.open(path) as store:
        candidate = store.earliest_source_openings()[0]
        assert candidate.printed_opening_minor == 10_000
        assert candidate.blockers == ("source_timing_unreviewed",)
        with pytest.raises(ProfileFormatError, match="opening_review_blocked"):
            store.post_reviewed_opening("cash")
        revision = store.record_opening_source_review(
            "cash",
            evidence.source_sha256,
            opening_origin="reported",
            timing_confirmed=False,
            source_reference="Page 1 balance summary",
        )
        assert revision == 1
        assert store.earliest_source_openings()[0].blockers == ("source_timing_unreviewed",)
        store.record_opening_source_review(
            "cash",
            evidence.source_sha256,
            opening_origin="reported",
            timing_confirmed=True,
            source_reference="Page 1 balance summary",
            note="Period dates inspected",
        )
        candidate = store.earliest_source_openings()[0]
        assert candidate.blockers == ()
        reviews = store.statement_source_reviews("cash")
        basis = store._opening_basis(candidate, reviews)
        with pytest.raises(ProfileFormatError, match="opening_review_changed_since_selection"):
            store.post_reviewed_opening("cash", expected_basis_sha256="stale")
        decision = store.post_reviewed_opening("cash", expected_basis_sha256=basis)
        assert decision.cutoff_date == date(2025, 12, 31)
        assert decision.amount_minor == 10_000 and decision.entry_key == "review:opening:cash"
        assert store.post_reviewed_opening("cash", expected_basis_sha256=basis) == decision
        assert (
            store.record_opening_source_review(
                "cash",
                evidence.source_sha256,
                opening_origin="reported",
                timing_confirmed=True,
                source_reference="Page 1 balance summary",
                note="Period dates inspected",
            )
            == reviews[0].revision_id
        )
        assert not store.opening_decision("cash").stale
        payload = json.loads(store.connection.execute("SELECT payload FROM JournalEntries").fetchone()[0])
        assert payload["origin"] == "opening" and payload["reviewed"]
        assert [(posting["account_id"], posting["amount_minor"]) for posting in payload["postings"]] == [
            ("cash", 10_000),
            ("internal:opening-equity:USD", -10_000),
        ]
        assert store._active_consumed() == {}
        assert (
            store.reviewed_category_summary(kind="expense", start=date(2025, 12, 1), end=date(2026, 1, 1)).total_minor
            == 0
        )
        store.record_opening_source_review(
            "cash",
            evidence.source_sha256,
            opening_origin="reported",
            timing_confirmed=True,
            source_reference="Page 1 checked again",
        )
        assert store.opening_decision("cash").stale
        with pytest.raises(ProfileFormatError, match="opening_already_decided"):
            store.post_reviewed_opening("cash")
    with V2ProfileStore.open(path, read_only=True) as store:
        assert store.opening_decision("cash").stale
        assert store.load_import(evidence.source_sha256).evidence == evidence


def test_zero_opening_is_a_decision_without_journal(tmp_path: Path):
    path = tmp_path / "zero.db"
    evidence = _profile(path, amount_minor=0)
    with V2ProfileStore.open(path) as store:
        store.record_opening_source_review(
            "cash",
            evidence.source_sha256,
            opening_origin="reported",
            timing_confirmed=True,
            source_reference="Page 1 zero balance",
        )
        decision = store.post_reviewed_opening("cash")
        assert decision.amount_minor == 0 and decision.entry_key is None
        assert store.connection.execute("SELECT COUNT(*) FROM JournalEntries").fetchone() == (0,)
        assert store.connection.execute("SELECT COUNT(*) FROM OpeningDecisions").fetchone() == (1,)


def test_card_debt_opening_preserves_liability_sign(tmp_path: Path):
    path = tmp_path / "card-opening.db"
    evidence = from_anchored_card(CARD_DEFINITION, *card_channels())
    with V2ProfileStore.create(path) as store:
        store.import_source(CARD_SOURCE, CARD_DEFINITION, evidence, suffix=".pdf")
        store.add_financial_account(FinancialAccount("card", "Card", "liability", "citi"))
        account = evidence.payload.accounts[0]
        store.bind_source_account(evidence.source_sha256, account.source_identity, account.source_identity_form, "card")
        candidate = store.earliest_source_openings()[0]
        assert candidate.printed_opening_minor == -10_000
        store.record_opening_source_review(
            "card",
            evidence.source_sha256,
            opening_origin="reported",
            timing_confirmed=True,
            source_reference="Page 1 card balance",
        )
        decision = store.post_reviewed_opening("card")
        payload = json.loads(store.connection.execute("SELECT payload FROM JournalEntries").fetchone()[0])
        assert decision.amount_minor == -10_000
        assert [(posting["account_id"], posting["amount_minor"]) for posting in payload["postings"]] == [
            ("card", -10_000),
            ("internal:opening-equity:USD", 10_000),
        ]


def test_tied_earliest_sources_each_need_review(tmp_path: Path):
    path = tmp_path / "tied.db"
    first = _profile(path)
    source = SOURCE + b"-same-opening"
    second = _variant(first, source)
    with V2ProfileStore.open(path) as store:
        store.import_source(source, DEFINITION, second, suffix=".pdf")
        account = second.payload.accounts[0]
        store.bind_source_account(second.source_sha256, account.source_identity, account.source_identity_form, "cash")
        candidate = store.earliest_source_openings()[0]
        assert len(candidate.earliest_source_ids) == 2
        for index, source_id in enumerate(candidate.earliest_source_ids):
            store.record_opening_source_review(
                "cash",
                source_id,
                opening_origin="reported",
                timing_confirmed=True,
                source_reference=f"Statement {index + 1}, page 1",
            )
            assert store.earliest_source_openings()[0].blockers == (("source_timing_unreviewed",) if index == 0 else ())
        assert store.post_reviewed_opening("cash").amount_minor == 10_000


def test_unestablished_balance_and_earlier_posting_block_opening(tmp_path: Path):
    path = tmp_path / "blocked.db"
    evidence = _profile(path)
    with V2ProfileStore.open(path) as store:
        store.record_opening_source_review(
            "cash",
            evidence.source_sha256,
            opening_origin="unestablished",
            timing_confirmed=True,
            source_reference="Page 1 uncertain",
        )
        with pytest.raises(ProfileFormatError, match="opening_review_blocked"):
            store.post_reviewed_opening("cash")
        store.record_opening_source_review(
            "cash",
            evidence.source_sha256,
            opening_origin="reported",
            timing_confirmed=True,
            source_reference="Page 1 printed",
        )
        store.connection.execute(
            "INSERT INTO JournalEntries(key,payload) VALUES (?,?)",
            (
                "earlier",
                json.dumps(
                    {
                        "key": "earlier",
                        "event_id": "earlier",
                        "posting_date": "2025-12-30",
                        "description": "Earlier adjustment",
                        "postings": [
                            {"account_id": "cash", "amount_minor": 1, "allocations": []},
                            {"account_id": "internal:opening-equity:USD", "amount_minor": -1, "allocations": []},
                        ],
                        "origin": "manual",
                        "reviewed": True,
                        "reason": "Test earlier entry",
                    }
                ),
            ),
        )
        with pytest.raises(ProfileFormatError, match="opening_earlier_posting_conflict"):
            store.post_reviewed_opening("cash")
        assert store.connection.execute("SELECT COUNT(*) FROM OpeningDecisions").fetchone() == (0,)


def test_opening_dialog_requires_saved_source_review(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from parsetrail.core.v2_workspace import V2Workspace
    from parsetrail.gui.v2_opening_review import V2OpeningReview
    from PySide6.QtWidgets import QApplication, QMessageBox

    app = QApplication.instance() or QApplication([])
    path = tmp_path / "opening.db"
    _profile(path)
    workspace = V2Workspace.open(path, tmp_path / "catalog", trusted_keys={}, preferences_path=tmp_path / "prefs.json")
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.Yes)
    dialog = V2OpeningReview(workspace)
    try:
        dialog.show()
        app.processEvents()
        assert dialog.profile_path.text() == str(path)
        assert dialog.source.count() == 1
        assert not dialog.confirm.isEnabled()
        dialog.origin.setCurrentIndex(dialog.origin.findData("reported"))
        dialog.timing.setChecked(True)
        dialog.reference.setText("Page 1 balance summary")
        assert dialog.save.isEnabled() and not dialog.confirm.isEnabled()
        dialog.save.click()
        assert dialog.confirm.isEnabled()
        dialog.note.setText("Unsaved change")
        assert not dialog.confirm.isEnabled()
        dialog.note.clear()
        assert dialog.confirm.isEnabled()
        dialog.confirm.click()
        assert dialog.decision is not None and not dialog.decision.stale
        assert "Opening posted" in dialog.status.text()
    finally:
        dialog.close()
        app.processEvents()
