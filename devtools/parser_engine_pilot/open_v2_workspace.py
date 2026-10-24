"""Open a disposable signed 2.0 workspace with synthetic source evidence."""

from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from parsetrail.core.v2_data_catalog import key_id_for_public_key
from parsetrail.core.v2_profile_store import FinancialAccount, V2ProfileStore
from parsetrail.core.v2_workspace import V2Workspace
from parsetrail.gui.v2_workspace_window import V2WorkspaceWindow
from PySide6.QtWidgets import QApplication
from scripts.v2_catalog_release import signed_catalog_bytes

from devtools.parser_engine_pilot.review_accountless_export import DEFINITION as MOHELA_DEFINITION
from devtools.parser_engine_pilot.review_accountless_export import SOURCE as MOHELA_SOURCE

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
        private = Ed25519PrivateKey.generate()
        public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        snapshot, signature, _verified = signed_catalog_bytes(
            definitions, private, release_sequence=1, source_revision="a" * 40
        )
        workspace = V2Workspace.create(
            root / "demo.db", root / "catalog", trusted_keys={key_id_for_public_key(public): public}
        )
        workspace.catalog_cache.activate(snapshot, signature)
        mohela_path = root / "mohela.csv"
        mohela_path.write_bytes(MOHELA_SOURCE)
        cash_path = root / "cash.csv"
        cash_path.write_bytes(CASH_SOURCE)
        more_path = root / "import-this.csv"
        more_path.write_bytes(MORE_CASH)
        workspace.import_file(mohela_path)
        workspace.import_file(cash_path)
        with V2ProfileStore.open(workspace.profile_path) as store:
            store.add_financial_account(FinancialAccount("loan-a", "Loan A", "liability", "mohela"))
            store.add_financial_account(FinancialAccount("loan-b", "Loan B", "liability", "mohela"))
        window = V2WorkspaceWindow(workspace)
        window.status.setText(f"Disposable demo. To try Import source, choose {more_path}")
        window.show()
        return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
