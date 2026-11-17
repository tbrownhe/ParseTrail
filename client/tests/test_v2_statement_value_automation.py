"""Standing statement-value consent records exact new evidence without journals."""

import json
import sqlite3
from datetime import date
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from parsetrail.core import v2_source_pipeline as pipeline
from parsetrail.core.v2_data_catalog import key_id_for_public_key
from parsetrail.core.v2_import_accounts import ImportAccountChoice, prepare_import_accounts
from parsetrail.core.v2_preferences import V2Preferences, load_preferences, save_preferences
from parsetrail.core.v2_profile_store import FinancialAccount, V2ProfileStore
from parsetrail.core.v2_statement_value_automation import AUTOMATIC_REASON, record_imported_statement_value
from parsetrail.core.v2_workspace import V2Workspace
from scripts.v2_catalog_release import signed_catalog_bytes

from devtools.parser_engine_pilot import test_plan_label_summary as fidelity
from devtools.parser_engine_pilot.synthetic_family_sources import family_sources, pdf_document, text_page


def statement_account():
    return FinancialAccount("retirement", "My retirement", "asset", "fidelity", product_type="investment")


def statement_workspace(tmp_path, *, existing_account=True):
    tmp_path.mkdir(parents=True, exist_ok=True)
    pilot = Path(__file__).resolve().parents[2] / "devtools/parser_engine_pilot"
    name = "fidelity-401k-summary-pilot-definition.json"
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
            store.add_financial_account(statement_account())
    path = tmp_path / "statement.pdf"
    path.write_bytes(case.source)
    return workspace, path


def choose_summary(_path, review):
    new_accounts = () if any(account.id == "retirement" for account in review.accounts) else (statement_account(),)
    return prepare_import_accounts(
        review,
        tuple(ImportAccountChoice(group.group_id, "retirement") for group in review.groups),
        "pdf_fidelity401k_201810",
        new_accounts=new_accounts,
    )


def _manual(store, amount, day=date(2026, 1, 31)):
    frame = store.account_anchor_snapshot("retirement")
    return store.record_reviewed_dated_value(
        "retirement",
        amount_minor=amount,
        value_date=day,
        tracking_scope="account_total",
        reference="Independent value",
        reason="Independent review",
        expected_basis_sha256=frame.basis_sha256,
    )


def _assert_only_value(store, source, expected_count):
    assert len(store.source_ids()) == 1
    assert store.connection.execute("SELECT count(*) FROM AccountDatedValues").fetchone() == (expected_count,)
    assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
    assert not store._active_consumed()
    assert store.load_import(source).evidence.parser_id == "pdf_fidelity401k_201810"


def test_preference_default_old_file_strict_validation_and_preservation(tmp_path):
    path = tmp_path / "prefs.json"
    assert not load_preferences(path).auto_record_statement_values
    path.write_text('{"allow_abbreviated_account_matching":false,"auto_post_loan_payments":true}')
    assert not load_preferences(path).auto_record_statement_values and load_preferences(path).auto_post_loan_payments
    for bad in (1, "true", None):
        path.write_text(json.dumps({"allow_abbreviated_account_matching": False, "auto_record_statement_values": bad}))
        with pytest.raises(ValueError, match="v2_preferences_shape"):
            load_preferences(path)
        with pytest.raises(ValueError, match="v2_preferences_shape"):
            save_preferences(path, V2Preferences(auto_record_statement_values=bad))
    workspace, _ = statement_workspace(tmp_path / "workspace")
    workspace.set_auto_record_statement_values(True)
    workspace.set_allow_abbreviated_account_matching(True)
    workspace.set_allow_assumed_posting_dates(True)
    workspace.set_import_preview_mode("when_needed")
    workspace.set_auto_post_loan_payments(True)
    assert workspace.preferences() == V2Preferences(True, True, "when_needed", True, True)
    for bad in (1, "true", None):
        with pytest.raises(ValueError, match="invalid_statement_value_automation_preference"):
            workspace.set_auto_record_statement_values(bad)


@pytest.mark.parametrize("existing_account", [True, False])
def test_opt_in_records_exact_value_with_new_or_established_explicit_account(tmp_path, existing_account):
    workspace, path = statement_workspace(tmp_path, existing_account=existing_account)
    workspace.set_auto_record_statement_values(True)
    result = workspace.import_file(path, review_import=choose_summary)
    assert result.status == "imported" and result.loan_automation is None
    assert result.statement_value_automation.status == "recorded"
    assert (result.statement_value_automation.amount_minor, result.statement_value_automation.value_date) == (
        14000,
        date(2026, 1, 31),
    )
    assert not workspace.preferences().allow_assumed_posting_dates
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        section = store.statement_summary_snapshot(result.source_sha256).sections[0]
        assert section.status == "reviewed" and section.active_value.reason == AUTOMATIC_REASON
        assert result.statement_value_automation.value_id == section.active_value.value_id
        assert section.active_value.source_proof.closing == result.evidence.payload.accounts[0].closing
        _assert_only_value(store, result.source_sha256, 1)


@pytest.mark.parametrize("case", ["off", "enable_during_review", "revoke", "unbound"])
def test_manual_fallback_and_future_import_only_consent(tmp_path, case):
    workspace, path = statement_workspace(tmp_path)
    if case not in {"off", "enable_during_review"}:
        workspace.set_auto_record_statement_values(True)

    def choose(source, review):
        if case == "enable_during_review":
            workspace.set_auto_record_statement_values(True)
        if case == "revoke":
            workspace.set_auto_record_statement_values(False)
        return choose_summary(source, review)

    result = workspace.import_file(path, review_import=None if case == "unbound" else choose)
    assert result.status == "imported"
    if case in {"off", "enable_during_review"}:
        assert result.statement_value_automation is None
    else:
        assert result.statement_value_automation.status == "needs_review"
        assert result.statement_value_automation.reason_code == (
            "statement_value_auto_changed" if case == "revoke" else "statement_value_auto_account_required"
        )
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        _assert_only_value(store, result.source_sha256, 0)


@pytest.mark.parametrize("prior", [14000, 15000])
def test_agreeing_manual_point_allowed_but_conflict_is_manual(tmp_path, prior):
    workspace, path = statement_workspace(tmp_path)
    workspace.set_auto_record_statement_values(True)
    with V2ProfileStore.open(workspace.profile_path) as store:
        _manual(store, prior)
    result = workspace.import_file(path, review_import=choose_summary)
    assert result.status == "imported"
    assert result.statement_value_automation.status == ("recorded" if prior == 14000 else "needs_review")
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        _assert_only_value(store, result.source_sha256, 2 if prior == 14000 else 1)
        summary = store.statement_summary_snapshot(result.source_sha256)
        assert summary.complete == (prior == 14000)


def test_saved_retry_after_enabling_or_withdrawal_never_records_again(tmp_path):
    workspace, path = statement_workspace(tmp_path)
    imported = workspace.import_file(path, review_import=choose_summary)
    workspace.set_auto_record_statement_values(True)
    retry = workspace.import_file(path, review_import=lambda *_: pytest.fail("Saved source needs no preview"))
    assert retry.status == "already_imported" and retry.statement_value_automation is None
    with V2ProfileStore.open(workspace.profile_path) as store:
        snapshot = store.statement_summary_snapshot(imported.source_sha256)
        section = snapshot.sections[0]
        value = store.record_reviewed_source_value(
            section.account_id,
            section.candidate.candidate_id,
            expected_candidate_sha256=section.candidate.version,
            expected_basis_sha256=section.basis_sha256,
            reference="Inspected",
            reason="Initial Review",
        )
        store.withdraw_reviewed_dated_value(
            section.account_id,
            value.value_id,
            expected_value_version=value.version,
            expected_basis_sha256=store.account_anchor_snapshot(section.account_id).basis_sha256,
            reason="Withdraw unsupported value",
        )
    assert workspace.import_file(path).statement_value_automation is None
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert not store.statement_summary_snapshot(imported.source_sha256).complete
        _assert_only_value(store, imported.source_sha256, 1)


def test_material_extractor_warning_keeps_successful_import_for_manual_review(tmp_path, monkeypatch):
    workspace, path = statement_workspace(tmp_path)
    workspace.set_auto_record_statement_values(True)
    lines = fidelity.lines(changes={5: "Your Contributions $50.00 $500.00"})
    path.write_bytes(pdf_document((text_page("Fidelity Brokerage Services", *(line.raw for line in lines.lines)),)))
    parse = pipeline.parse_plan_label_summary

    def material_diagnostic(*args, **kwargs):
        evidence = parse(*args, **kwargs)
        # Exercise a material diagnostic through the real warning projector;
        # the current parser's retained extra-column code is not a defect warning.
        dispositions = tuple(
            disposition.model_copy(update={"code": "unclassified_monetary_line"})
            if disposition.code == "summary_extra_column"
            else disposition
            for disposition in evidence.payload.dispositions
        )
        return evidence.model_copy(
            update={"payload": evidence.payload.model_copy(update={"dispositions": dispositions})}
        )

    monkeypatch.setattr(pipeline, "parse_plan_label_summary", material_diagnostic)
    result = workspace.import_file(path, review_import=choose_summary)
    assert result.status == "imported" and result.statement_value_automation.status == "needs_review"
    assert result.statement_value_automation.reason_code == "statement_value_auto_source_warning"
    assert result.evidence.payload.independent_balance_verified
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        _assert_only_value(store, result.source_sha256, 0)


@pytest.mark.parametrize("withdrawn", [False, True])
def test_history_created_after_snapshot_cannot_use_historical_retry_or_duplicate(tmp_path, monkeypatch, withdrawn):
    workspace, path = statement_workspace(tmp_path)
    workspace.set_auto_record_statement_values(True)
    original = V2ProfileStore.record_reviewed_source_value

    def add_racing_history(store, account_id, candidate_id, **kwargs):
        manual_kwargs = {key: value for key, value in kwargs.items() if key not in {"before_write", "before_commit"}}
        existing = original(store, account_id, candidate_id, **manual_kwargs)
        if withdrawn:
            store.withdraw_reviewed_dated_value(
                account_id,
                existing.value_id,
                expected_value_version=existing.version,
                expected_basis_sha256=store.account_anchor_snapshot(account_id).basis_sha256,
                reason="Withdraw concurrent value review",
            )
        return original(store, account_id, candidate_id, **kwargs)

    monkeypatch.setattr(V2ProfileStore, "record_reviewed_source_value", add_racing_history)
    result = workspace.import_file(path, review_import=choose_summary)
    assert result.status == "imported" and result.statement_value_automation.status == "needs_review"
    assert result.statement_value_automation.reason_code == "statement_value_auto_prior_review"
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        _assert_only_value(store, result.source_sha256, 1)
        assert store.statement_summary_snapshot(result.source_sha256).complete == (not withdrawn)


@pytest.mark.parametrize("stage", ["begin", "append"])
@pytest.mark.parametrize("change", ["cancel", "revoke", "failure"])
def test_late_cancel_revoke_failure_roll_back_value_but_keep_import(tmp_path, monkeypatch, stage, change):
    workspace, path = statement_workspace(tmp_path)
    workspace.set_auto_record_statement_values(True)
    cancelled = False
    name = "_anchor_write_start" if stage == "begin" else "_append_dated_value"
    original = getattr(V2ProfileStore, name)

    def interrupt(store, *args, **kwargs):
        nonlocal cancelled
        result = original(store, *args, **kwargs)
        if change == "cancel":
            cancelled = True
        elif change == "revoke":
            workspace.set_auto_record_statement_values(False)
        else:
            raise sqlite3.IntegrityError("Injected statement-value write failure")
        return result

    monkeypatch.setattr(V2ProfileStore, name, interrupt)
    result = workspace.import_file(path, review_import=choose_summary, cancelled=lambda: cancelled)
    assert result.status == "imported"
    assert result.statement_value_automation.status == ("cancelled" if change == "cancel" else "needs_review")
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        _assert_only_value(store, result.source_sha256, 0)


def test_batch_cancel_keeps_saved_import_and_stops_remaining_sources(tmp_path, monkeypatch):
    workspace, path = statement_workspace(tmp_path)
    workspace.set_auto_record_statement_values(True)
    second = tmp_path / "second.pdf"
    second.write_bytes(path.read_bytes() + b"\n% another source\n")
    cancelled = False
    original = V2ProfileStore._append_dated_value

    def interrupt(store, *args, **kwargs):
        nonlocal cancelled
        result = original(store, *args, **kwargs)
        cancelled = True
        return result

    monkeypatch.setattr(V2ProfileStore, "_append_dated_value", interrupt)
    result = workspace.import_files((path, second), review_import=choose_summary, cancelled=lambda: cancelled)
    assert result.cancelled and [item.status for item in result.files] == ["imported", "not_attempted"]
    assert result.files[0].statement_value_automation.status == "cancelled"


def test_direct_helper_requires_strict_opt_in_and_refuses_prior_source_history(tmp_path):
    from parsetrail.core.v2_import_accounts import _profile_identity

    workspace, path = statement_workspace(tmp_path)
    result = workspace.import_file(path, review_import=choose_summary)
    with V2ProfileStore.open(workspace.profile_path) as store:
        for bad in (False, 1, "true"):
            with pytest.raises(ValueError, match="statement_value_auto_consent_required"):
                record_imported_statement_value(
                    store,
                    result.source_sha256,
                    preferences=V2Preferences(auto_record_statement_values=bad),
                    expected_profile=_profile_identity(store),
                    authorize=lambda: None,
                )
        value = record_imported_statement_value(
            store,
            result.source_sha256,
            preferences=V2Preferences(auto_record_statement_values=True),
            expected_profile=_profile_identity(store),
            authorize=lambda: None,
        )
        assert value.status == "recorded"
        with pytest.raises(ValueError, match="statement_value_auto_prior_review"):
            record_imported_statement_value(
                store,
                result.source_sha256,
                preferences=V2Preferences(auto_record_statement_values=True),
                expected_profile=_profile_identity(store),
                authorize=lambda: None,
            )
