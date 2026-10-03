"""Persist the last displayed reconciliation snapshot outside immutable ledger evidence."""

import json
import os
import tempfile

from parsetrail.core.ledger import LedgerError
from parsetrail.core.ledger_opening_review import OpeningReview
from parsetrail.core.ledger_rebuild import key
from parsetrail.core.ledger_reviewed_reconciliation import RULE, ReviewedReconciliation
from parsetrail.core.ledger_store import encoded


class ReconciliationView:
    def __init__(self, review, folder):
        self.service = ReviewedReconciliation(review)
        self.path = folder / "reconciliation-view.json"
        self.report = None
        if self.path.exists():
            try:
                saved = json.loads(self.path.read_text(encoding="utf-8"))
                report = saved["report"]
                valid = (
                    saved["sha256"] == key(report)
                    and report["rule"] == RULE
                    and report["candidate_hash"] == key(review.plan)
                    and report["opening_plan_hash"] == key(OpeningReview(review).plan)
                )
            except (ValueError, KeyError, TypeError) as exc:
                raise LedgerError(
                    "Saved reconciliation view is malformed; preserve it before recreating the view."
                ) from exc
            if not valid:
                raise LedgerError("Saved reconciliation view changed or belongs to different evidence.")
            self.report = report

    def check(self):
        report = self.service.snapshot()
        payload = encoded({"report": report, "sha256": key(report)})
        descriptor, temporary = tempfile.mkstemp(prefix="reconciliation-view-", suffix=".tmp", dir=self.path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        self.report = report

    def is_current(self):
        return self.report is not None and self.service.is_current(self.report)
