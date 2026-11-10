"""Explicit managed institution setup for synthetic account fixtures only."""

from parsetrail.core.v2_institutions import Institution, institution_label


def register_test_institutions(store, *keys):
    """Declare synthetic institutions in a disposable fixture before accounts."""
    existing = {institution.id for institution in store.institutions()}
    for key in keys:
        if key is not None and key not in existing:
            store.register_institution(Institution(key, institution_label(key)))
            existing.add(key)


def add_test_financial_account(store, account):
    """Explicit fixture factory: register its named institution, then the account.

    This never patches production account validation. Tests of unknown or invalid
    institution refusal must call the production method directly instead.
    """
    register_test_institutions(store, account.institution_key)
    store.add_financial_account(account)
