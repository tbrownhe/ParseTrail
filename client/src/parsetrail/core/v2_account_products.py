"""Managed account products, independent of source identity and interpretation."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AccountProduct:
    id: str
    label: str
    kind: str
    tracking_scopes: tuple[str, ...]


ACCOUNT_PRODUCTS = (
    AccountProduct("checking", "Checking account", "asset", ("account_total",)),
    AccountProduct("savings", "Savings account", "asset", ("account_total",)),
    AccountProduct("credit_card", "Credit card", "liability", ("account_total",)),
    AccountProduct("loan", "Loan", "liability", ("account_total", "principal_component")),
    AccountProduct("hsa", "Health savings account", "asset", ("account_total", "cash_component")),
    AccountProduct("investment", "Investment account", "asset", ("account_total", "cash_component")),
    AccountProduct("cash", "Other cash account", "asset", ("account_total",)),
    AccountProduct("tangible_asset", "Tangible asset", "asset", ("account_total",)),
)
_PRODUCTS = {product.id: product for product in ACCOUNT_PRODUCTS}


def account_product(product_type: str) -> AccountProduct:
    if type(product_type) is not str or product_type not in _PRODUCTS:
        raise ValueError("account_product_invalid")
    return _PRODUCTS[product_type]


def validate_product_type(product_type: str | None, kind: str, tracking_scope: str) -> None:
    """Unknown remains unknown; a selected product must agree with ledger scope."""
    if product_type is None:
        return
    product = account_product(product_type)
    if product.kind != kind or tracking_scope not in product.tracking_scopes:
        raise ValueError("account_product_incompatible")


@dataclass(frozen=True, slots=True)
class AccountProductProfile:
    """A supported format association, never proof of a source's origin."""

    institution_key: str | None
    product_type: str
    tracking_scope: str

    def __post_init__(self):
        if self.institution_key is not None and (
            type(self.institution_key) is not str
            or re.fullmatch(r"[a-z][a-z0-9_-]{2,79}", self.institution_key) is None
        ):
            raise ValueError("account_product_institution_invalid")
        product = account_product(self.product_type)
        validate_product_type(self.product_type, product.kind, self.tracking_scope)

    @property
    def kind(self) -> str:
        return account_product(self.product_type).kind
