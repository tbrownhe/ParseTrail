"""Source closing points are finite, auditable facts separate from journal money."""

from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path

import pytest
from parsetrail.core.v2_profile_store import (
    BindingCorrectionTarget,
    FinancialAccount,
    ProfileFormatError,
    V2ProfileStore,
    _transfer_record_digest,
)
from parsetrail.core.v2_source_pipeline import build_source_evidence

from devtools.parser_engine_pilot.synthetic_family_sources import family_sources

ROOT = Path(__file__).parents[2] / "devtools" / "parser_engine_pilot"
AS_OF = date(2026, 12, 31)
FAMILY_FACTS = {
    "chase-card-pilot-definition.json": ("liability", "account_total", -3000),
    "happen-savings-pilot-definition.json": ("asset", "account_total", 11000),
    "lendingclub-savings-pilot-definition.json": ("asset", "account_total", 11600),
    "hsa-cash-pilot-definition.json": ("asset", "cash_component", 110010),
    "fidelity-hsa-summary-pilot-definition.json": ("asset", "account_total", 14500),
    "capital-one-loan-pilot-definition.json": ("liability", "principal_component", -950000),
    "fidelity-401k-summary-pilot-definition.json": ("asset", "account_total", 14000),
    "vanguard-summary-pilot-definition.json": ("asset", "account_total", 17000),
    "occu-bank-pilot-definition.json": ("asset", "account_total", 11000),
    "occu-card-pilot-definition.json": ("liability", "account_total", -9500),
    "legacy-citi-pilot-definition.json": ("liability", "account_total", -9000),
    "yamaha-card-pilot-definition.json": ("liability", "account_total", -99000),
    "wells-loan-pilot-definition.json": ("liability", "principal_component", -8000),
    "usbank-rei-card-pilot-definition.json": ("liability", "account_total", -9000),
    "transamerica-summary-pilot-definition.json": ("asset", "account_total", 11500),
    "middle-citi-table-pilot-definition.json": ("liability", "account_total", -11000),
    "recent-citi-pilot-definition.json": ("liability", "account_total", -11000),
    "wells-table-pilot-definition.json": ("asset", "account_total", 10100),
    "wells-personal-table-pilot-definition.json": ("asset", "account_total", 12000),
    "synchrony-table-pilot-definition.json": ("liability", "account_total", -11000),
    "lendingclub-table-pilot-definition.json": ("asset", "account_total", 11000),
}


@pytest.fixture(scope="module")
def samples():
    return {
        case.definition_name: (
            case.source,
            (ROOT / case.definition_name).read_bytes(),
            build_source_evidence(case.source, (ROOT / case.definition_name).read_bytes(), suffix=case.suffix),
            case.suffix,
        )
        for case in family_sources()
    }


def setup(
    path, samples, family="capital-one-loan-pilot-definition.json", *, empty=False, account="target", transform=None
):
    content, definition, evidence, suffix = samples[family]
    if empty:
        section = evidence.payload.accounts[0].model_copy(update={"rows": ()})
        evidence = evidence.model_copy(
            update={
                "payload": evidence.payload.model_copy(
                    update={"accounts": (section,), "independent_balance_verified": False}
                )
            }
        )
    if transform is not None:
        evidence = transform(evidence)
    kind, scope, _ = FAMILY_FACTS[family]
    with V2ProfileStore.create(path) as store:
        store.import_source(content, definition, evidence, suffix=suffix)
        store.add_financial_account(
            FinancialAccount(account, "Synthetic account", kind, "synthetic", tracking_scope=scope)
        )
        section = evidence.payload.accounts[0]
        store.bind_source_account(
            evidence.source_sha256, section.source_identity, section.source_identity_form, account
        )
    return evidence


def record_source(store, account="target", *, corrects=None, allow_conflict=False):
    frame = store.account_anchor_snapshot(account, as_of=AS_OF)
    candidate = frame.source_value_candidates[0]
    return store.record_reviewed_source_value(
        account,
        candidate.candidate_id,
        expected_candidate_sha256=candidate.version,
        expected_basis_sha256=frame.basis_sha256,
        reference="Explicit source closing review",
        reason="Nonposting source point only",
        corrects_value_id=corrects,
        allow_conflict=allow_conflict,
    )


def manual(store, amount, day, *, corrects=None, allow_conflict=False):
    frame = store.account_anchor_snapshot("target")
    return store.record_reviewed_dated_value(
        "target",
        amount_minor=amount,
        value_date=day,
        tracking_scope=frame.account.tracking_scope,
        reference="Independent reviewed point",
        reason="Manual fact remains manual",
        expected_basis_sha256=frame.basis_sha256,
        corrects_value_id=corrects,
        allow_conflict=allow_conflict,
    )


def withdraw(store, value, reason="Withdraw unsupported dated point"):
    frame = store.account_anchor_snapshot(value.account_id)
    return store.withdraw_reviewed_dated_value(
        value.account_id,
        value.value_id,
        expected_value_version=value.version,
        expected_basis_sha256=frame.basis_sha256,
        reason=reason,
    )


@pytest.mark.parametrize("family", sorted(FAMILY_FACTS))
def test_all_finite_statement_families_record_exact_nonposting_closing_point(tmp_path, samples, family):
    path = tmp_path / "source.db"
    evidence = setup(path, samples, family)
    original = path.read_bytes()
    with V2ProfileStore.open(path, read_only=True) as store:
        frame = store.source_dated_value_snapshot("target", as_of=AS_OF)
        candidate = frame.source_value_candidates[0]
        assert candidate.amount_minor == FAMILY_FACTS[family][2] and not candidate.blockers
        assert candidate.proof.closing == evidence.payload.accounts[0].closing
        assert candidate.proof.value_date == evidence.payload.end
        assert frame.value_status == "missing" and frame.latest_dated_value is None
    assert path.read_bytes() == original
    with V2ProfileStore.open(path) as store:
        value = record_source(store)
        assert value.origin == "source" and value.amount_minor == FAMILY_FACTS[family][2]
        assert value.source_proof.closing == evidence.payload.accounts[0].closing
        assert value.source_proof.value_date == evidence.payload.end
        frame = store.account_anchor_snapshot("target", as_of=AS_OF)
        assert frame.value_status == "known" and frame.latest_dated_value == value
        assert frame.opening is None and frame.position_debit_minor is None and frame.recorded_debit_minor == 0
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
        assert store._active_consumed() == {}
        assert store.load_import(evidence.source_sha256).evidence == evidence
    V2ProfileStore.snapshot_to(path, tmp_path / "backup.db")


def test_same_date_conflict_is_explicit_and_never_selected_by_latest_id(tmp_path, samples):
    path = tmp_path / "conflict.db"
    setup(path, samples)
    with V2ProfileStore.open(path) as store:
        sourced = record_source(store)
        with pytest.raises(ProfileFormatError, match="account_dated_value_conflict_requires_review"):
            manual(store, -900000, sourced.value_date)
        opposing = manual(store, -900000, sourced.value_date, allow_conflict=True)
        frame = store.account_anchor_snapshot("target", as_of=AS_OF)
        assert frame.value_status == "conflict" and frame.latest_dated_value is None
        assert {v.value_id for v in frame.conflicting_dated_values} == {sourced.value_id, opposing.value_id}
        position = store.account_positions(as_of=AS_OF).accounts[0]
        assert position.value_status == "conflict" and position.latest_dated_value is None
        assert position.recorded_debit_minor == 0 and position.position_debit_minor is None
        later = manual(store, -800000, date(2026, 2, 28))
        assert store.account_anchor_snapshot("target", as_of=date(2026, 2, 28)).latest_dated_value == later
        assert store.account_anchor_snapshot("target", as_of=date(2026, 1, 31)).value_status == "conflict"
        withdraw(store, opposing)
        assert store.account_anchor_snapshot("target", as_of=date(2026, 1, 31)).latest_dated_value == sourced


def test_agreeing_points_are_one_known_value_and_cross_origin_corrections_are_explicit(tmp_path, samples):
    path = tmp_path / "origins.db"
    setup(path, samples)
    with V2ProfileStore.open(path) as store:
        sourced = record_source(store)
        agreeing = manual(store, sourced.amount_minor, sourced.value_date)
        frame = store.account_anchor_snapshot("target", as_of=AS_OF)
        assert frame.value_status == "known" and len(frame.current_dated_values) == 2
        manual_replacement = manual(store, -900000, sourced.value_date, corrects=sourced.value_id, allow_conflict=True)
        assert manual_replacement.origin == "manual" and manual_replacement.source_proof is None
        assert (
            next(
                v for v in store.account_anchor_snapshot("target").dated_values if v.value_id == sourced.value_id
            ).source_proof
            == sourced.source_proof
        )
        sourced_replacement = record_source(store, corrects=manual_replacement.value_id)
        assert sourced_replacement.origin == "source" and sourced_replacement.source_proof is not None
        assert store.account_anchor_snapshot("target", as_of=AS_OF).value_status == "known"
        assert agreeing.value_id != sourced_replacement.value_id


def test_withdrawal_unknown_zero_and_historical_retry_do_not_touch_fresh_reestablishment(tmp_path, samples):
    path = tmp_path / "withdraw.db"
    setup(path, samples)
    with V2ProfileStore.open(path) as store:
        original = record_source(store)
        frame = store.account_anchor_snapshot("target")
        action = store.withdraw_reviewed_dated_value(
            "target",
            original.value_id,
            expected_value_version=original.version,
            expected_basis_sha256=frame.basis_sha256,
            reason="Wrong source point",
        )
        assert store.account_anchor_snapshot("target", as_of=AS_OF).latest_dated_value is None
        fresh = record_source(store)
        assert fresh.value_id != original.value_id
        assert (
            store.withdraw_reviewed_dated_value(
                "target",
                original.value_id,
                expected_value_version=original.version,
                expected_basis_sha256=frame.basis_sha256,
                reason="Wrong source point",
            )
            == action
        )
        assert store.account_anchor_snapshot("target", as_of=AS_OF).latest_dated_value == fresh
        zero = manual(store, 0, date(2026, 2, 28))
        assert store.account_anchor_snapshot("target", as_of=AS_OF).latest_dated_value.amount_minor == 0
        withdraw(store, zero)
        assert store.account_anchor_snapshot("target", as_of=AS_OF).latest_dated_value == fresh


def test_empty_section_anchor_blocks_rebind_until_withdrawal_then_retains_original_account_proof(tmp_path, samples):
    path = tmp_path / "empty.db"
    evidence = setup(path, samples, empty=True)
    section = evidence.payload.accounts[0]
    with V2ProfileStore.open(path) as store:
        original = record_source(store)
        store.add_financial_account(
            FinancialAccount("other", "Other principal", "liability", "synthetic", tracking_scope="principal_component")
        )
        target = BindingCorrectionTarget(
            evidence.source_sha256, "source", section.source_identity, section.source_identity_form
        )
        with pytest.raises(ProfileFormatError, match="account_binding_source_backed_dated_value_anchor"):
            store.bind_source_account(
                evidence.source_sha256, section.source_identity, section.source_identity_form, "other"
            )
        selected = store.binding_correction_snapshot(target, destination_account_id="other")
        assert selected.affected_row_ids == () and selected.source_value_anchors == (original,)
        assert "source_backed_dated_value_anchor" in selected.blockers
        with pytest.raises(ProfileFormatError, match="source_backed_dated_value_anchor"):
            store.correct_reviewed_binding(
                target,
                destination_account_id="other",
                expected_basis_sha256=selected.basis_sha256,
                reason="Must retire point first",
            )
        withdraw(store, original)
        selected = store.binding_correction_snapshot(target, destination_account_id="other")
        store.correct_reviewed_binding(
            target,
            destination_account_id="other",
            expected_basis_sha256=selected.basis_sha256,
            reason="Reviewed correct principal identity",
        )
        assert record_source(store, "other").account_id == "other"
        old = store.account_anchor_snapshot("target").dated_values[0]
        assert old.account_id == "target" and old.state == "withdrawn" and old.source_proof == original.source_proof
    V2ProfileStore.snapshot_to(path, tmp_path / "backup.db")


def test_stale_and_failed_value_writes_leave_no_facts_or_journal_side_effects(tmp_path, samples):
    path = tmp_path / "atomic.db"
    setup(path, samples)
    with V2ProfileStore.open(path) as store:
        frame = store.account_anchor_snapshot("target")
        candidate = frame.source_value_candidates[0]
        with pytest.raises(ProfileFormatError, match="changed_since_selection"):
            store.record_reviewed_source_value(
                "target",
                candidate.candidate_id,
                expected_candidate_sha256=candidate.version,
                expected_basis_sha256="0" * 64,
                reference="Source",
                reason="Stale",
            )
        store.connection.execute(
            "CREATE TEMP TRIGGER fail_value BEFORE INSERT ON AccountDatedValues BEGIN SELECT RAISE(ABORT,'value failure'); END"
        )
        with pytest.raises(sqlite3.IntegrityError, match="value failure"):
            record_source(store)
        assert store.connection.execute("SELECT count(*) FROM AccountDatedValues").fetchone() == (0,)
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)


def test_missing_source_value_account_refuses_with_controlled_profile_error(tmp_path):
    with V2ProfileStore.create(tmp_path / "missing.db") as store:
        with pytest.raises(ProfileFormatError, match="financial_account_missing"):
            store.record_reviewed_source_value(
                "missing",
                "a" * 64,
                expected_candidate_sha256="b" * 64,
                expected_basis_sha256="c" * 64,
                reference="Synthetic review",
                reason="Missing account input",
            )
        assert not store.connection.in_transaction


def test_schema_eighteen_is_refused_before_writes(tmp_path):
    path = tmp_path / "old.db"
    with V2ProfileStore.create(path) as store:
        store.connection.execute("PRAGMA user_version=18")
    before = path.read_bytes()
    with pytest.raises(ProfileFormatError, match="unsupported_profile_format"):
        V2ProfileStore.open(path)
    assert path.read_bytes() == before


def review_source(store, source_id, *, account="target", reference="Reviewed section A only", previous=None):
    return store.record_statement_source_review(
        account,
        source_id,
        expected_revision_id=previous,
        opening_origin="reported",
        closing_origin="reported",
        timing_confirmed=True,
        posting_dates="reported",
        source_reference=reference,
    )


def test_simultaneous_sections_never_inherit_another_sections_source_assertion(tmp_path, samples):
    path = tmp_path / "sections.db"
    evidence = setup(path, samples, "occu-bank-pilot-definition.json")
    first, second = evidence.payload.accounts
    with V2ProfileStore.open(path) as store:
        revision = review_source(store, evidence.source_sha256)
        sourced = record_source(store)
        store.bind_source_account(evidence.source_sha256, second.source_identity, second.source_identity_form, "target")
        frame = store.account_anchor_snapshot("target")
        candidates = {c.source_identity: c for c in frame.source_value_candidates}
        assert candidates[first.source_identity].source_review.revision_id == revision
        assert candidates[second.source_identity].source_review is None
        assert candidates[second.source_identity].proof.review_annotation is None
        assert store.statement_source_reviews("target") == ()
        assert store.statement_source_review_history("target")[0].source_identity == first.source_identity
        assert frame.dated_values[0].source_proof == sourced.source_proof
        assert not frame.dated_values[0].source_review_changed
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)


def test_sequential_section_rebinding_cannot_inherit_opening_or_closing_review_and_retired_proof_survives(
    tmp_path, samples
):
    path = tmp_path / "sequential.db"
    evidence = setup(path, samples, "occu-bank-pilot-definition.json")
    first, second = evidence.payload.accounts
    with V2ProfileStore.open(path) as store:
        revision = review_source(store, evidence.source_sha256)
        sourced = record_source(store)
        withdraw(store, sourced)
        store.add_financial_account(FinancialAccount("other", "Other asset", "asset", "synthetic"))
        target = BindingCorrectionTarget(
            evidence.source_sha256, "source", first.source_identity, first.source_identity_form
        )
        selected = store.binding_correction_snapshot(target, destination_account_id="other")
        store.correct_reviewed_binding(
            target,
            destination_account_id="other",
            expected_basis_sha256=selected.basis_sha256,
            reason="Retired value permits original section move",
        )
        store.bind_source_account(evidence.source_sha256, second.source_identity, second.source_identity_form, "target")
        frame = store.account_anchor_snapshot("target")
        assert len(frame.source_value_candidates) == 1 and frame.source_value_candidates[0].source_review is None
        assert frame.source_value_candidates[0].proof.review_annotation is None
        assert store.statement_source_reviews("target") == ()
        assert store.statement_source_review_history("target")[0].revision_id == revision
        with pytest.raises(ProfileFormatError, match="opening_review_blocked"):
            store.post_reviewed_opening("target")
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
        assert store.account_anchor_snapshot("target").dated_values[0].source_proof == sourced.source_proof
        new_revision = review_source(store, evidence.source_sha256, reference="New explicit review of section B")
        assert (
            new_revision != revision
            and store.statement_source_reviews("target")[0].source_identity == second.source_identity
        )
    V2ProfileStore.snapshot_to(path, tmp_path / "backup.db")


def test_parser_provenance_and_changed_authored_assertions_remain_separate_qualifiers(tmp_path, samples):
    path = tmp_path / "annotations.db"
    evidence = setup(path, samples, "happen-savings-pilot-definition.json")
    with V2ProfileStore.open(path) as store:
        first = review_source(store, evidence.source_sha256)
        sourced = record_source(store)
        assert sourced.source_proof.closing.provenance == "observed"
        assert sourced.source_proof.review_annotation.closing_origin == "reported"
        store.record_statement_source_review(
            "target",
            evidence.source_sha256,
            expected_revision_id=first,
            opening_origin="unestablished",
            closing_origin="unestablished",
            timing_confirmed=False,
            posting_dates="unverified",
            source_reference="Later authored uncertainty",
        )
        frame = store.account_anchor_snapshot("target", as_of=AS_OF)
        assert frame.latest_dated_value.source_review_changed
        assert frame.latest_dated_value.source_proof.review_annotation.closing_origin == "reported"
        assert frame.source_value_candidates[0].source_review.closing_origin == "unestablished"
        assert frame.source_value_candidates[0].proof.closing.provenance == "observed"
        assert frame.value_status == "known" and frame.position_debit_minor is None


def test_source_derived_endpoint_and_closing_are_labeled_without_becoming_printed(tmp_path, samples):
    path = tmp_path / "derived.db"

    def derived(evidence):
        section = evidence.payload.accounts[0]
        section = section.model_copy(
            update={"closing": section.closing.model_copy(update={"raw": None, "provenance": "derived"})}
        )
        return evidence.model_copy(
            update={
                "payload": evidence.payload.model_copy(
                    update={
                        "accounts": (section,),
                        "end": evidence.payload.end.model_copy(update={"raw": None, "provenance": "derived"}),
                        "independent_balance_verified": False,
                    }
                )
            }
        )

    setup(path, samples, "happen-savings-pilot-definition.json", transform=derived)
    with V2ProfileStore.open(path) as store:
        sourced = record_source(store)
        assert sourced.source_proof.closing.provenance == "derived" and sourced.source_proof.closing.raw is None
        assert (
            sourced.source_proof.value_date.provenance == "derived" and sourced.source_proof.review_annotation is None
        )
        assert store.statement_source_reviews("target") == ()
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)


@pytest.mark.parametrize("change", ["unknown_closing", "assumed_date", "wrong_scope", "wrong_kind"])
def test_unavailable_source_or_wrong_scope_stays_pending_without_value_writes(tmp_path, samples, change):
    path = tmp_path / "unsupported.db"

    def unavailable(evidence):
        payload = evidence.payload
        section = payload.accounts[0]
        if change == "unknown_closing":
            section = section.model_copy(
                update={
                    "closing": section.closing.model_copy(update={"raw": None, "minor": None, "provenance": "unknown"})
                }
            )
        endpoint = (
            payload.end.model_copy(update={"raw": None, "provenance": "assumed"})
            if change == "assumed_date"
            else payload.end
        )
        return evidence.model_copy(
            update={
                "payload": payload.model_copy(
                    update={"accounts": (section,), "end": endpoint, "independent_balance_verified": False}
                )
            }
        )

    setup(path, samples, transform=unavailable)
    with V2ProfileStore.open(path) as store:
        if change == "wrong_scope":
            store.update_financial_account(
                FinancialAccount("target", "Wrong total", "liability", "synthetic", tracking_scope="account_total")
            )
        if change == "wrong_kind":
            store.connection.execute(
                "UPDATE Accounts SET kind='asset',tracking_scope='account_total' WHERE id='target'"
            )
        frame = store.account_anchor_snapshot("target")
        assert frame.source_value_candidates[0].blockers and frame.source_value_candidates[0].proof is None
        with pytest.raises(ProfileFormatError, match="source_value_candidate_unavailable"):
            record_source(store)
        assert store.connection.execute("SELECT count(*) FROM AccountDatedValues").fetchone() == (0,)


def test_value_snapshot_is_coherent_during_wal_writer_and_old_form_stays_stale(tmp_path, samples, monkeypatch):
    path = tmp_path / "wal.db"
    setup(path, samples)
    with V2ProfileStore.open(path) as store:
        store.connection.execute("PRAGMA journal_mode=WAL")
        original = store._source_value_candidates

        def concurrent_write(account_id):
            result = original(account_id)
            with V2ProfileStore.open(path) as writer:
                manual(writer, -900000, date(2026, 2, 28))
            return result

        monkeypatch.setattr(store, "_source_value_candidates", concurrent_write)
        old = store.account_anchor_snapshot("target", as_of=AS_OF)
        monkeypatch.setattr(store, "_source_value_candidates", original)
        assert old.value_status == "missing" and old.latest_dated_value is None
        current = store.account_anchor_snapshot("target", as_of=AS_OF)
        assert current.value_status == "known" and current.basis_sha256 != old.basis_sha256
        candidate = old.source_value_candidates[0]
        with pytest.raises(ProfileFormatError, match="account_anchor_changed_since_selection"):
            store.record_reviewed_source_value(
                "target",
                candidate.candidate_id,
                expected_candidate_sha256=candidate.version,
                expected_basis_sha256=old.basis_sha256,
                reference="Stale form",
                reason="Old display cannot authorize changed context",
            )


@pytest.mark.parametrize(
    "mutation",
    [
        "proof_amount",
        "proof_kind",
        "proof_deep",
        "withdraw_prior",
        "proof_amount_rehashed",
        "proof_sign_rehashed",
        "proof_deep_rehashed",
        "withdraw_prior_rehashed",
    ],
)
def test_tampered_value_proof_or_withdrawal_refuses_common_reads_and_backup(tmp_path, samples, mutation):
    path = tmp_path / "tamper.db"
    setup(path, samples)
    with V2ProfileStore.open(path) as store:
        sourced = record_source(store)
        if mutation.startswith("withdraw_prior"):
            withdraw(store, sourced)
    with sqlite3.connect(path) as connection:
        table = "DatedValueWithdrawals" if mutation.startswith("withdraw_prior") else "AccountDatedValues"
        trigger = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name=?", (f"immutable_{table}_update",)
        ).fetchone()[0]
        connection.execute(f"DROP TRIGGER immutable_{table}_update")
        if mutation.startswith("withdraw_prior"):
            connection.execute("UPDATE DatedValueWithdrawals SET prior_version=?", ("0" * 64,))
        else:
            raw = connection.execute("SELECT source_proof FROM AccountDatedValues").fetchone()[0]
            proof = json.loads(raw)
            if mutation.startswith("proof_amount"):
                proof["closing"]["minor"] += 1
            if mutation == "proof_kind":
                proof["financial_kind"] = "asset"
            if mutation.startswith("proof_sign"):
                proof["sign_rule"] = "debit-signed-1"
            raw = "[" * 11000 + "0" + "]" * 11000 if mutation.startswith("proof_deep") else json.dumps(proof)
            connection.execute("UPDATE AccountDatedValues SET source_proof=?", (raw,))
        if mutation.endswith("rehashed"):
            row = connection.execute(f"SELECT * FROM {table}").fetchone()
            checksum = (
                _transfer_record_digest(*row[:5], row[6])
                if table == "DatedValueWithdrawals"
                else _transfer_record_digest(*row[:9], row[10], row[11], row[12], row[13])
            )
            connection.execute(f"UPDATE {table} SET record_sha256=?", (checksum,))
        connection.execute(trigger)
    before = path.read_bytes()
    with V2ProfileStore.open(path, read_only=True) as store:
        with pytest.raises(ProfileFormatError, match="account_dated_value_history_integrity"):
            store.account_positions(as_of=AS_OF)
        with pytest.raises(ProfileFormatError, match="account_dated_value_history_integrity"):
            store.reviewed_journal_export(start=date(2026, 1, 1), end=AS_OF)
    with pytest.raises(ProfileFormatError, match="account_dated_value_history_integrity"):
        V2ProfileStore.snapshot_to(path, tmp_path / "refused.db")
    assert path.read_bytes() == before and not (tmp_path / "refused.db").exists()


@pytest.mark.parametrize("wrapper", ["statement", "opening"])
def test_initially_unreviewed_source_form_cannot_save_assertions_for_a_rebound_section(tmp_path, samples, wrapper):
    path = tmp_path / "stale_section.db"
    evidence = setup(path, samples, "occu-bank-pilot-definition.json")
    first, second = evidence.payload.accounts
    with V2ProfileStore.open(path) as store:
        loaded = store.statement_source_review_snapshot("target", evidence.source_sha256)
        assert loaded.review is None and loaded.source_account.source_identity == first.source_identity
        store.clear_source_account_binding(evidence.source_sha256, first.source_identity, first.source_identity_form)
        store.bind_source_account(evidence.source_sha256, second.source_identity, second.source_identity_form, "target")
        common = {
            "expected_revision_id": None,
            "opening_origin": "reported",
            "timing_confirmed": True,
            "source_reference": "I reviewed original section A only",
            "expected_section": (loaded.source_account.source_identity, loaded.source_account.source_identity_form),
            "expected_basis_sha256": loaded.basis_sha256,
        }
        with pytest.raises(ProfileFormatError, match="changed_since_selection"):
            if wrapper == "statement":
                store.record_statement_source_review(
                    "target", evidence.source_sha256, closing_origin="reported", posting_dates="reported", **common
                )
            else:
                store.record_opening_source_review("target", evidence.source_sha256, **common)
        assert store.statement_source_reviews("target") == ()
        assert store.statement_source_review_history("target") == ()
        with pytest.raises(ProfileFormatError, match="opening_review_blocked"):
            store.post_reviewed_opening("target")
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)


def test_source_review_snapshot_and_opening_sections_remain_coherent_during_wal_context_change(
    tmp_path, samples, monkeypatch
):
    path = tmp_path / "review_wal.db"
    evidence = setup(path, samples, "occu-bank-pilot-definition.json")
    first, second = evidence.payload.accounts
    with V2ProfileStore.open(path) as store:
        store.connection.execute("PRAGMA journal_mode=WAL")
        original = store.statement_coverage

        def concurrent_bind():
            rows = original()
            with V2ProfileStore.open(path) as writer:
                writer.clear_source_account_binding(
                    evidence.source_sha256, first.source_identity, first.source_identity_form
                )
                writer.bind_source_account(
                    evidence.source_sha256, second.source_identity, second.source_identity_form, "target"
                )
            return rows

        monkeypatch.setattr(store, "statement_coverage", concurrent_bind)
        loaded = store.statement_source_review_snapshot("target", evidence.source_sha256)
        monkeypatch.setattr(store, "statement_coverage", original)
        assert loaded.section.source_identity == loaded.source_account.source_identity == first.source_identity
        current = store.statement_source_review_snapshot("target", evidence.source_sha256)
        assert current.section.source_identity == second.source_identity and current.basis_sha256 != loaded.basis_sha256
        opening = store.opening_review_snapshot("target")
        assert (
            opening.sections[0].source_identity == second.source_identity
            and opening.source_review_basis_sha256 == current.basis_sha256
        )


def test_historical_source_value_retry_returns_old_withdrawn_receipt_without_reviving_it(tmp_path, samples):
    path = tmp_path / "source_retry.db"
    setup(path, samples)
    with V2ProfileStore.open(path) as store:
        frame = store.account_anchor_snapshot("target")
        candidate = frame.source_value_candidates[0]
        original = record_source(store)
        withdraw(store, original)
        fresh = record_source(store)
        receipt = store.record_reviewed_source_value(
            "target",
            candidate.candidate_id,
            expected_candidate_sha256=candidate.version,
            expected_basis_sha256=frame.basis_sha256,
            reference=original.reference,
            reason=original.reason,
        )
        assert receipt.value_id == original.value_id and receipt.state == "withdrawn"
        assert store.account_anchor_snapshot("target", as_of=AS_OF).latest_dated_value == fresh


def test_withdrawing_wrong_manual_point_removes_only_its_opening_date_boundary(tmp_path):
    path = tmp_path / "boundaries.db"
    with V2ProfileStore.create(path) as store:
        store.add_financial_account(FinancialAccount("target", "Synthetic cash", "asset", "synthetic"))
        wrong = manual(store, 100, date(2026, 1, 1))
        assert store.account_anchor_snapshot("target").earliest_known_history_date == date(2026, 1, 1)
        withdraw(store, wrong)
        frame = store.account_anchor_snapshot("target")
        assert frame.value_status == "missing" and frame.opening_boundaries == ()
        store.post_reviewed_manual_opening(
            "target",
            amount_minor=200,
            cutoff_date=date(2026, 1, 2),
            tracking_scope="account_total",
            reference="Earlier wrong value was retired",
            reason="Reviewed independent opening",
            expected_decision_version=None,
            expected_basis_sha256=frame.basis_sha256,
        )


@pytest.mark.parametrize("family", ["mohela-pilot-definition.json", "mohela-account-history-definition.json"])
def test_mohela_export_running_principal_is_never_admitted_as_statement_closing(tmp_path, samples, family):
    path = tmp_path / "export.db"
    content, definition, evidence, suffix = samples[family]
    with V2ProfileStore.create(path) as store:
        store.import_source(content, definition, evidence, suffix=suffix)
        store.add_financial_account(
            FinancialAccount(
                "target", "Synthetic principal", "liability", "synthetic", tracking_scope="principal_component"
            )
        )
        first = evidence.payload.rows[0]
        if first.source_account is None:
            store.assert_file_account(evidence.source_sha256, "target")
        else:
            store.bind_source_account(evidence.source_sha256, first.source_account, first.source_account_form, "target")
        frame = store.account_anchor_snapshot("target")
        assert frame.source_value_candidates == () and frame.dated_values == ()
        assert store.load_import(evidence.source_sha256).evidence == evidence
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)


@pytest.mark.parametrize(
    "field,value",
    [
        ("source_reference", b"broken reference"),
        ("note", b"broken note"),
        ("source_identity", b"broken identity"),
        ("created_at", b"broken timestamp"),
        ("source_identity", "unknown section"),
    ],
)
def test_malformed_source_review_history_refuses_before_version_hashing_even_without_values(
    tmp_path, samples, field, value
):
    path = tmp_path / "bad_review.db"
    evidence = setup(path, samples, "happen-savings-pilot-definition.json")
    with V2ProfileStore.open(path) as store:
        review_source(store, evidence.source_sha256)
    with sqlite3.connect(path) as connection:
        trigger = connection.execute(
            "SELECT sql FROM sqlite_master WHERE name='immutable_StatementSourceReviews_update'"
        ).fetchone()[0]
        connection.execute("DROP TRIGGER immutable_StatementSourceReviews_update")
        connection.execute(f"UPDATE StatementSourceReviews SET {field}=?", (value,))
        connection.execute(trigger)
    before = path.read_bytes()
    with V2ProfileStore.open(path, read_only=True) as store:
        for read in (lambda: store.source_dated_value_snapshot("target"), lambda: store.account_positions(as_of=AS_OF)):
            with pytest.raises(ProfileFormatError, match="statement_source_review_history_integrity"):
                read()
    with pytest.raises(ProfileFormatError, match="statement_source_review_history_integrity"):
        V2ProfileStore.snapshot_to(path, tmp_path / "refused.db")
    assert path.read_bytes() == before and not (tmp_path / "refused.db").exists()
