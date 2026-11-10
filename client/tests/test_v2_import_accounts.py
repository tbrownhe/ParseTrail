"""Account-first imports preserve source evidence and commit no financial entries."""

import json
from dataclasses import replace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from parsetrail.core.v2_account_products import AccountProductProfile
from parsetrail.core.v2_catalog_admission import admit_pilot_definition
from parsetrail.core.v2_data_catalog import key_id_for_public_key, verify_catalog
from parsetrail.core.v2_format_recognition import recognize_catalog_source
from parsetrail.core.v2_import_accounts import (
    ImportAccountChoice,
    build_import_account_review,
    commit_import_accounts,
    compatible_import_accounts,
    import_account_creation_draft,
    import_account_profiles,
    matching_import_candidates,
    prepare_import_accounts,
    resolve_import_candidate,
)
from parsetrail.core.v2_preferences import V2Preferences
from parsetrail.core.v2_profile_store import SCHEMA_VERSION, FinancialAccount, ProfileFormatError, V2ProfileStore
from parsetrail.core.v2_source_import import ImportCancelled, prepare_catalog_source
from parsetrail.core.v2_source_pipeline import build_source_evidence
from scripts.v2_catalog_release import signed_catalog_bytes

from .test_v2_catalog_import import DEFINITION, SOURCE, _verified_catalog


def account(account_id="new-checking", *, kind="asset", product="checking", scope="account_total"):
    return FinancialAccount(account_id, "Everyday checking", kind, "chase", None, scope, product)


def proposal(store, source=SOURCE, *, new_account=None, catalog=None, parse=build_source_evidence):
    catalog = catalog or _verified_catalog()
    recognition = recognize_catalog_source(source, catalog=catalog, suffix=".csv", parse=parse)
    review = build_import_account_review(store, recognition, catalog)
    created = new_account or account()
    choices = tuple(ImportAccountChoice(group.group_id, created.id) for group in review.groups)
    plan = prepare_import_accounts(review, choices, recognition.candidates[0].parser_id, (created,))
    prepared = prepare_catalog_source(source, catalog=catalog, suffix=".csv", selection=plan.selection, parse=parse)
    return catalog, review, plan, prepared


def assert_unwritten(store):
    assert store.source_ids() == ()
    assert store.financial_accounts() == ()
    for table in (
        "SourceAccountBindings",
        "FileAccountAssertions",
        "RowAccountAssignments",
        "JournalEntries",
        "OpeningDecisions",
    ):
        assert store.connection.execute(f"SELECT count(*) FROM {table}").fetchone() == (0,)


def routing_catalog(tmp_path, *, profiles=None, other_account=False):
    definitions = tmp_path / "routing-definitions"
    definitions.mkdir()
    first = json.loads(DEFINITION.read_bytes())
    other = json.loads(DEFINITION.read_bytes())
    other["parser_id"] = "synthetic_other_csv"
    if other_account:
        first["header"].append("OtherAccount")
        other["header"].append("OtherAccount")
        other["columns"]["account"] = "OtherAccount"
    else:
        other["columns"]["total"], other["columns"]["balance"] = (
            other["columns"]["balance"],
            other["columns"]["total"],
        )
    for item in (first, other):
        (definitions / (item["parser_id"] + "-definition.json")).write_text(json.dumps(item))
    if profiles is not None:
        (definitions / "account-profiles.json").write_text(json.dumps(profiles))
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    snapshot, signature, _ = signed_catalog_bytes(definitions, private, release_sequence=1, source_revision="a" * 40)
    return verify_catalog(snapshot, signature, {key_id_for_public_key(public): public}, admit_pilot_definition)


def test_overlapping_declared_semantics_cannot_be_resolved_by_parser_choice(tmp_path):
    catalog = routing_catalog(tmp_path)
    recognition = recognize_catalog_source(SOURCE, catalog=catalog, suffix=".csv")
    with V2ProfileStore.create(tmp_path / "overlap.db") as store:
        review = build_import_account_review(store, recognition, catalog)
        choices = tuple(ImportAccountChoice(group.group_id, account().id) for group in review.groups)
        assert len(matching_import_candidates(review, choices, (account(),))) == 2
        with pytest.raises(ProfileFormatError, match="import_account_routing_conflict"):
            resolve_import_candidate(review, choices, (account(),))
        for candidate in recognition.candidates:
            with pytest.raises(ProfileFormatError, match="import_account_routing_conflict"):
                prepare_import_accounts(review, choices, candidate.parser_id, (account(),))
        assert_unwritten(store)


@pytest.mark.parametrize("narrow_by", ["institution", "product"])
def test_account_metadata_resolves_headers_to_one_declared_format_without_column_input(tmp_path, narrow_by):
    profiles = {
        "synthetic_posted_cash_csv": [
            {"institution_key": "chase", "product_type": "checking", "tracking_scope": "account_total"}
        ],
        "synthetic_other_csv": [
            {
                "institution_key": "citi" if narrow_by == "institution" else "chase",
                "product_type": "checking" if narrow_by == "institution" else "savings",
                "tracking_scope": "account_total",
            }
        ],
    }
    catalog = routing_catalog(tmp_path, profiles=profiles)
    recognition = recognize_catalog_source(SOURCE, catalog=catalog, suffix=".csv")
    assert len(recognition.candidates) == 2
    assert all(candidate.institution_key is None for candidate in recognition.candidates)
    with V2ProfileStore.create(tmp_path / "narrowed.db") as store:
        review = build_import_account_review(store, recognition, catalog)
        choices = tuple(ImportAccountChoice(group.group_id, account().id) for group in review.groups)
        candidate = resolve_import_candidate(review, choices, (account(),))
        assert candidate.parser_id == "synthetic_posted_cash_csv"
        plan = prepare_import_accounts(review, choices, candidate.parser_id, (account(),))
        prepared = prepare_catalog_source(SOURCE, catalog=catalog, suffix=".csv", selection=plan.selection)
        result = commit_import_accounts(store, prepared, catalog, plan)
        assert result.evidence.payload.rows[0].amount.minor == 120000
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)


@pytest.mark.parametrize("other_account", [False, True])
def test_commit_rechecks_complete_catalog_against_caller_trimmed_review(tmp_path, other_account):
    catalog = routing_catalog(tmp_path, other_account=other_account)
    source = SOURCE
    if other_account:
        lines = SOURCE.splitlines()
        source = b"\n".join((lines[0] + b",OtherAccount", lines[1] + b",Other A", lines[2] + b",Other B")) + b"\n"
    recognition = recognize_catalog_source(source, catalog=catalog, suffix=".csv")
    selected = next(c for c in recognition.candidates if c.parser_id == "synthetic_posted_cash_csv")
    with V2ProfileStore.create(tmp_path / "trimmed.db") as store:
        trimmed = replace(recognition, candidates=(selected,))
        review = build_import_account_review(store, trimmed, catalog)
        choices = tuple(ImportAccountChoice(group.group_id, account().id) for group in review.groups)
        plan = prepare_import_accounts(review, choices, selected.parser_id, (account(),))
        prepared = prepare_catalog_source(source, catalog=catalog, suffix=".csv", selection=plan.selection)
        with pytest.raises(ProfileFormatError, match="import_account_routing_conflict"):
            commit_import_accounts(store, prepared, catalog, plan)
        assert_unwritten(store)


def test_final_parse_freshness_callback_runs_without_write_lock_and_can_refuse(tmp_path):
    with V2ProfileStore.create(tmp_path / "freshness.db") as store:
        catalog, _review, plan, prepared = proposal(store)

        def changed():
            assert not store.connection.in_transaction
            raise ValueError("synthetic source changed during final validation")

        with pytest.raises(ValueError, match="source changed"):
            commit_import_accounts(store, prepared, catalog, plan, before_write=changed)
        assert_unwritten(store)


def test_cancellation_during_final_full_catalog_validation_keeps_import_atomic(tmp_path):
    with V2ProfileStore.create(tmp_path / "cancel-final.db") as store:
        catalog, _review, plan, prepared = proposal(store)
        stopped = False

        def parse(source, definition, *, suffix, cancelled=None):
            nonlocal stopped
            evidence = build_source_evidence(source, definition, suffix=suffix, cancelled=cancelled)
            stopped = True
            return evidence

        with pytest.raises(ImportCancelled):
            commit_import_accounts(store, prepared, catalog, plan, lambda: stopped, parse=parse)
        assert_unwritten(store)


@pytest.mark.parametrize("changed_at", ["after_parse", "transaction"])
def test_profile_identity_is_rechecked_after_final_parse_and_before_saved_retry(tmp_path, monkeypatch, changed_at):
    from parsetrail.core import v2_import_accounts as module

    with V2ProfileStore.create(tmp_path / "identity.db") as store:
        catalog, _review, plan, prepared = proposal(store)
        parsed = False
        identity_calls = []

        def parse(source, definition, *, suffix, cancelled=None):
            nonlocal parsed
            evidence = build_source_evidence(source, definition, suffix=suffix, cancelled=cancelled)
            parsed = True
            return evidence

        def identity(_store):
            identity_calls.append((parsed, store.connection.in_transaction))
            changed = parsed and (changed_at == "after_parse" or store.connection.in_transaction)
            return "replaced-profile" if changed else plan.profile_sha256

        def saved_retry_must_not_run(*_args):
            pytest.fail("A changed profile reached saved-source retry")

        monkeypatch.setattr(module, "_profile_identity", identity)
        monkeypatch.setattr(store, "source_imported", saved_retry_must_not_run)
        with pytest.raises(ProfileFormatError, match="import_account_profile_changed"):
            commit_import_accounts(store, prepared, catalog, plan, parse=parse)
        assert identity_calls == (
            [(False, False), (True, False)]
            if changed_at == "after_parse"
            else [(False, False), (True, False), (True, True)]
        )
        assert not store.connection.in_transaction
        assert_unwritten(store)


def test_product_round_trip_unknown_and_backup_validation(tmp_path):
    path = tmp_path / "products.db"
    with V2ProfileStore.create(path) as store:
        store.ensure_builtin_category("builtin:loan-interest")
        store.add_financial_account(account())
        store.add_financial_account(account("unknown", product=None))
        assert store.category_accounts()[0].id == "builtin:loan-interest"
        assert store.connection.execute("PRAGMA user_version").fetchone() == (SCHEMA_VERSION,)
    with V2ProfileStore.open(path) as store:
        assert {a.id: a.product_type for a in store.financial_accounts()} == {
            "new-checking": "checking",
            "unknown": None,
        }
        # Older editor callers do not silently erase newly populated metadata.
        store.update_financial_account(replace(account(), product_type=None, name="Renamed"))
        assert next(a for a in store.financial_accounts() if a.id == "new-checking").product_type == "checking"
    V2ProfileStore.snapshot_to(path, tmp_path / "backup.db")
    with V2ProfileStore.open(tmp_path / "backup.db", read_only=True) as store:
        assert next(a for a in store.financial_accounts() if a.id == "new-checking").product_type == "checking"


@pytest.mark.parametrize(
    "changes", [{"product_type": "loan"}, {"tracking_scope": "principal_component"}, {"product_type": "not-a-product"}]
)
def test_product_kind_and_scope_disagreement_refuses_without_account(tmp_path, changes):
    with V2ProfileStore.create(tmp_path / "invalid.db") as store:
        with pytest.raises(ProfileFormatError, match="account_product"):
            store.add_financial_account(replace(account(), **changes))
        assert_unwritten(store)


def test_account_first_proposals_are_read_only_and_atomic_apply_retains_original(tmp_path):
    path = tmp_path / "import.db"
    with V2ProfileStore.create(path) as store:
        before = path.read_bytes()
        catalog, review, plan, prepared = proposal(store)
        assert path.read_bytes() == before and not store.connection.in_transaction
        assert not review.groups[0].automatic and review.groups[0].suggested_account_id is None
        assert {profile.product_type for profile in import_account_profiles(review, review.groups[0].group_id)} == {
            "checking",
            "savings",
            "cash",
        }
        profile = AccountProductProfile(None, "checking", "account_total")
        draft = import_account_creation_draft(review, review.groups[0].group_id, profile)
        assert (draft.kind, draft.product_type, draft.tracking_scope) == ("asset", "checking", "account_total")
        assert not draft.verified_context and draft.institution_key is None
        result = commit_import_accounts(store, prepared, catalog, plan)
        assert result.status == "imported"
        assert store.financial_accounts() == (account(),)
        assert {binding.ledger_account_id for binding in store.account_bindings(result.source_sha256)} == {account().id}
        saved = store.load_import(result.source_sha256)
        assert (
            saved.source == SOURCE and saved.evidence == prepared.evidence and saved.definition == prepared.definition
        )
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
        assert store.connection.execute("SELECT count(*) FROM OpeningDecisions").fetchone() == (0,)
        # Retrying the old confirmed request neither recreates accounts nor reassigns evidence.
        assert commit_import_accounts(store, prepared, catalog, plan).status == "already_imported"
        assert store.financial_accounts() == (account(),)


def test_incompatible_loan_excluded_but_unknown_product_preserved(tmp_path):
    with V2ProfileStore.create(tmp_path / "compatible.db") as store:
        unknown = account("unknown", product=None)
        loan = account("loan", kind="liability", product="loan", scope="principal_component")
        store.add_financial_account(unknown)
        store.add_financial_account(loan)
        catalog = _verified_catalog()
        recognition = recognize_catalog_source(SOURCE, catalog=catalog, suffix=".csv")
        review = build_import_account_review(store, recognition, catalog)
        group = review.groups[0]
        assert compatible_import_accounts(review, group.group_id) == (unknown,)
        assert not matching_import_candidates(review, (ImportAccountChoice(group.group_id, loan.id),))
        choices = (ImportAccountChoice(group.group_id, unknown.id),)
        plan = prepare_import_accounts(review, choices, recognition.candidates[0].parser_id)
        prepared = prepare_catalog_source(SOURCE, catalog=catalog, suffix=".csv", selection=plan.selection)
        commit_import_accounts(store, prepared, catalog, plan)
        assert next(a for a in store.financial_accounts() if a.id == unknown.id).product_type is None


@pytest.mark.parametrize("failure", ["cancel", "binding"])
def test_mid_apply_failure_rolls_back_new_account_source_and_assignment(tmp_path, monkeypatch, failure):
    with V2ProfileStore.create(tmp_path / "atomic.db") as store:
        catalog, _review, plan, prepared = proposal(store)

        def cancelled():
            return bool(store.financial_accounts()) if failure == "cancel" else False

        if failure == "binding":

            def fail(*_args):
                raise RuntimeError("synthetic binding failure")

            monkeypatch.setattr(store, "bind_source_account", fail)
        with pytest.raises(ImportCancelled if failure == "cancel" else RuntimeError):
            commit_import_accounts(store, prepared, catalog, plan, cancelled)
        assert not store.connection.in_transaction
        assert_unwritten(store)


def test_stale_account_metadata_refuses_before_any_import_changes(tmp_path):
    with V2ProfileStore.create(tmp_path / "stale.db") as store:
        catalog, _review, plan, prepared = proposal(store)
        store.add_financial_account(account("external"))
        with pytest.raises(ProfileFormatError, match="import_account_review_stale"):
            commit_import_accounts(store, prepared, catalog, plan)
        assert store.source_ids() == () and [a.id for a in store.financial_accounts()] == ["external"]


def test_wrong_profile_or_tampered_candidate_refuses_without_writes(tmp_path):
    with V2ProfileStore.create(tmp_path / "one.db") as store:
        catalog, _review, plan, prepared = proposal(store)
        wrong_candidate = replace(plan.candidate, row_count=plan.candidate.row_count + 1)
        with pytest.raises(ProfileFormatError, match="import_account_format_changed"):
            commit_import_accounts(store, prepared, catalog, replace(plan, candidate=wrong_candidate))
        assert_unwritten(store)
    with V2ProfileStore.create(tmp_path / "two.db") as store:
        with pytest.raises(ProfileFormatError, match="import_account_profile_changed"):
            commit_import_accounts(store, prepared, catalog, plan)
        assert_unwritten(store)


@pytest.mark.parametrize("mode", ["accountless", "mixed"])
def test_all_unknown_and_mixed_groups_are_explicit_and_atomic(tmp_path, mode):
    source = SOURCE.replace(b"Checking A,Paycheck", b",Paycheck")
    if mode == "accountless":
        source = source.replace(b"Checking A,Groceries", b",Groceries")
    declaration = json.loads(DEFINITION.read_bytes())
    declaration["columns"].pop("account")
    declaration["account_key"] = "unknown"
    catalog = _verified_catalog((json.dumps(declaration).encode(),))

    def parse(content, definition, *, suffix, cancelled=None):
        evidence = build_source_evidence(content, definition, suffix=suffix, cancelled=cancelled)
        if mode == "mixed":
            # Synthetic parser output isolates mixed binding policy; the current
            # simple opaque CSV declaration refuses blank account cells.
            first, second = evidence.payload.rows
            evidence = evidence.model_copy(
                update={
                    "payload": evidence.payload.model_copy(
                        update={
                            "rows": (
                                first,
                                second.model_copy(
                                    update={"source_account": "Checking A", "source_account_form": "opaque"}
                                ),
                            )
                        }
                    )
                }
            )
        return evidence

    with V2ProfileStore.create(tmp_path / "unknown.db") as store:
        catalog, review, plan, prepared = proposal(store, source, catalog=catalog, parse=parse)
        assert any(group.source_identity is None for group in review.groups)
        if mode == "mixed":
            assert len(review.groups) == 2
            with pytest.raises(ProfileFormatError, match="choices_incomplete"):
                prepare_import_accounts(review, plan.choices[:1], plan.selection.parser_id, plan.new_accounts)
        result = commit_import_accounts(store, prepared, catalog, plan, parse=parse)
        assert {binding.ledger_account_id for binding in store.account_bindings(result.source_sha256)} == {account().id}
        assert store.connection.execute("SELECT count(*) FROM FileAccountAssertions").fetchone() == (
            (1,) if mode == "accountless" else (0,)
        )
        assert store.connection.execute("SELECT count(*) FROM RowAccountAssignments").fetchone() == (
            (0,) if mode == "accountless" else (1,)
        )
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)


def test_caller_owned_rollback_removes_successful_composite_apply(tmp_path):
    with V2ProfileStore.create(tmp_path / "outer.db") as store:
        catalog, _review, plan, prepared = proposal(store)
        store.connection.execute("BEGIN IMMEDIATE")
        commit_import_accounts(store, prepared, catalog, plan)
        assert store.connection.in_transaction and store.source_ids()
        store.connection.execute("ROLLBACK")
        assert_unwritten(store)


@pytest.mark.parametrize("allow_abbreviated", [False, True])
def test_pdf_existing_suggestion_preserves_abbreviated_identity_preference(tmp_path, allow_abbreviated):
    with V2ProfileStore.create(tmp_path / "matching.db") as store:
        existing = replace(account(), full_account_number="12345678")
        store.add_financial_account(existing)
        catalog = _verified_catalog()
        csv = recognize_catalog_source(SOURCE, catalog=catalog, suffix=".csv")
        # A synthetic recognized-PDF read model isolates matching policy here;
        # evidence/routing tests separately establish creation of these facts.
        section = replace(csv.candidates[0].source_accounts[0], source_identity="5678", source_form="last_four")
        candidate = replace(
            csv.candidates[0],
            institution_key="chase",
            account_kind="asset",
            source_accounts=(section,),
            account_profiles=(AccountProductProfile("chase", "checking", "account_total"),),
        )
        recognition = replace(csv, suffix=".pdf", candidates=(candidate,))
        review = build_import_account_review(
            store, recognition, catalog, V2Preferences(allow_abbreviated_account_matching=allow_abbreviated)
        )
        assert review.groups[0].suggested_account_id == existing.id
        assert review.groups[0].automatic is allow_abbreviated


def test_conflicting_account_columns_refuse_instead_of_asking_user_to_map_columns(tmp_path):
    original = json.loads(DEFINITION.read_bytes())
    original["header"].append("OtherAccount")
    alternate = json.loads(json.dumps(original))
    alternate["parser_id"] = "synthetic_account_description"
    alternate["columns"]["account"] = "OtherAccount"
    catalog = _verified_catalog((json.dumps(original).encode(), json.dumps(alternate).encode()))
    lines = SOURCE.splitlines()
    source = b"\n".join((lines[0] + b",OtherAccount", lines[1] + b",Other A", lines[2] + b",Other B")) + b"\n"
    recognition = recognize_catalog_source(source, catalog=catalog, suffix=".csv")
    assert len(recognition.candidates) == 2
    with V2ProfileStore.create(tmp_path / "columns.db") as store:
        with pytest.raises(ProfileFormatError, match="import_account_routing_conflict"):
            build_import_account_review(store, recognition, catalog)
        assert_unwritten(store)


def test_provisional_account_can_be_reused_for_two_explicit_groups(tmp_path):
    source = SOURCE.replace(b"Checking A,Groceries", b"Another identity,Groceries")
    catalog = _verified_catalog()
    recognition = recognize_catalog_source(source, catalog=catalog, suffix=".csv")
    created = account()
    loan = account("loan", kind="liability", product="loan", scope="principal_component")
    with V2ProfileStore.create(tmp_path / "reuse.db") as store:
        review = build_import_account_review(store, recognition, catalog)
        assert len(review.groups) == 2
        for group in review.groups:
            assert compatible_import_accounts(review, group.group_id) == ()
            assert compatible_import_accounts(review, group.group_id, new_accounts=(created, loan)) == (created,)
        choices = tuple(ImportAccountChoice(group.group_id, created.id) for group in review.groups)
        plan = prepare_import_accounts(review, choices, recognition.candidates[0].parser_id, (created,))
        prepared = prepare_catalog_source(source, catalog=catalog, suffix=".csv", selection=plan.selection)
        result = commit_import_accounts(store, prepared, catalog, plan)
        assert store.financial_accounts() == (created,)
        assert len(store.source_account_bindings(result.source_sha256)) == 2
        assert {binding.ledger_account_id for binding in store.account_bindings(result.source_sha256)} == {created.id}
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
