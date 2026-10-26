"""Explicit opening correction keeps source assertions and saved decision history distinct."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from parsetrail.core.source_evidence import DateValue
from parsetrail.core.v2_profile_store import FinancialAccount, V2ProfileStore
from parsetrail.core.v2_table_card_source_output import from_anchored_card
from parsetrail.core.v2_workspace import V2Workspace

from devtools.parser_engine_pilot.test_table_card_source_output import DEFINITION as CARD_DEFINITION
from devtools.parser_engine_pilot.test_table_card_source_output import SOURCE as CARD_SOURCE
from devtools.parser_engine_pilot.test_table_card_source_output import evidence as card_channels

from .test_v2_reviewed_openings import _profile
from .test_v2_source_openings import _variant


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QMessageBox

    def unexpected_warning(_parent, title, message):
        pytest.fail(f"{title}: {message}")

    monkeypatch.setattr(QMessageBox, "warning", unexpected_warning)

    return QApplication.instance() or QApplication([])


def _review(store, evidence, *, reference="Inspected synthetic printed opening", note=""):
    previous = next(
        (review for review in store.statement_source_reviews("cash") if review.source_sha256 == evidence.source_sha256),
        None,
    )
    store.record_statement_source_review(
        "cash",
        evidence.source_sha256,
        expected_revision_id=previous.revision_id if previous else None,
        opening_origin="reported",
        closing_origin="reported",
        timing_confirmed=True,
        posting_dates="reported",
        source_reference=reference,
        note=note,
    )


def _initial(profile: Path, *, amount_minor: int = 10_000):
    evidence = _profile(profile, amount_minor=amount_minor)
    with V2ProfileStore.open(profile) as store:
        _review(store, evidence)
        store.post_reviewed_opening("cash")
    return evidence


def _earlier(store, evidence, *, amount_minor: int):
    source = f"synthetic earlier source with opening {amount_minor}".encode()
    earlier = _variant(evidence, source, opening_minor=amount_minor)
    section = earlier.payload.accounts[0].model_copy(update={"rows": ()})
    payload = earlier.payload.model_copy(
        update={
            "start": DateValue(
                raw="12/01/2025", iso="2025-12-01", provenance="observed", locations=evidence.payload.start.locations
            ),
            "end": DateValue(
                raw="12/31/2025", iso="2025-12-31", provenance="observed", locations=evidence.payload.end.locations
            ),
            "accounts": (section,),
        }
    )
    earlier = earlier.model_copy(update={"payload": payload})
    definition = store.load_import(evidence.source_sha256).definition
    store.import_source(source, definition, earlier, suffix=".pdf")
    store.bind_source_account(earlier.source_sha256, section.source_identity, section.source_identity_form, "cash")
    _review(store, earlier)
    return earlier


def _dialog(profile: Path):
    from parsetrail.gui.v2_opening_review import V2OpeningReview

    workspace = V2Workspace.open(
        profile, profile.parent / "catalog", trusted_keys={}, preferences_path=profile.parent / "preferences.json"
    )
    return V2OpeningReview(workspace)


def _cell(model, row: int, column: int):
    return model.data(model.index(row, column))


def test_basis_only_correction_requires_reason_and_clean_source_form_and_keeps_history(
    tmp_path: Path, app, monkeypatch
):
    from PySide6.QtWidgets import QMessageBox

    profile = tmp_path / "basis.db"
    evidence = _initial(profile)
    with V2ProfileStore.open(profile) as store:
        _review(store, evidence, reference="Rechecked printed opening")
        original_key = store.opening_decision("cash").entry_key
    questions = []

    def confirm(_parent, _title, message):
        questions.append(message)
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", confirm)
    dialog = _dialog(profile)
    try:
        dialog.show()
        app.processEvents()
        assert "Saved opening" not in dialog.saved_label.text()
        assert "$100.00 as of 2025-12-31" in dialog.saved_label.text()
        assert "stale" in dialog.saved_label.text()
        assert dialog.history_model.rowCount() == 1
        assert not dialog.confirm.isEnabled()
        assert not dialog.correct.isEnabled()
        dialog.correction_reason.setText("Revalidated earliest source basis")
        assert dialog.correct.isEnabled()
        dialog.note.setText("Unsaved source assessment")
        assert not dialog.correct.isEnabled()
        dialog.note.clear()
        assert dialog.correct.isEnabled()
        dialog.correct.click()
        assert len(questions) == 1
        assert "Saved: $100.00 as of 2025-12-31" in questions[0]
        assert "Current reviewed candidate: $100.00 as of 2025-12-31" in questions[0]
        assert "When only the source basis changes" in questions[0]
        assert dialog.decision.revision_id > 0 and not dialog.decision.stale
        assert dialog.decision.entry_key == original_key
        assert dialog.history_model.rowCount() == 2
        assert _cell(dialog.history_model, 0, 1) == "$100.00"
        assert _cell(dialog.history_model, 1, 3) == "Initial reviewed opening"
        assert "Opening corrected" in dialog.status.text()
        assert not dialog.correct.isEnabled()
        assert dialog.correction_reason.text() == ""
        dialog.tabs.setCurrentIndex(1)
        app.processEvents()
        assert dialog.history_table.viewport().height() > 100
        assert "Decision version:" in dialog.history_details.text()
    finally:
        dialog.close()
        app.processEvents()
    reopened = _dialog(profile)
    try:
        assert reopened.history_model.rowCount() == 2
        assert reopened.decision.entry_key == original_key
    finally:
        reopened.close()
        app.processEvents()


@pytest.mark.parametrize("initial_minor,new_minor", [(10_000, 0), (0, 25_000)])
def test_correct_amount_cutoff_and_zero_decisions_are_explicit(
    tmp_path: Path, app, monkeypatch, initial_minor, new_minor
):
    from PySide6.QtWidgets import QMessageBox

    profile = tmp_path / "amount.db"
    evidence = _initial(profile, amount_minor=initial_minor)
    with V2ProfileStore.open(profile) as store:
        _earlier(store, evidence, amount_minor=new_minor)
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.Yes)
    dialog = _dialog(profile)
    try:
        assert "Start: 2025-12-01" in dialog.candidate_label.text()
        assert "2025-12-31" in dialog.saved_label.text()
        dialog.correction_reason.setText("Earlier original statement establishes the opening")
        assert dialog.correct.isEnabled()
        dialog.correct.click()
        assert dialog.decision.amount_minor == new_minor
        assert dialog.decision.cutoff_date.isoformat() == "2025-11-30"
        assert (dialog.decision.entry_key is None) == (new_minor == 0)
        assert dialog.history_model.rowCount() == 2
        assert _cell(dialog.history_model, 0, 5) == ("No posting (zero)" if new_minor == 0 else "Retained reference")
        assert "current source basis" in dialog.saved_label.text()
    finally:
        dialog.close()
        app.processEvents()


def test_correction_cancel_writes_nothing(tmp_path: Path, app, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    profile = tmp_path / "cancel.db"
    evidence = _initial(profile)
    with V2ProfileStore.open(profile) as store:
        _review(store, evidence, reference="Fresh inspection before cancellation")
    before = hashlib.sha256(profile.read_bytes()).hexdigest()
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.No)
    dialog = _dialog(profile)
    try:
        dialog.correction_reason.setText("Considered correction")
        dialog.correct.click()
        assert dialog.history_model.rowCount() == 1
        assert dialog.decision.stale
        assert dialog.correction_reason.text() == "Considered correction"
    finally:
        dialog.close()
        app.processEvents()
    assert hashlib.sha256(profile.read_bytes()).hexdigest() == before


@pytest.mark.parametrize("change", ["decision", "basis"])
def test_correction_refuses_stale_decision_or_source_basis_and_reloads(tmp_path: Path, app, monkeypatch, change):
    from PySide6.QtWidgets import QMessageBox

    profile = tmp_path / "stale.db"
    evidence = _initial(profile)
    with V2ProfileStore.open(profile) as store:
        _review(store, evidence, reference="First revised inspection")
    warnings = []
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, "warning", lambda _parent, _title, message: warnings.append(message))
    dialog = _dialog(profile)
    try:
        old_version, old_basis = dialog.decision.version, dialog.basis
        dialog.correction_reason.setText("Correction from loaded form")
        with V2ProfileStore.open(profile) as store:
            if change == "decision":
                store.correct_reviewed_opening(
                    "cash",
                    expected_decision_version=old_version,
                    expected_basis_sha256=old_basis,
                    reason="A concurrent confirmed correction",
                )
            else:
                _review(store, evidence, reference="Concurrent newer source inspection")
        before = hashlib.sha256(profile.read_bytes()).hexdigest()
        dialog.correct.click()
        assert len(warnings) == 1
        assert "changed" in warnings[0]
        assert hashlib.sha256(profile.read_bytes()).hexdigest() == before
        assert dialog.decision.version != old_version if change == "decision" else dialog.basis != old_basis
    finally:
        dialog.close()
        app.processEvents()


def test_stale_source_assessment_cannot_overwrite_newer_review(tmp_path: Path, app, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    profile = tmp_path / "stale-source.db"
    evidence = _initial(profile)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda _parent, _title, message: warnings.append(message))
    dialog = _dialog(profile)
    try:
        dialog.note.setText("Old form edited locally")
        assert dialog.save.isEnabled()
        with V2ProfileStore.open(profile) as store:
            _review(store, evidence, reference="Concurrent assessment", note="Newer saved note")
            expected = store.statement_source_reviews("cash")[0]
        before = hashlib.sha256(profile.read_bytes()).hexdigest()
        dialog.save.click()
        assert len(warnings) == 1
        assert "changed after the form was loaded" in warnings[0]
        assert dialog.note.text() == "Newer saved note"
        assert not dialog.save.isEnabled()
        assert hashlib.sha256(profile.read_bytes()).hexdigest() == before
        with V2ProfileStore.open(profile, read_only=True) as store:
            actual = store.statement_source_reviews("cash")[0]
            assert actual == expected
            assert actual.closing_origin == actual.posting_dates == "reported"
    finally:
        dialog.close()
        app.processEvents()


def test_conflicting_earliest_sources_keep_correction_blocked_and_preserve_unknown(tmp_path: Path, app):
    profile = tmp_path / "conflict.db"
    evidence = _initial(profile)
    source = b"synthetic tied source with conflicting opening"
    conflicting = _variant(evidence, source, opening_minor=20_000)
    with V2ProfileStore.open(profile) as store:
        store.import_source(source, store.load_import(evidence.source_sha256).definition, conflicting, suffix=".pdf")
        section = conflicting.payload.accounts[0]
        store.bind_source_account(
            conflicting.source_sha256, section.source_identity, section.source_identity_form, "cash"
        )
    before = hashlib.sha256(profile.read_bytes()).hexdigest()
    dialog = _dialog(profile)
    try:
        assert "printed candidate: unavailable" in dialog.candidate_label.text()
        assert "$100.00 as of 2025-12-31" in dialog.saved_label.text()
        assert "conflicting printed openings" in dialog.status.text()
        dialog.correction_reason.setText("Cannot settle conflicting source facts")
        assert not dialog.confirm.isEnabled()
        assert not dialog.correct.isEnabled()
        dialog._correct()
        assert dialog.history_model.rowCount() == 1
    finally:
        dialog.close()
        app.processEvents()
    assert hashlib.sha256(profile.read_bytes()).hexdigest() == before


def test_liability_correction_and_history_show_positive_amount_owed(tmp_path: Path, app, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    profile = tmp_path / "card.db"
    evidence = from_anchored_card(CARD_DEFINITION, *card_channels())
    with V2ProfileStore.create(profile) as store:
        store.import_source(CARD_SOURCE, CARD_DEFINITION, evidence, suffix=".pdf")
        store.add_financial_account(FinancialAccount("card", "Card", "liability", "citi"))
        section = evidence.payload.accounts[0]
        store.bind_source_account(evidence.source_sha256, section.source_identity, section.source_identity_form, "card")
        store.record_opening_source_review(
            "card",
            evidence.source_sha256,
            opening_origin="reported",
            timing_confirmed=True,
            source_reference="Printed card opening",
        )
        store.post_reviewed_opening("card")
        store.record_opening_source_review(
            "card",
            evidence.source_sha256,
            opening_origin="reported",
            timing_confirmed=True,
            source_reference="Rechecked card opening",
        )
    questions = []

    def confirm(_parent, _title, message):
        questions.append(message)
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "question", confirm)
    dialog = _dialog(profile)
    try:
        assert "printed candidate: $100.00" in dialog.candidate_label.text()
        assert "$100.00 as of" in dialog.saved_label.text()
        dialog.correction_reason.setText("Revalidated card source")
        dialog.correct.click()
        assert "Saved: $100.00" in questions[0]
        assert dialog.decision.amount_minor == -10_000
        assert _cell(dialog.history_model, 0, 1) == "$100.00"
        assert _cell(dialog.history_model, 1, 1) == "$100.00"
    finally:
        dialog.close()
        app.processEvents()


def test_candidate_and_basis_stay_in_one_snapshot_across_concurrent_new_source(tmp_path: Path, app, monkeypatch):
    profile = tmp_path / "snapshot.db"
    evidence = _initial(profile)
    original_snapshot = V2ProfileStore.opening_review_snapshot
    calls = []

    def concurrent_new_source(store, account_id):
        snapshot = original_snapshot(store, account_id)
        calls.append(snapshot)
        if len(calls) == 1:
            with V2ProfileStore.open(profile) as writer:
                _earlier(writer, evidence, amount_minor=0)
        return snapshot

    monkeypatch.setattr(V2ProfileStore, "opening_review_snapshot", concurrent_new_source)
    dialog = _dialog(profile)
    try:
        assert len(calls) == 1
        assert dialog.basis == calls[0].basis_sha256
        assert "printed candidate: $100.00" in dialog.candidate_label.text()
        assert not dialog.decision.stale
        dialog.refresh()
        assert len(calls) == 2
        assert "printed candidate: $0.00" in dialog.candidate_label.text()
        assert dialog.basis != calls[0].basis_sha256
        assert dialog.decision.stale
        dialog.correction_reason.setText("Earlier source reviewed after refresh")
        assert dialog.correct.isEnabled()
    finally:
        dialog.close()
        app.processEvents()
