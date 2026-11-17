"""Account-first workspace confirmation is atomic and refreshes stale proposals."""

import pytest
from parsetrail.core.v2_import_accounts import (
    ImportAccountChoice,
    compatible_import_accounts,
    import_account_profiles,
    prepare_import_accounts,
)
from parsetrail.core.v2_profile_store import FinancialAccount, V2ProfileStore
from parsetrail.core.v2_source_import import ImportCancelled
from parsetrail.core.v2_workspace import ImportSkipped

from .test_v2_workspace_recognition import workspace_with_choices as _workspace_with_choices


def workspace_with_choices(tmp_path):
    return _workspace_with_choices(tmp_path, account_routing=True)


def create_plan(review):
    profile = next(
        p for p in import_account_profiles(review, review.groups[0].group_id) if p.product_type == "checking"
    )
    account = FinancialAccount(
        "chosen-checking",
        "Everyday checking",
        profile.kind,
        "chase",
        tracking_scope=profile.tracking_scope,
        product_type=profile.product_type,
    )
    return prepare_import_accounts(
        review,
        tuple(ImportAccountChoice(group.group_id, account.id) for group in review.groups),
        "synthetic_posted_csv",
        new_accounts=(account,),
    )


def test_import_and_assign_is_one_confirmation_and_exact_retry_keeps_decisions(tmp_path):
    workspace, path, _activate = workspace_with_choices(tmp_path)
    called = []

    def choose(source_path, review):
        assert source_path == path and not review.accounts
        with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
            assert store.source_ids() == () and store.financial_accounts() == ()
        called.append(review)
        return create_plan(review)

    result = workspace.import_file(path, review_import=choose)
    assert result.status == "imported" and len(called) == 1
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        account = store.financial_accounts()[0]
        assert account.product_type == "checking" and account.kind == "asset"
        assert store.source_account_bindings(result.source_sha256)[0].ledger_account_id == account.id
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
        original = store.load_import(result.source_sha256)
    retry = workspace.import_file(path, review_import=lambda *_: pytest.fail("Exact source retry must not ask again"))
    assert retry.status == "already_imported"
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert store.load_import(result.source_sha256) == original
        assert len(store.financial_accounts()) == 1


@pytest.mark.parametrize("drift", ["account", "catalog", "source"])
def test_stale_confirmation_rebuilds_then_requires_another_explicit_decision(tmp_path, drift):
    workspace, path, activate = workspace_with_choices(tmp_path)
    seen = []

    def choose(_path, review):
        seen.append(review)
        if len(seen) == 1:
            plan = create_plan(review)
            if drift == "account":
                with V2ProfileStore.open(workspace.profile_path) as store:
                    store.add_financial_account(FinancialAccount("other", "New elsewhere", "asset", None))
            elif drift == "catalog":
                activate(2)
            else:
                path.write_bytes(path.read_bytes().replace(b"Coffee", b"Updated description"))
            return plan
        assert review.recovery_notice
        with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
            assert store.source_ids() == ()
            assert not any(a.id == "chosen-checking" for a in store.financial_accounts())
        return None  # A refreshed preview never confirms itself.

    with pytest.raises(ImportSkipped):
        workspace.import_file(path, review_import=choose)
    assert len(seen) == 2
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert store.source_ids() == ()


def test_existing_compatible_account_is_explicit_and_loan_is_not_offered(tmp_path):
    workspace, path, _activate = workspace_with_choices(tmp_path)
    with V2ProfileStore.open(workspace.profile_path) as store:
        store.add_financial_account(FinancialAccount("asset", "Checking", "asset", None, product_type="checking"))
        store.add_financial_account(FinancialAccount("loan", "Loan", "liability", None, product_type="loan"))

    def choose(_path, review):
        group = review.groups[0]
        assert group.suggested_account_id is None and not group.automatic
        assert {a.id for a in compatible_import_accounts(review, group.group_id)} == {"asset"}
        return prepare_import_accounts(review, (ImportAccountChoice(group.group_id, "asset"),), "synthetic_posted_csv")

    result = workspace.import_file(path, review_import=choose)
    assert result.status == "imported"
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert len(store.financial_accounts()) == 2
        assert store.source_account_bindings(result.source_sha256)[0].ledger_account_id == "asset"


def test_cancellation_after_draft_confirmation_leaves_no_new_state(tmp_path):
    workspace, path, _activate = workspace_with_choices(tmp_path)
    cancel = False

    def choose(_path, review):
        nonlocal cancel
        plan = create_plan(review)
        cancel = True
        return plan

    with pytest.raises(ImportCancelled):
        workspace.import_file(path, review_import=choose, cancelled=lambda: cancel)
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert store.source_ids() == () and store.financial_accounts() == ()


@pytest.mark.parametrize("drift", ["source", "catalog"])
def test_changes_during_selected_evidence_validation_require_fresh_confirmation(tmp_path, monkeypatch, drift):
    from parsetrail.core.v2_prepared_import import PreparedImportSession

    workspace, path, activate = workspace_with_choices(tmp_path)
    original = PreparedImportSession.select
    changed = False
    reviews = []

    def select(*args, **kwargs):
        nonlocal changed
        original(*args, **kwargs)
        if not changed:
            changed = True
            if drift == "source":
                path.write_bytes(path.read_bytes().replace(b"Coffee", b"Changed during validation"))
            else:
                activate(2)

    monkeypatch.setattr(PreparedImportSession, "select", select)

    def choose(_path, review):
        reviews.append(review)
        if len(reviews) == 1:
            return create_plan(review)
        assert "while" in review.recovery_notice
        return None

    with pytest.raises(ImportSkipped):
        workspace.import_file(path, review_import=choose)
    assert len(reviews) == 2
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert store.source_ids() == () and store.financial_accounts() == ()


@pytest.mark.parametrize("drift", ["source", "catalog"])
def test_changes_before_atomic_apply_require_fresh_confirmation(tmp_path, monkeypatch, drift):
    from parsetrail.core import v2_workspace as module

    workspace, path, activate = workspace_with_choices(tmp_path)
    original = module.commit_import_accounts
    reviews = []
    changed = False

    def commit(*args, **kwargs):
        nonlocal changed
        if not changed:
            changed = True
            if drift == "source":
                path.write_bytes(path.read_bytes().replace(b"Coffee", b"Changed during route validation"))
            else:
                activate(2)
        return original(*args, **kwargs)

    monkeypatch.setattr(module, "commit_import_accounts", commit)

    def choose(_path, review):
        reviews.append(review)
        if len(reviews) == 1:
            return create_plan(review)
        assert "while" in review.recovery_notice
        return None

    with pytest.raises(ImportSkipped):
        workspace.import_file(path, review_import=choose)
    assert len(reviews) == 2
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert store.source_ids() == () and store.financial_accounts() == ()
