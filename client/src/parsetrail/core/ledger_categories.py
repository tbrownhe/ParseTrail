"""Stable built-in ledger categories alongside retained user-defined categories.

Built-ins are a code-owned catalog, never inferred from an editable display name.
User category IDs remain integers; built-ins use a separate semantic namespace.
Ledger mappings are installed by posting transactions, not by reading this catalog.
"""

import json
from types import MappingProxyType

from parsetrail.core.ledger import AccountKind, LedgerAccount

LOAN_INTEREST_KEY = "builtin:loan-interest"
LOAN_INTEREST = LedgerAccount(f"category:{LOAN_INTEREST_KEY}", "Loan interest", AccountKind.EXPENSE)
BUILTIN_CATEGORIES = MappingProxyType({LOAN_INTEREST_KEY: LOAN_INTEREST})


def category_accounts(store, *, kind=None):
    """Return a fresh catalog; custom names cannot override built-in identity/type."""
    result = dict(BUILTIN_CATEGORIES)
    for cid, payload in store.connection.execute("SELECT id,payload FROM CategoryDefinitions"):
        row = json.loads(payload)
        if row["Type"] in {"Expense", "Income"}:
            result[cid] = LedgerAccount(f"category:{cid}", row["Name"], AccountKind(row["Type"].lower()))
    return {cid: account for cid, account in result.items() if kind is None or account.kind == kind}
