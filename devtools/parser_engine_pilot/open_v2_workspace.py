"""Open a disposable signed 2.0 workspace with synthetic source evidence."""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from parsetrail.core.v2_data_catalog import key_id_for_public_key
from parsetrail.core.v2_profile_store import FinancialAccount, V2ProfileStore
from parsetrail.core.v2_synchrony_source_output import from_synchrony_table
from parsetrail.core.v2_workspace import V2Workspace
from parsetrail.gui.v2_workspace_window import V2WorkspaceWindow
from PySide6.QtWidgets import QApplication
from scripts.v2_catalog_release import signed_catalog_bytes

from devtools.parser_engine_pilot.review_accountless_export import DEFINITION as MOHELA_DEFINITION
from devtools.parser_engine_pilot.review_accountless_export import SOURCE as MOHELA_SOURCE
from devtools.parser_engine_pilot.test_synchrony_source_output import DEFINITION as CARD_DEFINITION
from devtools.parser_engine_pilot.test_synchrony_source_output import SOURCE as CARD_SOURCE
from devtools.parser_engine_pilot.test_synchrony_source_output import channels as card_channels

ROOT = Path(__file__).resolve().parents[2]
CASH_DEFINITION = ROOT / "devtools" / "v2_fresh_slice" / "synthetic-posted-cash-definition.json"
CASH_SOURCE = b"Date,Account,Description,Amount,ReportedBalance\n10/01/2026,Checking A,Coffee,-$4.00,$996.00\n"
MORE_CASH = b"Date,Account,Description,Amount,ReportedBalance\n10/02/2026,Checking A,Tea,-$3.00,$993.00\n"


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
        (definitions / "account-contexts.json").write_text(
            '{"synchrony_amazon_store_card":{"institution_key":"synchrony","kind":"liability"}}'
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
        workspace.import_file(cash_path)
        with V2ProfileStore.open(workspace.profile_path) as store:
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
        window = V2WorkspaceWindow(workspace)
        window.status.setWordWrap(True)
        window.status.setText(
            "Disposable demo. First source: review its last-four match and inline preference. "
            f"Import source: {more_path}\nInstall signed catalog: {next_release}"
        )
        window.show()
        return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
