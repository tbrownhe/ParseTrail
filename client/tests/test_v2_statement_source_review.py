"""Later bound statements can receive append-only provenance review."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest
from parsetrail.core.v2_profile_store import ProfileFormatError, V2ProfileStore

from devtools.parser_engine_pilot.test_table_bank_source_output import DEFINITION, SOURCE

from .test_v2_card_purchase_review import _chase_profile
from .test_v2_reviewed_openings import _profile


def _later_source(store: V2ProfileStore, original):
    source = SOURCE + b"-later-source-review"
    digest = sha256(source).hexdigest()
    old = original.payload.accounts[0]
    zero_change = old.closing
    account = old.model_copy(update={"opening": zero_change, "closing": zero_change, "rows": ()})
    payload = original.payload.model_copy(
        update={
            "start": original.payload.start.model_copy(update={"raw": "02/01/2026", "iso": "2026-02-01"}),
            "end": original.payload.end.model_copy(update={"raw": "02/28/2026", "iso": "2026-02-28"}),
            "accounts": (account,),
            "independent_balance_verified": True,
        }
    )
    later = original.model_copy(update={"source_sha256": digest, "payload": payload})
    store.import_source(source, DEFINITION, later, suffix=".pdf")
    store.bind_source_account(digest, account.source_identity, account.source_identity_form, "cash")
    return later


def test_later_statement_review_is_explicit_idempotent_and_append_only(tmp_path: Path):
    path = tmp_path / "source-review.db"
    original = _profile(path)
    with V2ProfileStore.open(path) as store:
        later = _later_source(store, original)
        with pytest.raises(ProfileFormatError, match="opening_source_not_earliest_bound"):
            store.record_opening_source_review(
                "cash",
                later.source_sha256,
                opening_origin="reported",
                timing_confirmed=True,
                source_reference="Page 1",
            )
        first = store.record_statement_source_review(
            "cash",
            later.source_sha256,
            expected_revision_id=None,
            opening_origin="reported",
            closing_origin="reported",
            timing_confirmed=True,
            posting_dates="reported",
            source_reference="Page 1, balance section",
        )
        assert first == 1
        review = next(
            item for item in store.statement_source_reviews("cash") if item.source_sha256 == later.source_sha256
        )
        assert review.opening_origin == review.closing_origin == "reported"
        assert review.posting_dates == "reported" and review.timing_confirmed
        assert (
            store.record_statement_source_review(
                "cash",
                later.source_sha256,
                expected_revision_id=first,
                opening_origin="reported",
                closing_origin="reported",
                timing_confirmed=True,
                posting_dates="reported",
                source_reference="Page 1, balance section",
            )
            == first
        )
        with pytest.raises(ProfileFormatError, match="statement_source_review_changed_since_selection"):
            store.record_statement_source_review(
                "cash",
                later.source_sha256,
                expected_revision_id=None,
                opening_origin="reported",
                closing_origin="reported",
                timing_confirmed=True,
                posting_dates="reported",
                source_reference="Stale form",
            )
        changed = store.record_statement_source_review(
            "cash",
            later.source_sha256,
            expected_revision_id=first,
            opening_origin="reported",
            closing_origin="unestablished",
            timing_confirmed=True,
            posting_dates="unverified",
            source_reference="Page 1, closing needs review",
        )
        assert changed > first
        assert store.connection.execute("SELECT COUNT(*) FROM StatementSourceReviews").fetchone() == (2,)
    with V2ProfileStore.open(path, read_only=True) as store:
        assert store.statement_source_reviews("cash")[-1].revision_id == changed
        assert store.load_import(later.source_sha256).evidence == later


def test_assumed_card_dates_cannot_be_asserted_reported(tmp_path: Path):
    path = tmp_path / "card-source-review.db"
    evidence = _chase_profile(path)
    account = evidence.payload.accounts[0]
    with V2ProfileStore.open(path) as store:
        store.bind_source_account(evidence.source_sha256, account.source_identity, account.source_identity_form, "card")
        with pytest.raises(ProfileFormatError, match="reported_posting_dates_unavailable"):
            store.record_statement_source_review(
                "card",
                evidence.source_sha256,
                expected_revision_id=None,
                opening_origin="unestablished",
                closing_origin="unestablished",
                timing_confirmed=False,
                posting_dates="reported",
                source_reference="Page 1",
            )
        store.record_statement_source_review(
            "card",
            evidence.source_sha256,
            expected_revision_id=None,
            opening_origin="unestablished",
            closing_origin="unestablished",
            timing_confirmed=False,
            posting_dates="estimated",
            source_reference="Page 1 date column",
        )
        assert store.statement_source_reviews("card")[0].posting_dates == "estimated"


def test_later_review_does_not_stale_earliest_opening(tmp_path: Path):
    path = tmp_path / "later-after-opening.db"
    first = _profile(path)
    with V2ProfileStore.open(path) as store:
        store.record_opening_source_review(
            "cash",
            first.source_sha256,
            opening_origin="reported",
            timing_confirmed=True,
            source_reference="First statement, page 1",
        )
        store.post_reviewed_opening("cash")
        later = _later_source(store, first)
        store.record_statement_source_review(
            "cash",
            later.source_sha256,
            expected_revision_id=None,
            opening_origin="reported",
            closing_origin="reported",
            timing_confirmed=True,
            posting_dates="reported",
            source_reference="Later statement, page 1",
        )
        assert not store.opening_decision("cash").stale


def test_saved_period_review_action_records_later_source_without_journal(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from parsetrail.gui.v2_statement_coverage import V2StatementCoverageDialog
    from parsetrail.gui.v2_statement_source_review import V2StatementSourceReview
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    path = tmp_path / "review-ui.db"
    first = _profile(path)
    with V2ProfileStore.open(path) as store:
        later = _later_source(store, first)

    def fill_and_save(dialog):
        assert dialog.section.source_sha256 == later.source_sha256
        dialog.opening.setCurrentIndex(dialog.opening.findData("reported"))
        dialog.closing.setCurrentIndex(dialog.closing.findData("reported"))
        dialog.timing.setChecked(True)
        dialog.posting_dates.setCurrentIndex(dialog.posting_dates.findData("reported"))
        dialog.reference.setText("Page 1, later statement")
        assert dialog.save.isEnabled()
        dialog.save.click()
        return dialog.result()

    monkeypatch.setattr(V2StatementSourceReview, "exec", fill_and_save)
    dialog = V2StatementCoverageDialog(path)
    try:
        dialog.show()
        app.processEvents()
        index = next(i for i, row in enumerate(dialog.model.rows) if row.source_sha256 == later.source_sha256)
        dialog.table.selectRow(index)
        assert dialog.review_source_button.isEnabled()
        assert "Not recorded" in dialog.review_source_button.text()
        dialog.review_source_button.click()
        assert dialog.model.data(dialog.model.index(index, 10)) == "Recorded"
        assert "Recorded" in dialog.review_source_button.text()
        with V2ProfileStore.open(path, read_only=True) as store:
            assert store.connection.execute("SELECT COUNT(*) FROM JournalEntries").fetchone() == (0,)
            assert store.statement_source_reviews("cash")[-1].source_reference == "Page 1, later statement"
    finally:
        dialog.close()
        app.processEvents()


def test_card_source_review_disables_reported_date_choice(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from parsetrail.gui.v2_statement_source_review import V2StatementSourceReview
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    path = tmp_path / "card-review-ui.db"
    evidence = _chase_profile(path)
    account = evidence.payload.accounts[0]
    with V2ProfileStore.open(path) as store:
        store.bind_source_account(evidence.source_sha256, account.source_identity, account.source_identity_form, "card")
        section = store.statement_coverage()[0]
    dialog = V2StatementSourceReview(path, section)
    try:
        dialog.show()
        app.processEvents()
        reported = dialog.posting_dates.findData("reported")
        assert not dialog.posting_dates.model().item(reported).isEnabled()
        assert "unavailable" in dialog.status.text()
    finally:
        dialog.close()
        app.processEvents()
