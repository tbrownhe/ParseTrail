"""Open repeated-row review over a disposable synthetic V2 profile."""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from parsetrail.core.v2_profile_store import FinancialAccount, V2ProfileStore
from parsetrail.core.v2_source_pipeline import build_source_evidence

DEFINITION = (
    Path(__file__).resolve().parents[2] / "devtools/v2_fresh_slice/synthetic-posted-cash-definition.json"
).read_bytes()
SOURCES = (
    b"Date,Account,Description,Amount,ReportedBalance\n"
    b"10/01/2026,Checking A,Coffee,-$4.00,$996.00\n"
    b"10/01/2026,Checking A,Coffee,-$4.00,$992.00\n"
    b"10/02/2026,Checking A,Deposit,$10.00,$1002.00\n",
    b"Date,Account,Description,Amount,ReportedBalance\n"
    b"10/01/2026,Checking A,Coffee shop,-$4.00,$996.00\n"
    b"10/03/2026,Checking A,Deposit,$10.00,$1006.00\n",
)


def prepare_demo(profile: Path) -> None:
    """Create a new profile with two equal occurrences versus one candidate."""
    with V2ProfileStore.create(profile) as store:
        store.add_financial_account(FinancialAccount("cash", "Synthetic checking", "asset", "synthetic"))
        store.add_category_account("expense:food", "Food", "expense")
        for source in SOURCES:
            evidence = build_source_evidence(source, DEFINITION, suffix=".csv")
            store.import_source(source, DEFINITION, evidence, suffix=".csv")
            store.bind_source_account(evidence.source_sha256, "Checking A", "opaque", "cash")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", required=True, action="store_true")
    parser.parse_args(argv)
    from parsetrail.gui.v2_source_overlap_review import V2SourceOverlapReview
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory(prefix="parsetrail-overlap-demo-") as temporary:
        profile = Path(temporary) / "demo.db"
        prepare_demo(profile)
        dialog = V2SourceOverlapReview(profile)
        dialog.show()
        return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
