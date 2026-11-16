"""Nonposting row decisions and immutable PDF-import account identity provenance."""

from __future__ import annotations

from dataclasses import dataclass

from parsetrail.core.v2_loan_payments import digest
from parsetrail.core.v2_resolution import error, now, reason_text


@dataclass(frozen=True)
class AccountIdentityLock:
    account_id: str
    source_sha256: str
    institution_key: str | None
    product_type: str | None


@dataclass(frozen=True)
class ZeroReview:
    revision_id: int
    row_id: str
    source_sha256: str
    account_id: str
    category_id: str
    purpose: str
    prior_revision_id: int | None
    action: str
    reason: str
    request_basis: str
    version: str
    created_at: str


@dataclass(frozen=True)
class ZeroReviewDraft:
    row_id: str
    source_sha256: str
    account_id: str
    category_id: str
    purpose: str
    prior_revision_id: int | None = None
    action: str = "reviewed"


def identity_locks(store):
    result = []
    for saved in store.connection.execute("SELECT * FROM AccountImportOrigins ORDER BY account_id"):
        account, source, institution, product, checksum = saved
        if checksum != digest(list(saved[:-1])):
            raise error("account_identity_origin_integrity")
        imported = store.load_import(source)
        if imported.suffix != ".pdf" or store.connection.execute(
            "SELECT institution_key,product_type FROM Accounts WHERE id=? AND role='financial'", (account,)
        ).fetchone() != (institution, product):
            raise error("account_identity_origin_integrity")
        # The record means 'chosen during PDF import', not 'every field printed'.
        if not store.connection.execute(
            "SELECT 1 FROM SourceAccountBindings WHERE source_sha256=? AND ledger_account_id=?", (source, account)
        ).fetchone():
            # A reviewed re-assignment retains the old creation provenance.
            if not store.connection.execute(
                "SELECT 1 FROM BindingCorrections WHERE source_sha256=?", (source,)
            ).fetchone():
                raise error("account_identity_origin_integrity")
        result.append(AccountIdentityLock(account, source, institution, product))
    return tuple(result)


def lock_pdf_account(store, account_id, source_sha256):
    store._require_writable()
    imported = store.load_import(source_sha256)
    values = store.connection.execute(
        "SELECT institution_key,product_type FROM Accounts WHERE id=? AND role='financial'", (account_id,)
    ).fetchone()
    if (
        imported.suffix != ".pdf"
        or values is None
        or not any(binding.ledger_account_id == account_id for binding in store.account_bindings(source_sha256))
    ):
        raise error("account_identity_origin_requires_bound_pdf")
    record = (account_id, source_sha256, *values)
    prior = store.connection.execute("SELECT * FROM AccountImportOrigins WHERE account_id=?", (account_id,)).fetchone()
    if prior is not None:
        if prior != (*record, digest(list(record))):
            raise error("account_identity_origin_conflict")
        return AccountIdentityLock(*record)
    store.connection.execute("INSERT INTO AccountImportOrigins VALUES (?,?,?,?,?)", (*record, digest(list(record))))
    return AccountIdentityLock(*record)


def zero_source(store, row_id, *, active=True):
    from parsetrail.core.v2_cash_source_policy import cash_tracking_scope
    from parsetrail.core.v2_liability_register import register_review_scopes
    from parsetrail.core.v2_profile_store import _card_review_scopes, _cash_review_scopes, _rows

    source = store.connection.execute(
        "SELECT source_sha256,row_role,date_role,observed_date,amount_minor FROM SourceObservations WHERE row_id=?",
        (row_id,),
    ).fetchone()
    if source is None:
        raise error("zero_review_source_unavailable")
    saved = store.load_import(source[0])
    row = next((row for row in _rows(saved.evidence) if row.row_id == row_id), None)
    cash, card = (
        _cash_review_scopes(saved.evidence),
        {**_card_review_scopes(saved.evidence), **register_review_scopes(saved.evidence)},
    )
    if (
        row is None
        or row.row_role != "activity"
        or row.amount.minor != 0
        or row.amount.provenance != "observed"
        or row.components
        or not (cash.get(row_id, False) or card.get(row_id, False))
        or source[1:] != (row.row_role, row.date_role, row.date.iso, 0)
    ):
        raise error("zero_review_source_unavailable")
    bindings = {binding.row_id: binding.ledger_account_id for binding in store.account_bindings(source[0])}
    account = bindings.get(row_id)
    if active and account is None:
        raise error("zero_review_account_required")
    if active:
        financial = store.connection.execute(
            "SELECT kind,role,tracking_scope,product_type FROM Accounts WHERE id=?", (account,)
        ).fetchone()
        expected = (
            ("asset", "financial", cash_tracking_scope(saved.evidence.parser_id))
            if cash.get(row_id, False)
            else ("liability", "financial", "account_total")
        )
        if financial is None or financial[:3] != expected or financial[3] == "vehicle":
            raise error("zero_review_account_scope_unsupported")
    return source[0], row, account


def zero_history(store, row_id=None):
    from parsetrail.core.v2_profile_store import CATEGORY_PURPOSE_KINDS

    result, latest = [], {}
    for saved in store.connection.execute("SELECT * FROM ZeroAmountReviews ORDER BY revision_id"):
        number, row, source, account, category, purpose, prior, action, reason, basis, version, created = saved
        if (
            type(number) is not int
            or number <= 0
            or reason != reason_text(reason)
            or purpose not in CATEGORY_PURPOSE_KINDS
            or action not in {"reviewed", "withdrawn"}
            or version != digest(list(saved[:-2]) + [created])
            or prior != (latest[row].revision_id if row in latest else None)
            or (action == "withdrawn" and (row not in latest or latest[row].action != "reviewed"))
            or store.connection.execute("SELECT kind,role FROM Accounts WHERE id=?", (category,)).fetchone()
            != (CATEGORY_PURPOSE_KINDS[purpose], "category")
        ):
            raise error("zero_review_history_integrity")
        actual_source, _evidence, _binding = zero_source(store, row, active=False)
        if (
            actual_source != source
            or store.connection.execute("SELECT 1 FROM Accounts WHERE id=? AND role='financial'", (account,)).fetchone()
            is None
        ):
            raise error("zero_review_history_integrity")
        review = ZeroReview(*saved)
        if action == "withdrawn" and (source, account, category, purpose) != (
            latest[row].source_sha256,
            latest[row].account_id,
            latest[row].category_id,
            latest[row].purpose,
        ):
            raise error("zero_review_history_integrity")
        latest[row] = review
        if row_id is None or row == row_id:
            result.append(review)
    for review in latest.values():
        if review.action == "reviewed" and zero_source(store, review.row_id)[2] != review.account_id:
            raise error("zero_review_history_integrity")
    return tuple(result)


def zero_draft(store, row_id, category_id, purpose, *, expected_revision_id=None, action="reviewed"):
    from parsetrail.core.v2_profile_store import CATEGORY_PURPOSE_KINDS

    source, _row, account = zero_source(store, row_id)
    history = zero_history(store, row_id)
    prior = history[-1] if history else None
    if expected_revision_id != (prior.revision_id if prior else None) or (
        action == "withdrawn" and (prior is None or prior.action != "reviewed")
    ):
        raise error("zero_review_changed_since_selection")
    if action == "withdrawn":
        category_id, purpose = prior.category_id, prior.purpose
    if purpose not in CATEGORY_PURPOSE_KINDS:
        raise error("zero_review_category_invalid")
    from parsetrail.core.v2_builtin_categories import builtin_category

    category = store.connection.execute("SELECT kind,role FROM Accounts WHERE id=?", (category_id,)).fetchone()
    builtin = builtin_category(category_id)
    if category is None and builtin:
        category = (builtin.kind, "category")
    if category != (CATEGORY_PURPOSE_KINDS[purpose], "category"):
        raise error("zero_review_category_invalid")
    return ZeroReviewDraft(row_id, source, account, category_id, purpose, expected_revision_id, action)


def insert_zero(store, draft, *, reason, basis):
    reason = reason_text(reason)
    store._category_for_posting(draft.category_id)
    number = store.connection.execute("SELECT COALESCE(MAX(revision_id),0)+1 FROM ZeroAmountReviews").fetchone()[0]
    created = now(store)
    values = (
        number,
        draft.row_id,
        draft.source_sha256,
        draft.account_id,
        draft.category_id,
        draft.purpose,
        draft.prior_revision_id,
        draft.action,
        reason,
        basis,
    )
    store.connection.execute(
        "INSERT INTO ZeroAmountReviews VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (*values, digest([*values, created]), created)
    )
    return number


def write_zero(
    store, row_id, category_id, purpose, *, reason, expected_basis_sha256, expected_revision_id=None, action="reviewed"
):
    reason = reason_text(reason)
    store._require_writable()
    if store.connection.in_transaction:
        raise error("zero_review_requires_committed_snapshot")
    store.connection.execute("BEGIN IMMEDIATE")
    try:
        history = zero_history(store, row_id)
        latest = history[-1] if history else None
        if (
            latest
            and latest.prior_revision_id == expected_revision_id
            and latest.request_basis == expected_basis_sha256
            and latest.reason == reason
            and latest.action == action
            and (action == "withdrawn" or (latest.category_id, latest.purpose) == (category_id, purpose))
        ):
            store.connection.execute("COMMIT")
            return latest
        store._require_source_interpretation_basis(expected_basis_sha256, required=True)
        draft = zero_draft(
            store, row_id, category_id, purpose, expected_revision_id=expected_revision_id, action=action
        )
        insert_zero(store, draft, reason=reason, basis=expected_basis_sha256)
        result = zero_history(store, row_id)[-1]
        store.connection.execute("COMMIT")
        return result
    except BaseException:
        store.connection.execute("ROLLBACK")
        raise
