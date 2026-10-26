"""Code-owned category identities; discovery never opens or changes a profile."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class BuiltinCategory:
    account_id: str
    name: str
    kind: Literal["expense", "income"]


BUILTIN_CATEGORIES = (BuiltinCategory("builtin:loan-interest", "Loan interest", "expense"),)


def is_builtin_id_reserved(account_id: str) -> bool:
    """Reserve future code-owned identities as well as today's catalog entries."""
    return account_id.startswith("builtin:")


def builtin_category(account_id: str) -> BuiltinCategory | None:
    return next((category for category in BUILTIN_CATEGORIES if category.account_id == account_id), None)


def category_labels(accounts: Iterable[tuple[str, str, str]]) -> dict[str, str]:
    """Keep fixed semantic identities distinct from custom matching names."""
    accounts = tuple(accounts)
    counts = Counter((name, kind) for _account_id, name, kind in accounts)
    builtin_names = {(category.name, category.kind) for category in BUILTIN_CATEGORIES}
    return {
        account_id: name
        + (
            ""
            if kind not in {"expense", "income"}
            else (
                " [Built-in]"
                if builtin_category(account_id) is not None
                else f" [Custom: {account_id}]"
                if counts[name, kind] > 1 or (name, kind) in builtin_names
                else ""
            )
        )
        for account_id, name, kind in accounts
    }
