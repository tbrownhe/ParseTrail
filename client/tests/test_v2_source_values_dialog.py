"""Source points and scoped review forms exercise actual disposable services."""

from datetime import date
from types import SimpleNamespace

import pytest
from parsetrail.core.v2_profile_store import FinancialAccount, ProfileFormatError, V2ProfileStore
from parsetrail.core.v2_workspace import V2Workspace

from . import test_v2_source_values as source_fixtures
from .test_v2_source_values import FAMILY_FACTS, manual, record_source, setup, withdraw


@pytest.fixture(scope="module")
def samples():
    return source_fixtures.samples.__wrapped__()


@pytest.fixture(autouse=True)
def app(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QMessageBox

    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
    monkeypatch.setattr(QMessageBox, "warning", lambda _p, title, message: pytest.fail(f"{title}: {message}"))
    return QApplication.instance() or QApplication([])


def dialog(path):
    from parsetrail.gui.v2_account_anchors import V2AccountAnchors

    return V2AccountAnchors(path, "target", initial_tab="source_values")


def source_form(view):
    view.source_table.selectRow(0)
    view.source_reference.setText("Inspected exact printed closing and section")
    view.source_reason.setText("Keep this independently reviewed nonposting endpoint")
    view.source_ack.setChecked(True)


def value_form(view, amount, day):
    view.value_amount.setText(amount)
    view.value_date.setText(day.isoformat())
    view.value_reference.setText("Independent manual information")
    view.value_reason.setText("Manual point, no source assertion")
    view.value_ack.setChecked(True)


@pytest.mark.parametrize(
    "family",
    [
        "capital-one-loan-pilot-definition.json",
        "wells-loan-pilot-definition.json",
        "hsa-cash-pilot-definition.json",
        "fidelity-hsa-summary-pilot-definition.json",
    ],
)
def test_source_sign_scope_immutable_preview_cancel_record_reopen(tmp_path, samples, monkeypatch, family):
    from parsetrail.gui import v2_account_anchors as module
    from PySide6.QtWidgets import QAbstractItemView, QMessageBox

    path = tmp_path / "source.db"
    evidence = setup(path, samples, family)
    view = dialog(path)
    assert view.tabs.currentIndex() == 3 and view.tabs.tabText(1) == "Dated values"
    assert not view.source_save.isEnabled() and view.source_table.currentRow() == -1
    assert view.source_table.editTriggers() == QAbstractItemView.NoEditTriggers
    source_form(view)
    candidate = view.snapshot.source_value_candidates[0]
    detail = view.source_details.toPlainText()
    assert candidate.amount_minor == FAMILY_FACTS[family][2]
    assert candidate.proof.closing.raw in detail and candidate.proof.closing.provenance in detail
    assert candidate.tracking_scope.replace("_", " ") in detail
    assert "negate" in detail if family.startswith("capital") else "do not invert" in detail
    assert "No authored" in detail and "capture" in detail.lower()
    previews = []
    monkeypatch.setattr(
        module,
        "preview_saved_source",
        lambda *args, **kwargs: previews.append(args) or SimpleNamespace(exec=lambda: None),
    )
    view.source_preview.click()
    assert evidence.source_sha256 in previews[0]
    original = path.read_bytes()
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.No)
    view.source_save.click()
    assert path.read_bytes() == original
    prompts = []
    monkeypatch.setattr(QMessageBox, "question", lambda _p, _t, message: prompts.append(message) or QMessageBox.Yes)
    view.source_save.click()
    assert "no posting" in prompts[0].lower() or "no journal" in prompts[0].lower()
    assert view.snapshot.dated_values[0].origin == "source"
    boundary = view._boundary_details()
    assert "Reviewed dated value" in boundary and "Manual dated value" not in boundary
    assert "see dated-value history for manual/source origin and proof" in boundary
    with V2ProfileStore.open(path, read_only=True) as store:
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
        assert store._active_consumed() == {} and store.statement_source_review_history("target") == ()
        assert store.account_anchor_snapshot("target").opening is None
    view.close()
    reopened = dialog(path)
    assert reopened.value_history.rowCount() == 1 and reopened.value_history.item(0, 7).text() == "Source"
    assert "Source-backed proof" in reopened.value_details.toPlainText()
    reopened.close()


def test_conflict_ack_and_cross_origin_corrections_preserve_old_proof(tmp_path, samples, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    path = tmp_path / "conflict.db"
    setup(path, samples)
    with V2ProfileStore.open(path) as store:
        sourced = record_source(store)
    view = dialog(path)
    value_form(view, "9000.00", sourced.value_date)
    assert view.value_allow_conflict.isEnabled() and not view.value_save.isEnabled()
    assert sourced.value_date.isoformat() in view.value_conflict_note.text()
    view.value_allow_conflict.setChecked(True)
    assert view.value_save.isEnabled()
    view.value_save.click()
    assert view.snapshot.value_status == "conflict" and view.snapshot.latest_dated_value is None
    assert "Conflict" in view.value_state.text()
    opposing = next(v for v in view.snapshot.dated_values if v.origin == "manual")
    source_form(view)
    view.source_target.setCurrentIndex(view.source_target.findData(opposing.value_id))
    assert not view.source_allow_conflict.isEnabled() and view.source_save.isEnabled()
    view.source_save.click()
    assert view.snapshot.value_status == "known"
    current = view.snapshot.dated_values[0]
    view.value_target.setCurrentIndex(view.value_target.findData(current.value_id))
    assert "manual" in view.value_origin_notice.text().lower() and "source" in view.value_origin_notice.text().lower()
    value_form(view, "9500.00", current.value_date)
    prompts = []
    monkeypatch.setattr(QMessageBox, "question", lambda _p, _t, message: prompts.append(message) or QMessageBox.Yes)
    view.value_save.click()
    assert "manual" in prompts[0].lower()
    assert view.snapshot.dated_values[0].source_proof is None
    assert any(v.source_proof is not None and v.state == "superseded" for v in view.snapshot.dated_values)
    view.close()


@pytest.mark.parametrize("origin", ["manual", "source"])
def test_withdraw_unknown_cancel_and_historical_retry_preserves_fresh_point(tmp_path, samples, monkeypatch, origin):
    from PySide6.QtWidgets import QMessageBox

    path = tmp_path / "withdraw.db"
    setup(path, samples)
    with V2ProfileStore.open(path) as store:
        value = record_source(store) if origin == "source" else manual(store, 0, date(2026, 1, 31))
    stale = dialog(path)
    assert "Reviewed dated value" in stale._boundary_details()
    stale.value_withdraw_reason.setText("Withdraw unsupported observation")
    original = path.read_bytes()
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.No)
    stale.value_withdraw.click()
    assert path.read_bytes() == original
    monkeypatch.setattr(QMessageBox, "question", lambda *_args: QMessageBox.Yes)
    # A separate view records the exact request while the original form remains loaded.
    current = dialog(path)
    current.value_withdraw_reason.setText("Withdraw unsupported observation")
    current.value_withdraw.click()
    assert current.snapshot.value_status == "missing" and current.snapshot.latest_dated_value is None
    assert current.snapshot.dated_values[0].state == "withdrawn"
    with V2ProfileStore.open(path) as store:
        fresh = record_source(store)
    stale.value_withdraw.click()
    assert stale.snapshot.latest_dated_value.value_id == fresh.value_id
    assert stale.snapshot.latest_dated_value.state == "active" and value.value_id != fresh.value_id
    assert "Refreshed" in stale.status.text() and "remains unknown" not in stale.status.text()
    current.close()
    stale.close()


def test_source_stale_and_failed_read_clear_actions(tmp_path, samples, monkeypatch):
    path = tmp_path / "stale.db"
    evidence = setup(path, samples)
    view = dialog(path)
    source_form(view)
    with V2ProfileStore.open(path) as store:
        store.record_statement_source_review(
            "target",
            evidence.source_sha256,
            expected_revision_id=None,
            opening_origin="unestablished",
            closing_origin="unestablished",
            timing_confirmed=False,
            posting_dates="unverified",
            source_reference="New authored context",
        )
    warnings = []
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "warning", lambda _p, _t, message: warnings.append(message))
    view.source_save.click()
    assert warnings and not view.source_save.isEnabled() and view.snapshot.dated_values == ()
    assert not view.source_ack.isChecked()
    monkeypatch.setattr(
        V2ProfileStore,
        "account_anchor_snapshot",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ProfileFormatError("malformed")),
    )
    view.refresh()
    assert view.snapshot is None and view.source_table.rowCount() == 0
    assert not view.source_save.isEnabled() and not view.source_preview.isEnabled()
    view.close()


@pytest.mark.parametrize("adapter", ["statement", "opening"])
def test_loaded_unreviewed_section_a_cannot_authorize_section_b_opening(tmp_path, samples, monkeypatch, adapter):
    path = tmp_path / "scoped.db"
    evidence = setup(path, samples, "occu-bank-pilot-definition.json")
    first, second = evidence.payload.accounts
    workspace = V2Workspace.open(
        path, tmp_path / "catalog", trusted_keys={}, preferences_path=tmp_path / "preferences.json"
    )
    if adapter == "statement":
        from parsetrail.gui.v2_statement_source_review import V2StatementSourceReview

        with V2ProfileStore.open(path, read_only=True) as store:
            section = store.statement_source_review_snapshot("target", evidence.source_sha256).section
        view = V2StatementSourceReview(path, section)
        view.opening.setCurrentIndex(view.opening.findData("reported"))
        view.closing.setCurrentIndex(view.closing.findData("reported"))
        view.posting_dates.setCurrentIndex(view.posting_dates.findData("unverified"))
    else:
        from parsetrail.gui.v2_opening_review import V2OpeningReview

        view = V2OpeningReview(workspace)
        view.origin.setCurrentIndex(view.origin.findData("reported"))
    view.timing.setChecked(True)
    view.reference.setText("Section A printed source review only")
    assert view.save.isEnabled()
    with V2ProfileStore.open(path) as store:
        store.clear_source_account_binding(evidence.source_sha256, first.source_identity, first.source_identity_form)
        store.bind_source_account(evidence.source_sha256, second.source_identity, second.source_identity_form, "target")
    warnings = []
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(QMessageBox, "warning", lambda _p, _t, message: warnings.append(message))
    view.save.click()
    assert warnings and not view.save.isEnabled()
    assert "statement_source_review_" not in warnings[0]
    with V2ProfileStore.open(path) as store:
        assert store.statement_source_review_history("target") == ()
        assert store.statement_source_review_snapshot("target", evidence.source_sha256).review is None
        with pytest.raises(ProfileFormatError, match="opening_review_blocked"):
            store.post_reviewed_opening("target")
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
    view.close()


def test_empty_source_value_binding_protection_plain_reason_and_retired_proof(tmp_path, samples):
    from parsetrail.core.v2_profile_store import BindingCorrectionTarget
    from parsetrail.gui.v2_binding_correction import V2BindingCorrection, ordinary_binding_lock_notice

    path = tmp_path / "empty.db"
    evidence = setup(path, samples, empty=True)
    with V2ProfileStore.open(path) as store:
        value = record_source(store)
        store.add_financial_account(
            FinancialAccount("other", "Other principal", "liability", "synthetic", tracking_scope="principal_component")
        )
    section = evidence.payload.accounts[0]
    target = BindingCorrectionTarget(
        evidence.source_sha256, "source", section.source_identity, section.source_identity_form
    )
    view = V2BindingCorrection(path, target)
    view.destination.setCurrentIndex(view.destination.findData("other"))
    view.reason.setText("Explicit account assignment review")
    assert not view.save_button.isEnabled() and "Withdraw that value" in view.blockers.text()
    assert "active source closing value" in ordinary_binding_lock_notice(
        ("account_binding_source_backed_dated_value_anchor",)
    )
    with V2ProfileStore.open(path) as store:
        withdraw(store, value)
    view.refresh()
    view.destination.setCurrentIndex(view.destination.findData("other"))
    view.reason.setText("Explicit account assignment after value withdrawal")
    assert view.save_button.isEnabled()
    view.save_button.click()
    with V2ProfileStore.open(path, read_only=True) as store:
        old = store.account_anchor_snapshot("target").dated_values[0]
        assert old.state == "withdrawn" and old.source_proof.source_sha256 == evidence.source_sha256
        assert store.account_anchor_snapshot("other").dated_values == ()
    view.close()


@pytest.mark.parametrize("qualification", ["derived", "unknown_closing", "assumed_date", "wrong_scope"])
def test_finite_candidate_qualifications_remain_visible_and_refused_when_unavailable(tmp_path, samples, qualification):
    path = tmp_path / "qualified.db"

    def qualified(evidence):
        payload = evidence.payload
        section = payload.accounts[0]
        if qualification in {"derived", "unknown_closing"}:
            changes = {"raw": None, "provenance": "derived" if qualification == "derived" else "unknown"}
            if qualification == "unknown_closing":
                changes["minor"] = None
            section = section.model_copy(update={"closing": section.closing.model_copy(update=changes)})
        endpoint = payload.end
        if qualification in {"derived", "assumed_date"}:
            endpoint = endpoint.model_copy(
                update={"raw": None, "provenance": "derived" if qualification == "derived" else "assumed"}
            )
        return evidence.model_copy(
            update={
                "payload": payload.model_copy(
                    update={"accounts": (section,), "end": endpoint, "independent_balance_verified": False}
                )
            }
        )

    setup(path, samples, transform=qualified)
    if qualification == "wrong_scope":
        with V2ProfileStore.open(path) as store:
            store.update_financial_account(
                FinancialAccount("target", "Whole account", "liability", "synthetic", tracking_scope="account_total")
            )
    view = dialog(path)
    source_form(view)
    assert "capture" in view.source_details.toPlainText().lower()
    assert "source_value_" not in view.source_blockers.text()
    if qualification == "derived":
        assert "derived" in view.source_details.toPlainText() and "not printed" in view.source_details.toPlainText()
        assert view.source_save.isEnabled()
        view.source_save.click()
        assert view.snapshot.dated_values[0].source_proof.closing.provenance == "derived"
    else:
        assert view.snapshot.source_value_candidates[0].proof is None
        assert not view.source_save.isEnabled() and view.snapshot.dated_values == ()
        assert view.source_preview.isEnabled()
    view.close()
