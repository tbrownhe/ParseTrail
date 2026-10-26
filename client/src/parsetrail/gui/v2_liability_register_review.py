"""Finite account-total liability register review with fixed source posting dates."""

from __future__ import annotations

from parsetrail.gui.v2_card_purchase_review import V2CardPurchaseReview


class V2LiabilityRegisterReview(V2CardPurchaseReview):
    """Reuse ordinary liability mechanics without asserting a card or component split."""

    def __init__(self, workspace, source_sha256: str, parent=None):
        super().__init__(workspace, source_sha256, parent, register_mode=True)
