"""Open a disposable signed 2.0 workspace with synthetic source evidence."""

from __future__ import annotations

import argparse
import tempfile
from datetime import date
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from parsetrail.core.v2_data_catalog import key_id_for_public_key
from parsetrail.core.v2_legacy_citi_lines import parse_legacy_citi
from parsetrail.core.v2_profile_store import FinancialAccount, V2ProfileStore
from parsetrail.core.v2_synchrony_source_output import from_synchrony_table
from parsetrail.core.v2_workspace import V2Workspace
from parsetrail.gui.v2_workspace_window import V2WorkspaceWindow
from PySide6.QtWidgets import QApplication
from scripts.v2_catalog_release import signed_catalog_bytes

from devtools.parser_engine_pilot.review_accountless_export import DEFINITION as MOHELA_DEFINITION
from devtools.parser_engine_pilot.review_accountless_export import SOURCE as MOHELA_SOURCE
from devtools.parser_engine_pilot.test_legacy_citi_lines import DEFINITION as CITI_DEFINITION
from devtools.parser_engine_pilot.test_legacy_citi_lines import lines as citi_lines
from devtools.parser_engine_pilot.test_synchrony_source_output import DEFINITION as CARD_DEFINITION
from devtools.parser_engine_pilot.test_synchrony_source_output import SOURCE as CARD_SOURCE
from devtools.parser_engine_pilot.test_synchrony_source_output import channels as card_channels

ROOT = Path(__file__).resolve().parents[2]
CASH_DEFINITION = ROOT / "devtools" / "v2_fresh_slice" / "synthetic-posted-cash-definition.json"
CASH_SOURCE = (
    b"Date,Account,Description,Amount,ReportedBalance\n"
    b"10/01/2026,Checking A,Coffee,-$4.00,$996.00\n"
    b"10/02/2026,Checking A,Deposit,$10.00,$1006.00\n"
    b"10/03/2026,Checking A,Tea,-$3.00,$1003.00\n"
)
MORE_CASH = b"Date,Account,Description,Amount,ReportedBalance\n10/02/2026,Checking A,Tea,-$3.00,$993.00\n"
CITI_SOURCE = b"%PDF-older-citi-synthetic"
CITI_OVERLAP_SOURCE = b"%PDF-older-citi-overlap-synthetic"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", required=True)
    parser.parse_args(argv)
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory(prefix="parsetrail-v2-workspace-") as temporary:
        root = Path(temporary)
        definitions = root / "definitions"
        definitions.mkdir()
        (definitions / MOHELA_DEFINITION.name).write_bytes(MOHELA_DEFINITION.read_bytes())
        (definitions / CASH_DEFINITION.name).write_bytes(CASH_DEFINITION.read_bytes())
        (definitions / "synchrony-card-definition.json").write_bytes(CARD_DEFINITION)
        (definitions / "older-citi-definition.json").write_bytes(CITI_DEFINITION)
        (definitions / "account-contexts.json").write_text(
            '{"synchrony_amazon_store_card":{"institution_key":"synchrony","kind":"liability"},'
            '"pdf_citicc_201505":{"institution_key":"citi","kind":"liability"}}'
        )
        private = Ed25519PrivateKey.generate()
        public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        snapshot, signature, _verified = signed_catalog_bytes(
            definitions, private, release_sequence=1, source_revision="a" * 40
        )
        workspace = V2Workspace.create(
            root / "demo.db",
            root / "catalog",
            trusted_keys={key_id_for_public_key(public): public},
            preferences_path=root / "preferences.json",
        )
        first_release = root / "signed-release-1"
        first_release.mkdir()
        (first_release / "catalog.json").write_bytes(snapshot)
        (first_release / "catalog.sig").write_bytes(signature)
        workspace.install_catalog_release(first_release)
        next_snapshot, next_signature, _next_verified = signed_catalog_bytes(
            definitions, private, release_sequence=2, source_revision="a" * 40
        )
        next_release = root / "signed-release-2"
        next_release.mkdir()
        (next_release / "catalog.json").write_bytes(next_snapshot)
        (next_release / "catalog.sig").write_bytes(next_signature)
        mohela_path = root / "mohela.csv"
        mohela_path.write_bytes(MOHELA_SOURCE)
        cash_path = root / "cash.csv"
        cash_path.write_bytes(CASH_SOURCE)
        more_path = root / "import-this.csv"
        more_path.write_bytes(MORE_CASH)
        workspace.import_file(mohela_path)
        cash_result = workspace.import_file(cash_path)
        with V2ProfileStore.open(workspace.profile_path) as store:
            citi_evidence = parse_legacy_citi(
                CITI_DEFINITION,
                citi_lines(extra=("Offer balance $2.34",), source=CITI_SOURCE),
            )
            store.import_source(
                CITI_SOURCE,
                CITI_DEFINITION,
                citi_evidence,
                suffix=".pdf",
            )
            citi_overlap = parse_legacy_citi(
                CITI_DEFINITION,
                citi_lines(source=CITI_OVERLAP_SOURCE),
            )
            store.import_source(
                CITI_OVERLAP_SOURCE,
                CITI_DEFINITION,
                citi_overlap,
                suffix=".pdf",
            )
            store.import_source(
                CARD_SOURCE,
                CARD_DEFINITION,
                from_synchrony_table(CARD_DEFINITION, *card_channels()),
                suffix=".pdf",
            )
            store.add_financial_account(FinancialAccount("loan-a", "Loan A", "liability", "mohela"))
            store.add_financial_account(FinancialAccount("loan-b", "Loan B", "liability", "mohela"))
            store.add_financial_account(FinancialAccount("checking-a", "Checking A", "asset", "synthetic"))
            store.add_financial_account(FinancialAccount("card-a", "Card A", "liability", "synchrony", "999991234"))
            store.add_financial_account(FinancialAccount("citi-card", "Citi Card", "liability", "citi"))
            store.add_category_account("category:food", "Food", "expense")
            store.add_category_account("category:travel", "Travel", "expense")
            store.set_category_budget_rate("category:food", date(2026, 10, 1), 10_000)
            for evidence in (citi_evidence, citi_overlap):
                account = evidence.payload.accounts[0]
                store.bind_source_account(
                    evidence.source_sha256, account.source_identity, account.source_identity_form, "citi-card"
                )
        window = V2WorkspaceWindow(workspace)
        window.refresh(select_source=cash_result.source_sha256)
        window.status.setWordWrap(True)
        window.status.setText(
            "Disposable demo. Selected cash export: bind Checking A to its asset account under "
            "Review source accounts, then open Review cash expenses. Post Coffee to Food; "
            "correct it to Travel. Deposit stays pending. "
            "Select the card source to review its last-four match. "
            "Older Citi sources: inspect the period-overlap warning; one source previews an unclassified dollar line. "
            "Categories: rename Food, add a category, or change Food's October $100 target. "
            f"Import source: {more_path}\nInstall signed catalog: {next_release}"
        )
        window.show()
        return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
