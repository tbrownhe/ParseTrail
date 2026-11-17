"""Explicit standing consent posts only complete new lender-side evidence."""

import json
import sqlite3
from datetime import date
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from parsetrail.core.v2_data_catalog import key_id_for_public_key
from parsetrail.core.v2_import_accounts import ImportAccountChoice, prepare_import_accounts
from parsetrail.core.v2_loan_automation import AUTOMATIC_REASON
from parsetrail.core.v2_preferences import V2Preferences, load_preferences, save_preferences
from parsetrail.core.v2_profile_store import FinancialAccount, V2ProfileStore
from parsetrail.core.v2_workspace import V2Workspace
from scripts.v2_catalog_release import signed_catalog_bytes

from devtools.parser_engine_pilot.synthetic_family_sources import family_sources, pdf_document, text_page
from devtools.parser_engine_pilot.test_loan_history_lines import lines


def loan_account():
    return FinancialAccount(
        "loan",
        "Vehicle financing",
        "liability",
        "capital_one",
        tracking_scope="principal_component",
        product_type="loan",
    )


def loan_workspace(tmp_path, *, existing_account=True):
    pilot = Path(__file__).resolve().parents[2] / "devtools/parser_engine_pilot"
    name = "capital-one-loan-pilot-definition.json"
    case = next(item for item in family_sources() if item.definition_name == name)
    definitions = tmp_path / "definitions"
    definitions.mkdir()
    (definitions / name).write_bytes((pilot / name).read_bytes())
    contexts = json.loads((pilot / "account-contexts.json").read_bytes())
    parser_id = json.loads((pilot / name).read_bytes())["parser_id"]
    (definitions / "account-contexts.json").write_text(json.dumps({parser_id: contexts[parser_id]}))
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    snapshot, signature, _catalog = signed_catalog_bytes(
        definitions, private, release_sequence=1, source_revision="a" * 40
    )
    workspace = V2Workspace.create(
        tmp_path / "review.db",
        tmp_path / "catalog",
        trusted_keys={key_id_for_public_key(public): public},
        preferences_path=tmp_path / "preferences.json",
    )
    release = tmp_path / "release"
    release.mkdir()
    (release / "catalog.json").write_bytes(snapshot)
    (release / "catalog.sig").write_bytes(signature)
    workspace.install_catalog_release(release)
    if existing_account:
        with V2ProfileStore.open(workspace.profile_path) as store:
            store.add_financial_account(loan_account())
    path = tmp_path / "payment.pdf"
    path.write_bytes(case.source)
    return workspace, path


def choose_loan(_path, review):
    new_accounts = () if any(account.id == "loan" for account in review.accounts) else (loan_account(),)
    return prepare_import_accounts(
        review,
        tuple(ImportAccountChoice(group.group_id, "loan") for group in review.groups),
        "pdf_capitaloneauto_202402",
        new_accounts=new_accounts,
    )


def enable(workspace):
    workspace.set_auto_post_loan_payments(True)
    workspace.set_allow_assumed_posting_dates(True)


def test_preferences_default_old_file_validation_and_setter_preservation(tmp_path):
    path = tmp_path / "preferences.json"
    assert not load_preferences(path).auto_post_loan_payments
    path.write_text('{"allow_abbreviated_account_matching": false}')
    assert not load_preferences(path).auto_post_loan_payments
    for bad in (1, "true", None):
        path.write_text(json.dumps({"allow_abbreviated_account_matching": False, "auto_post_loan_payments": bad}))
        with pytest.raises(ValueError, match="v2_preferences_shape"):
            load_preferences(path)
    save_preferences(path, V2Preferences(auto_post_loan_payments=True))
    assert load_preferences(path).auto_post_loan_payments


def test_other_preference_setters_preserve_automation(tmp_path):
    workspace, _path = loan_workspace(tmp_path)
    workspace.set_auto_post_loan_payments(True)
    workspace.set_allow_abbreviated_account_matching(True)
    workspace.set_allow_assumed_posting_dates(True)
    workspace.set_import_preview_mode("when_needed")
    assert workspace.preferences() == V2Preferences(True, True, "when_needed", True)
    for bad in (1, "true", None):
        with pytest.raises(ValueError, match="invalid_loan_automation_preference"):
            workspace.set_auto_post_loan_payments(bad)


def test_opt_in_posts_exact_lender_side_and_retry_or_withdrawal_never_reposts(tmp_path):
    workspace, path = loan_workspace(tmp_path)
    enable(workspace)
    result = workspace.import_file(path, review_import=choose_loan)
    assert result.loan_automation.status == "posted"
    assert (result.loan_automation.principal_minor, result.loan_automation.interest_minor) == (20000, 2000)
    with V2ProfileStore.open(workspace.profile_path) as store:
        event = store.loan_history()[0]
        assert event.reason == AUTOMATIC_REASON and result.source_sha256 in event.reference
        assert event.manifest.bank is None
        entries = store.reviewed_journal_export(start=date(2026, 1, 1), end=date(2026, 2, 1)).entries
        assert [(posting.account_id, posting.amount_minor) for posting in entries[0].postings] == [
            ("loan", 20000),
            ("builtin:loan-interest", 2000),
            ("internal:transfer-clearing:USD", -22000),
        ]
        store.withdraw_reviewed_loan(event.event_id, expected_event_version=event.version, reason="Owner correction")
    retry = workspace.import_file(path, review_import=lambda *_: pytest.fail("Saved retry cannot ask"))
    assert retry.status == "already_imported" and retry.loan_automation is None
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert len(store.loan_history()) == 1 and store.loan_history()[0].status == "cancelled"
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (2,)


@pytest.mark.parametrize("case", ["off", "enable_during_review", "new_account", "date_off", "revoke"])
def test_manual_fallback_and_future_only_consent(tmp_path, case):
    workspace, path = loan_workspace(tmp_path, existing_account=case != "new_account")
    if case != "off" and case != "enable_during_review":
        enable(workspace)
    if case == "date_off":
        workspace.set_allow_assumed_posting_dates(False)

    def choose(source, review):
        if case == "enable_during_review":
            enable(workspace)
        if case == "revoke":
            workspace.set_auto_post_loan_payments(False)
        return choose_loan(source, review)

    result = workspace.import_file(path, review_import=choose)
    assert result.status == "imported"
    if case in {"off", "enable_during_review"}:
        assert result.loan_automation is None
    else:
        assert result.loan_automation.status == "needs_review"
        assert (
            result.loan_automation.reason_code
            == {
                "new_account": "loan_auto_account_new",
                "date_off": "loan_auto_date_permission_required",
                "revoke": "loan_auto_changed",
            }[case]
        )
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert len(store.source_ids()) == 1 and not store.loan_history()
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)


def test_enabling_later_does_not_post_previously_saved_evidence(tmp_path):
    workspace, path = loan_workspace(tmp_path)
    first = workspace.import_file(path, review_import=choose_loan)
    assert first.loan_automation is None
    enable(workspace)
    retry = workspace.import_file(path, review_import=lambda *_: pytest.fail("Existing source needs no new preview"))
    assert retry.status == "already_imported" and retry.loan_automation is None
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert len(store.source_ids()) == 1 and not store.loan_history()


@pytest.mark.parametrize("stage", ["build", "record"])
@pytest.mark.parametrize("change", ["cancel", "revoke", "failure"])
def test_post_import_late_changes_roll_back_payment_and_keep_source(tmp_path, monkeypatch, stage, change):
    workspace, path = loan_workspace(tmp_path)
    enable(workspace)
    cancelled = False
    name = "_loan_build" if stage == "build" else "_loan_record"
    original = getattr(V2ProfileStore, name)

    def interrupt(store, *args, **kwargs):
        nonlocal cancelled
        result = original(store, *args, **kwargs)
        if change == "cancel":
            cancelled = True
        elif change == "revoke":
            workspace.set_auto_post_loan_payments(False)
        else:
            raise sqlite3.IntegrityError("Injected automatic posting failure")
        return result

    monkeypatch.setattr(V2ProfileStore, name, interrupt)
    result = workspace.import_file(path, review_import=choose_loan, cancelled=lambda: cancelled)
    assert result.status == "imported"
    assert result.loan_automation.status == ("cancelled" if change == "cancel" else "needs_review")
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert len(store.source_ids()) == 1 and not store.loan_history()
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)


@pytest.mark.parametrize("case", ["origination", "multiple", "warning"])
def test_nonroutine_source_requires_manual_review(tmp_path, case):
    workspace, path = loan_workspace(tmp_path)
    enable(workspace)
    source_lines = lines(
        interest=case != "origination",
        changes={5: "01/16/2026 Payment Received -$100.00 -$10.00 = -$110.00"}
        if case == "multiple"
        else {7: "Unexplained $2.00"}
        if case == "warning"
        else None,
    )
    path.write_bytes(pdf_document((text_page("Capital One Auto Finance", *(line.raw for line in source_lines.lines)),)))
    result = workspace.import_file(path, review_import=choose_loan)
    assert result.status == "imported" and result.loan_automation.status == "needs_review"
    assert (
        result.loan_automation.reason_code
        == {
            "origination": "loan_auto_origination",
            "multiple": "loan_auto_multiple_payments",
            "warning": "loan_auto_source_warning",
        }[case]
    )
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert len(store.source_ids()) == 1 and not store.loan_history()


def test_profile_switch_after_evidence_import_refuses_automatic_posting(tmp_path, monkeypatch):
    workspace, path = loan_workspace(tmp_path)
    enable(workspace)
    original_profile = workspace.profile_path
    other_profile = tmp_path / "other.db"
    with V2ProfileStore.create(other_profile):
        pass
    original = workspace._import_file_evidence

    def import_then_switch(*args, **kwargs):
        result = original(*args, **kwargs)
        workspace.profile_path = other_profile
        return result

    monkeypatch.setattr(workspace, "_import_file_evidence", import_then_switch)
    result = workspace.import_file(path, review_import=choose_loan)
    assert result.status == "imported" and result.loan_automation.reason_code == "loan_auto_changed"
    with V2ProfileStore.open(original_profile, read_only=True) as store:
        assert len(store.source_ids()) == 1 and not store.loan_history()
    with V2ProfileStore.open(other_profile, read_only=True) as store:
        assert not store.source_ids() and not store.loan_history()


def test_batch_cancel_after_saved_import_keeps_it_and_stops_remaining_files(tmp_path, monkeypatch):
    workspace, path = loan_workspace(tmp_path)
    enable(workspace)
    second = tmp_path / "second.pdf"
    second.write_bytes(path.read_bytes() + b"\n% second source\n")
    cancelled = False
    original = V2ProfileStore._loan_build

    def cancel(store, *args, **kwargs):
        nonlocal cancelled
        result = original(store, *args, **kwargs)
        cancelled = True
        return result

    monkeypatch.setattr(V2ProfileStore, "_loan_build", cancel)
    result = workspace.import_files((path, second), review_import=choose_loan, cancelled=lambda: cancelled)
    assert result.cancelled
    assert [item.status for item in result.files] == ["imported", "not_attempted"]
    assert result.files[0].loan_automation.status == "cancelled"
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert len(store.source_ids()) == 1 and not store.loan_history()
