"""Prepared operations own complete evidence independently of public review DTOs."""

from dataclasses import fields, is_dataclass, replace

import pytest
from parsetrail.core import v2_prepared_import as module
from parsetrail.core.source_evidence import SourceEvidence
from parsetrail.core.v2_account_products import AccountProductProfile
from parsetrail.core.v2_format_recognition import CatalogImportError
from parsetrail.core.v2_import_accounts import (
    ImportAccountChoice,
    build_import_account_review,
    commit_import_accounts,
    prepare_import_accounts,
)
from parsetrail.core.v2_prepared_import import PreparedImportSession
from parsetrail.core.v2_profile_store import ProfileFormatError, V2ProfileStore
from parsetrail.core.v2_source_import import ImportCancelled, import_prepared_catalog_source, prepare_catalog_source
from parsetrail.core.v2_workspace import WorkspaceError

from .test_v2_catalog_import import SOURCE, _verified_catalog
from .test_v2_import_accounts import account, assert_unwritten, routing_catalog
from .test_v2_workspace_account_import import create_plan, workspace_with_choices
from .test_v2_workspace_recognition import workspace_with_choices as format_workspace


def prepare(store, catalog=None):
    catalog = catalog or _verified_catalog()
    session = PreparedImportSession(SOURCE, catalog=catalog, suffix=".csv")
    review = session.review(store)
    choices = tuple(ImportAccountChoice(group.group_id, account().id) for group in review.groups)
    plan = prepare_import_accounts(review, choices, review.recognition.candidates[0].parser_id, (account(),))
    session.select(plan)
    return session, catalog, review, plan


def assert_closed(session):
    assert session._phase == "closed"
    for name in ("_source", "_catalog", "_recognition", "_review", "_plan", "_definition", "_evidence"):
        assert getattr(session, name) is None
    assert session._outputs == {} and session._output_bytes == 0


def assert_public(value):
    assert not isinstance(value, (PreparedImportSession, SourceEvidence, bytes))
    if is_dataclass(value):
        for field in fields(value):
            assert_public(getattr(value, field.name))
    elif isinstance(value, tuple):
        for item in value:
            assert_public(item)


def test_nonfirst_csv_candidate_is_parsed_only_before_confirmation_and_exact_retry_needs_no_parse(
    tmp_path, monkeypatch
):
    workspace, path, _ = workspace_with_choices(tmp_path)
    parse = module.build_source_evidence
    calls = []
    confirmed = False

    def counted(*args, **kwargs):
        assert not confirmed, "Source parser ran after confirmation"
        result = parse(*args, **kwargs)
        calls.append(result.parser_id)
        return result

    monkeypatch.setattr(module, "build_source_evidence", counted)

    def choose(_path, review):
        nonlocal confirmed
        assert calls == [item.parser_id for item in review.recognition.candidates]
        assert review.recognition.candidates[0].parser_id != "synthetic_posted_csv"
        plan = create_plan(review)
        confirmed = True
        return plan

    result = workspace.import_file(path, review_import=choose)
    assert result.status == "imported" and result.evidence.parser_id == "synthetic_posted_csv"
    assert len(calls) == 2
    retry = workspace.import_file(path, review_import=lambda *_: pytest.fail("Saved retry requested review"))
    assert retry.status == "already_imported" and retry.evidence == result.evidence
    assert len(calls) == 2


@pytest.mark.parametrize("field", ["row_count", "engine_version", "extractor_version", "definition_sha256"])
def test_modified_candidate_never_authorizes_session_output(tmp_path, field):
    with V2ProfileStore.create(tmp_path / "candidate.db") as store:
        session, catalog, _review, plan = prepare(store)
        changed = plan.candidate.row_count + 1 if field == "row_count" else "forged"
        with pytest.raises(ProfileFormatError, match="format_changed"):
            commit_import_accounts(
                store, session, catalog, replace(plan, candidate=replace(plan.candidate, **{field: changed}))
            )
        assert_closed(session)
        assert_unwritten(store)


def test_caller_trimmed_recognition_cannot_bypass_ambiguous_private_inventory(tmp_path):
    catalog = routing_catalog(tmp_path)
    with V2ProfileStore.create(tmp_path / "trimmed.db") as store:
        with PreparedImportSession(SOURCE, catalog=catalog, suffix=".csv") as session:
            review = session.review(store)
            candidate = review.recognition.candidates[0]
            trimmed = replace(review, recognition=replace(review.recognition, candidates=(candidate,)))
            choices = tuple(ImportAccountChoice(group.group_id, account().id) for group in review.groups)
            forged = prepare_import_accounts(trimmed, choices, candidate.parser_id, (account(),))
            with pytest.raises(ProfileFormatError, match="routing_conflict"):
                session.select(forged)
            assert_unwritten(store)
        assert_closed(session)


def test_operation_ids_profile_identity_and_one_use_are_enforced(tmp_path):
    with V2ProfileStore.create(tmp_path / "first.db") as store:
        one, catalog, review, plan = prepare(store)
        two, _, _, other_plan = prepare(store, catalog)
        with pytest.raises(ProfileFormatError, match="format_changed"):
            commit_import_accounts(store, one, catalog, other_plan)
        assert_closed(one)
        result = commit_import_accounts(store, two, catalog, other_plan)
        assert result.status == "imported"
        assert_closed(two)
        with pytest.raises(ProfileFormatError, match="preparation_unavailable"):
            commit_import_accounts(store, two, catalog, other_plan)
        assert_public(review)
        assert_public(plan)
    with V2ProfileStore.create(tmp_path / "foreign.db") as store:
        foreign, catalog, _, foreign_plan = prepare(store)
    with V2ProfileStore.open(tmp_path / "first.db") as store:
        with pytest.raises(ProfileFormatError, match="profile_changed"):
            commit_import_accounts(store, foreign, catalog, foreign_plan)
        assert_closed(foreign)


@pytest.mark.parametrize("tamper", ["payload", "canonical", "catalog", "before_write", "late_catalog"])
def test_private_selected_output_and_catalog_are_revalidated_in_full(tmp_path, tamper):
    with V2ProfileStore.create(tmp_path / "tamper.db") as store:
        session, catalog, _review, plan = prepare(store)

        def change_payload():
            evidence = session._evidence
            row = evidence.payload.rows[-1]
            changed = row.model_copy(update={"amount": row.amount.model_copy(update={"minor": -999999})})
            session._evidence = evidence.model_copy(
                update={"payload": evidence.payload.model_copy(update={"rows": (*evidence.payload.rows[:-1], changed)})}
            )

        callback = None
        if tamper == "payload":
            change_payload()
        elif tamper == "canonical":
            content, digest = session._outputs[plan.selection.parser_id]
            session._outputs[plan.selection.parser_id] = (content + b" ", digest)
        elif tamper == "catalog":
            entry = replace(
                catalog.definitions[0], account_profiles=(AccountProductProfile("citi", "savings", "account_total"),)
            )
            catalog = replace(catalog, definitions=(entry,))
        elif tamper == "before_write":
            callback = change_payload
        else:

            def callback():
                object.__setattr__(catalog, "source_revision", "f" * 40)

        with pytest.raises(ProfileFormatError, match="format_changed"):
            commit_import_accounts(store, session, catalog, plan, before_write=callback)
        assert_closed(session)
        assert_unwritten(store)


@pytest.mark.parametrize("outcome", ["cancel", "failure", "base_exception", "success"])
def test_apply_always_releases_owner_and_preserves_atomicity(tmp_path, monkeypatch, outcome):
    with V2ProfileStore.create(tmp_path / "cleanup.db") as store:
        session, catalog, review, plan = prepare(store)
        if outcome in {"failure", "base_exception"}:

            def fail(*_args):
                raise RuntimeError("synthetic failure") if outcome == "failure" else KeyboardInterrupt()

            monkeypatch.setattr(store, "bind_source_account", fail)
        if outcome == "success":
            assert commit_import_accounts(store, session, catalog, plan).status == "imported"
        else:
            error = {"cancel": ImportCancelled, "failure": RuntimeError, "base_exception": KeyboardInterrupt}[outcome]
            with pytest.raises(error):
                commit_import_accounts(store, session, catalog, plan, cancelled=lambda: outcome == "cancel")
            assert_unwritten(store)
        assert_closed(session)
        assert_public(review)
        assert_public(plan)


def test_aggregate_budget_refuses_entire_operation_before_review(tmp_path, monkeypatch):
    workspace, path, _ = workspace_with_choices(tmp_path)
    monkeypatch.setattr(module, "MAX_EVIDENCE_BYTES", 1)
    with pytest.raises(CatalogImportError, match="import_preparation_size_limit"):
        workspace.import_file(path, review_import=lambda *_: pytest.fail("Overflow reached UI"))
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert_unwritten(store)


def test_legacy_prepared_dto_modified_beyond_preview_cannot_be_saved(tmp_path):
    header, first, second = SOURCE.splitlines()
    source = b"\n".join((header, first, *(second for _ in range(6)))) + b"\n"
    catalog = _verified_catalog()
    with V2ProfileStore.create(tmp_path / "legacy.db") as store:
        from parsetrail.core.v2_format_recognition import recognize_catalog_source

        recognition = recognize_catalog_source(source, catalog=catalog, suffix=".csv")
        review = build_import_account_review(store, recognition, catalog)
        choices = tuple(ImportAccountChoice(group.group_id, account().id) for group in review.groups)
        plan = prepare_import_accounts(review, choices, recognition.candidates[0].parser_id, (account(),))
        prepared = prepare_catalog_source(source, catalog=catalog, suffix=".csv", selection=plan.selection)
        rows = prepared.evidence.payload.rows
        changed = rows[5].model_copy(update={"amount": rows[5].amount.model_copy(update={"minor": -999999})})
        evidence = prepared.evidence.model_copy(
            update={"payload": prepared.evidence.payload.model_copy(update={"rows": (*rows[:5], changed, *rows[6:])})}
        )
        with pytest.raises(ProfileFormatError, match="format_changed"):
            commit_import_accounts(store, replace(prepared, evidence=evidence), catalog, plan)
        assert_unwritten(store)


@pytest.mark.parametrize("stage", ["profile_open", "before_write"])
@pytest.mark.parametrize("drift", ["source", "catalog"])
def test_explicit_format_late_input_drift_refuses_without_writes(tmp_path, monkeypatch, stage, drift):
    from parsetrail.core import v2_workspace as workspace_module

    workspace, path, activate = format_workspace(tmp_path)

    def mutate():
        if drift == "source":
            path.write_bytes(path.read_bytes().replace(b"Coffee", b"Changed after profile open"))
        else:
            activate(2)

    if stage == "profile_open":
        original_open = V2ProfileStore.open

        def open_profile(_cls, profile_path, *, read_only=False):
            store = original_open(profile_path, read_only=read_only)
            if not read_only:
                mutate()
            return store

        monkeypatch.setattr(V2ProfileStore, "open", classmethod(open_profile))
    else:
        original_import = workspace_module.import_prepared_catalog_source

        def import_changed(*args, **kwargs):
            original_callback = kwargs["before_write"]

            def changed():
                mutate()
                original_callback()

            kwargs["before_write"] = changed
            return original_import(*args, **kwargs)

        monkeypatch.setattr(workspace_module, "import_prepared_catalog_source", import_changed)
    error = WorkspaceError if drift == "source" else CatalogImportError
    code = "source_changed_since_preview" if drift == "source" else "catalog_selection_catalog_changed"
    with pytest.raises(error, match=code):
        workspace.import_file(
            path, review_format=lambda _path, recognition: recognition.selection("synthetic_posted_csv")
        )
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert_unwritten(store)


@pytest.mark.parametrize("stage", ["claim", "callback", "validation"])
def test_explicit_format_cancellation_after_claim_or_freshness_callback_is_atomic(tmp_path, monkeypatch, stage):
    catalog = _verified_catalog()
    with V2ProfileStore.create(tmp_path / "format-cancel.db") as store:
        session = PreparedImportSession(SOURCE, catalog=catalog, suffix=".csv")
        recognition = session.format_review(store)
        selection = recognition.selection(recognition.candidates[0].parser_id)
        session.select_format(selection)
        stopped = False
        original_claim = PreparedImportSession.claim_format
        original_validate = PreparedImportSession.validate_apply

        def claim(*args):
            nonlocal stopped
            selection = original_claim(*args)
            stopped = stage == "claim"
            return selection

        def before_write():
            nonlocal stopped
            assert not store.connection.in_transaction
            stopped = stage == "callback"

        def validate(*args, **kwargs):
            nonlocal stopped
            original_validate(*args, **kwargs)
            stopped = stage == "validation"

        monkeypatch.setattr(PreparedImportSession, "claim_format", claim)
        monkeypatch.setattr(PreparedImportSession, "validate_apply", validate)
        with pytest.raises(ImportCancelled):
            import_prepared_catalog_source(
                store,
                session,
                catalog=catalog,
                selection=selection,
                cancelled=lambda: stopped,
                before_write=before_write,
            )
        assert_closed(session)
        assert_unwritten(store)


def test_mutating_public_recognition_cannot_trim_private_ambiguity_proof(tmp_path):
    catalog = routing_catalog(tmp_path)
    with V2ProfileStore.create(tmp_path / "public-recognition.db") as store:
        with PreparedImportSession(SOURCE, catalog=catalog, suffix=".csv") as session:
            review = session.review(store)
            selected = review.recognition.candidates[0]
            object.__setattr__(review.recognition, "candidates", (selected,))
            choices = tuple(ImportAccountChoice(group.group_id, account().id) for group in review.groups)
            forged = prepare_import_accounts(review, choices, selected.parser_id, (account(),))
            with pytest.raises(ProfileFormatError, match="routing_conflict"):
                session.select(forged)
            assert_unwritten(store)


@pytest.mark.parametrize("stage", ["after_select", "before_write"])
@pytest.mark.parametrize("field", ["choice", "new_account", "selection", "candidate"])
def test_public_nested_plan_mutation_cannot_change_authorized_import(tmp_path, stage, field):
    with V2ProfileStore.create(tmp_path / "public-plan.db") as store:
        if field == "choice":
            store.add_financial_account(account("a"))
            store.add_financial_account(account("b"))
            catalog = _verified_catalog()
            session = PreparedImportSession(SOURCE, catalog=catalog, suffix=".csv")
            review = session.review(store)
            plan = prepare_import_accounts(
                review,
                tuple(ImportAccountChoice(group.group_id, "a") for group in review.groups),
                review.recognition.candidates[0].parser_id,
            )
            session.select(plan)
        else:
            session, catalog, _review, plan = prepare(store)

        def mutate():
            if field == "choice":
                object.__setattr__(plan.choices[0], "account_id", "b")
            elif field == "new_account":
                object.__setattr__(plan.new_accounts[0], "name", "Changed after selection")
            elif field == "selection":
                object.__setattr__(plan.selection, "source_sha256", "0" * 64)
            else:
                object.__setattr__(plan.candidate, "engine_version", "changed-after-selection")

        if stage == "after_select":
            mutate()
        with pytest.raises(ProfileFormatError, match="format_changed"):
            commit_import_accounts(
                store, session, catalog, plan, before_write=mutate if stage == "before_write" else None
            )
        assert_closed(session)
        if field == "choice":
            assert store.source_ids() == ()
            assert {value.id for value in store.financial_accounts()} == {"a", "b"}
        else:
            assert_unwritten(store)
