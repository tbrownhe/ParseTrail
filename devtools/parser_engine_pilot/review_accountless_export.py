"""Open a disposable six-row 2.0 account assignment review demo."""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from parsetrail.core.v2_profile_store import FinancialAccount, V2ProfileStore
from parsetrail.core.v2_source_pipeline import build_source_evidence
from parsetrail.gui.v2_account_binding_review import review_accountless_export
from PySide6.QtWidgets import QApplication

DEFINITION = Path(__file__).with_name("mohela-account-history-definition.json")
SOURCE = (
    b'<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.0 Transitional//EN">'
    b"Date,Description,Principal,Interest,Fees,Total,\n"
    b"10/01/2026,Payment,-$80.00,-$20.00,$0.00,-$100.00,\n"
    b"10/04/2026,Payment,-$60.00,-$15.00,$0.00,-$75.00,\n"
    b"10/08/2026,Payment,-$40.00,-$10.00,$0.00,-$50.00,\n"
    b"10/12/2026,Payment,-$96.00,-$24.00,$0.00,-$120.00,\n"
    b"10/16/2026,Payment,-$48.00,-$12.00,$0.00,-$60.00,\n"
    b"10/20/2026,Payment,-$72.00,-$18.00,$0.00,-$90.00,\n"
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", help="Open a disposable synthetic profile")
    args = parser.parse_args(argv)
    if not args.demo:
        parser.error("--demo is required")
    definition = DEFINITION.read_bytes()
    evidence = build_source_evidence(SOURCE, definition, suffix=".csv")
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory(prefix="parsetrail-v2-account-review-") as temporary:
        profile = Path(temporary) / "demo.db"
        with V2ProfileStore.create(profile) as store:
            store.import_source(SOURCE, definition, evidence, suffix=".csv")
            store.add_financial_account(FinancialAccount("loan-a", "Loan A", "liability", "mohela"))
            store.add_financial_account(FinancialAccount("loan-b", "Loan B", "liability", "mohela"))
        dialog = review_accountless_export(profile, evidence.source_sha256)
        dialog.exec()
        app.processEvents()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
