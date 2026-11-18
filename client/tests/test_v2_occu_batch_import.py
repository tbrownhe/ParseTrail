"""A first-use OCCU batch keeps its independent savings/checking accounts."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from parsetrail.core.v2_data_catalog import key_id_for_public_key
from parsetrail.core.v2_import_accounts import ImportAccountChoice, prepare_import_accounts
from parsetrail.core.v2_profile_store import FinancialAccount, ProfileFormatError, V2ProfileStore
from parsetrail.core.v2_workspace import V2Workspace
from scripts.v2_catalog_release import signed_catalog_bytes

from devtools.parser_engine_pilot.synthetic_family_sources import family_sources, pdf_document, text_page


def occu_workspace(tmp_path, *, inactive_savings=False, count=2, active_savings_indexes=()):
    pilot = Path(__file__).resolve().parents[2] / "devtools/parser_engine_pilot"
    name = "occu-bank-pilot-definition.json"
    case = next(item for item in family_sources() if item.definition_name == name)
    definitions = tmp_path / "definitions"
    definitions.mkdir()
    (definitions / name).write_bytes((pilot / name).read_bytes())
    contexts = json.loads((pilot / "account-contexts.json").read_bytes())
    (definitions / "account-contexts.json").write_text(
        json.dumps({"pdf_occubank_201409": contexts["pdf_occubank_201409"]})
    )
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    snapshot, signature, _ = signed_catalog_bytes(definitions, private, release_sequence=1, source_revision="a" * 40)
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
    paths = tuple(tmp_path / f"statement-{index}.pdf" for index in range(count))
    source = case.source
    if inactive_savings:
        source = pdf_document(
            (
                text_page(
                    "Oregon Community Credit Union MemberNumber",
                    "FROM 01/01/26",
                    "TO 01/31/26",
                    "XXXXXX1234 - PRIMARY SAVINGS .",
                    "Previous Balance.................... $100.00",
                    "Ending Balance...................... $100.00",
                    "XXXXXX5678 - REMARKABLE CHECKING .",
                    "Previous Balance.................... $200.00",
                    "Ending Balance...................... $195.00",
                    "01/10 # Payment ($5.00) $195.00",
                ),
            )
        )
    for index, path in enumerate(paths):
        current = case.source if index in active_savings_indexes else source
        path.write_bytes(current + f"\n% distinct public synthetic export {index}\n".encode())
    return workspace, paths


def choose_occu(_path, review):
    targets = {
        "1234": FinancialAccount("occu-savings", "Primary savings", "asset", "occu", product_type="savings"),
        "5678": FinancialAccount("occu-checking", "Remarkable checking", "asset", "occu", product_type="checking"),
    }
    existing = {account.id for account in review.accounts}
    return prepare_import_accounts(
        review,
        tuple(ImportAccountChoice(group.group_id, targets[group.source_identity].id) for group in review.groups),
        "pdf_occubank_201409",
        new_accounts=tuple(account for account in targets.values() if account.id not in existing),
    )


@pytest.mark.parametrize("automatic", [False, True])
@pytest.mark.parametrize("inactive_savings", [False, True])
def test_two_file_first_use_batch_creates_two_accounts_and_reuses_both(tmp_path, automatic, inactive_savings):
    count = 6 if inactive_savings else 2
    workspace, paths = occu_workspace(
        tmp_path, inactive_savings=inactive_savings, count=count, active_savings_indexes=(2,)
    )
    seen = []

    def choose(path, review):
        seen.append(review)
        plan = choose_occu(path, review)
        if automatic:
            workspace.set_allow_abbreviated_account_matching(True)
            workspace.set_import_preview_mode("when_needed")
        return plan

    result = workspace.import_files(paths, review_import=choose)
    assert [(item.status, item.error_code) for item in result.files] == [("imported", None)] * count
    assert len(seen) == (1 if automatic else count) and len(seen[0].accounts) == 0
    if not automatic:
        assert len(seen[1].accounts) == 2
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert {account.id: account.product_type for account in store.financial_accounts()} == {
            "occu-savings": "savings",
            "occu-checking": "checking",
        }
        for item in result.files:
            assert {
                binding.source_identity: binding.ledger_account_id
                for binding in store.source_account_bindings(item.source_sha256)
            } == {"1234": "occu-savings", "5678": "occu-checking"}
        for account in store.financial_accounts():
            lock = store.account_identity_lock(account.id)
            assert lock.source_sha256 == result.files[0].source_sha256
            assert lock.institution_key == "occu" and lock.product_type == account.product_type
            assert account.full_account_number is None
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
    retry = workspace.import_files(paths, review_import=lambda *_args: pytest.fail("Exact retry needs no review"))
    assert [item.status for item in retry.files] == ["already_imported"] * count


def test_zero_activity_section_origin_rejects_unrelated_account(tmp_path):
    workspace, paths = occu_workspace(tmp_path, inactive_savings=True)
    result = workspace.import_files(paths[:1], review_import=choose_occu)
    assert result.files[0].status == "imported"
    source = result.files[0].source_sha256
    with V2ProfileStore.open(workspace.profile_path) as store:
        store.add_financial_account(FinancialAccount("unrelated", "Unrelated", "asset", "occu", product_type="savings"))
        with pytest.raises(ProfileFormatError, match="account_identity_origin_requires_bound_pdf"):
            store.lock_pdf_import_account("unrelated", source)
        # A raw assignment to a nonexistent PDF section cannot create provenance.
        store.connection.execute("SAVEPOINT nonexistent_section")
        try:
            store.connection.execute(
                "INSERT INTO SourceAccountBindings VALUES (?,?,?,?)", (source, "9999", "last_four", "unrelated")
            )
            with pytest.raises(ProfileFormatError, match="account_identity_origin_requires_bound_pdf"):
                store.lock_pdf_import_account("unrelated", source)
        finally:
            store.connection.execute("ROLLBACK TO nonexistent_section")
            store.connection.execute("RELEASE nonexistent_section")
        account = next(account for account in store.financial_accounts() if account.id == "occu-savings")
        with pytest.raises(ProfileFormatError, match="identity_locked"):
            store.update_financial_account(replace(account, product_type="checking"))
        assert store.account_identity_lock("unrelated") is None


def test_pdf_origin_lock_rejects_a_bound_csv(tmp_path):
    from parsetrail.core.v2_import_accounts import commit_import_accounts

    from .test_v2_import_accounts import proposal

    with V2ProfileStore.create(tmp_path / "csv.db") as store:
        catalog, _review, plan, prepared = proposal(store)
        imported = commit_import_accounts(store, prepared, catalog, plan)
        assert store.account_bindings(imported.source_sha256)
        with pytest.raises(ProfileFormatError, match="account_identity_origin_requires_bound_pdf"):
            store.lock_pdf_import_account(plan.new_accounts[0].id, imported.source_sha256)
        assert store.account_identity_lock(plan.new_accounts[0].id) is None


def test_cancelling_after_first_origin_lock_rolls_back_all_accounts_and_source_then_retries(tmp_path, monkeypatch):
    workspace, paths = occu_workspace(tmp_path, inactive_savings=True)
    cancelled = False
    original_lock = V2ProfileStore.lock_pdf_import_account

    def lock_then_cancel(store, account, source):
        nonlocal cancelled
        lock = original_lock(store, account, source)
        cancelled = True
        return lock

    with monkeypatch.context() as patch:
        patch.setattr(V2ProfileStore, "lock_pdf_import_account", lock_then_cancel)
        result = workspace.import_files(paths, review_import=choose_occu, cancelled=lambda: cancelled)
    assert [item.status for item in result.files] == ["cancelled", "not_attempted"]
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert store.financial_accounts() == () and store.source_ids() == ()
        assert store.connection.execute("SELECT count(*) FROM AccountImportOrigins").fetchone() == (0,)
        assert store.connection.execute("SELECT count(*) FROM SourceAccountBindings").fetchone() == (0,)
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
    retry = workspace.import_files(paths, review_import=choose_occu)
    assert [item.status for item in retry.files] == ["imported", "imported"]
