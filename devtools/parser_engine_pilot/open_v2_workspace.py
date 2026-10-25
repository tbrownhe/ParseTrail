"""Open a disposable signed 2.0 workspace with synthetic source evidence."""

from __future__ import annotations

import argparse
import hashlib
import tempfile
from dataclasses import replace
from datetime import date
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from parsetrail.core.v2_citi_source_output import from_citi
from parsetrail.core.v2_data_catalog import key_id_for_public_key
from parsetrail.core.v2_legacy_citi_lines import parse_legacy_citi
from parsetrail.core.v2_profile_store import FinancialAccount, V2ProfileStore
from parsetrail.core.v2_synchrony_source_output import from_synchrony_table
from parsetrail.core.v2_table_bank_source_output import from_anchored_bank
from parsetrail.core.v2_workspace import V2Workspace
from parsetrail.gui.v2_statement_coverage import V2StatementCoverageDialog
from parsetrail.gui.v2_workspace_window import V2WorkspaceWindow
from PySide6.QtWidgets import QApplication, QFormLayout, QLineEdit, QTabWidget
from scripts.v2_catalog_release import signed_catalog_bytes

from devtools.parser_engine_pilot.citi_authoring import DEFINITION_BYTES as RECENT_CITI_DEFINITION
from devtools.parser_engine_pilot.review_accountless_export import DEFINITION as MOHELA_DEFINITION
from devtools.parser_engine_pilot.review_accountless_export import SOURCE as MOHELA_SOURCE
from devtools.parser_engine_pilot.test_citi_source_output import sample as recent_citi_sample
from devtools.parser_engine_pilot.test_legacy_citi_lines import DEFINITION as CITI_DEFINITION
from devtools.parser_engine_pilot.test_legacy_citi_lines import lines as citi_lines
from devtools.parser_engine_pilot.test_synchrony_source_output import DEFINITION as CARD_DEFINITION
from devtools.parser_engine_pilot.test_synchrony_source_output import SOURCE as CARD_SOURCE
from devtools.parser_engine_pilot.test_synchrony_source_output import channels as card_channels
from devtools.parser_engine_pilot.test_table_bank_source_output import SOURCE as BANK_SOURCE
from devtools.parser_engine_pilot.test_table_bank_source_output import TAIL_DEFINITION as BANK_DEFINITION
from devtools.parser_engine_pilot.test_table_bank_source_output import evidence as bank_channels

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
RECENT_CITI_SOURCE = b"%PDF-recent-citi-synthetic"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", required=True)
    parser.add_argument("--comparison", action="store_true", help="Open a prefilled statement journal comparison")
    args = parser.parse_args(argv)
    app = QApplication.instance() or QApplication([])
    with tempfile.TemporaryDirectory(prefix="parsetrail-v2-workspace-") as temporary:
        root = Path(temporary)
        definitions = root / "definitions"
        definitions.mkdir()
        (definitions / MOHELA_DEFINITION.name).write_bytes(MOHELA_DEFINITION.read_bytes())
        (definitions / CASH_DEFINITION.name).write_bytes(CASH_DEFINITION.read_bytes())
        (definitions / "synchrony-card-definition.json").write_bytes(CARD_DEFINITION)
        (definitions / "older-citi-definition.json").write_bytes(CITI_DEFINITION)
        (definitions / "recent-citi-definition.json").write_bytes(RECENT_CITI_DEFINITION)
        (definitions / "lendingclub-table-definition.json").write_bytes(BANK_DEFINITION)
        (definitions / "account-contexts.json").write_text(
            '{"synchrony_amazon_store_card":{"institution_key":"synchrony","kind":"liability"},'
            '"pdf_citicc_201505":{"institution_key":"citi","kind":"liability"},'
            '"pdf_lendingclublus_202506":{"institution_key":"lendingclub","kind":"asset"}}'
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
            recent = recent_citi_sample()
            recent = replace(
                recent,
                source_sha256=hashlib.sha256(RECENT_CITI_SOURCE).hexdigest(),
                simple_text_pages=("01/02 01/02 SHOP $10.00\nGeneral notice",),
                table_evidence=replace(
                    recent.table_evidence,
                    source_sha256=hashlib.sha256(RECENT_CITI_SOURCE).hexdigest(),
                ),
            )
            store.import_source(
                RECENT_CITI_SOURCE,
                RECENT_CITI_DEFINITION,
                from_citi(recent, RECENT_CITI_DEFINITION),
                suffix=".pdf",
            )
            card_evidence = from_synchrony_table(CARD_DEFINITION, *card_channels())
            store.import_source(CARD_SOURCE, CARD_DEFINITION, card_evidence, suffix=".pdf")
            bank_evidence = from_anchored_bank(BANK_DEFINITION, *bank_channels(definition=BANK_DEFINITION, tail=True))
            store.import_source(BANK_SOURCE, BANK_DEFINITION, bank_evidence, suffix=".pdf")
            store.add_financial_account(FinancialAccount("loan-a", "Loan A", "liability", "mohela"))
            store.add_financial_account(FinancialAccount("loan-b", "Loan B", "liability", "mohela"))
            store.add_financial_account(FinancialAccount("checking-a", "Checking A", "asset", "synthetic"))
            store.add_financial_account(FinancialAccount("savings-a", "Savings A", "asset", "lendingclub"))
            store.add_financial_account(FinancialAccount("card-a", "Card A", "liability", "synchrony", "999991234"))
            store.add_financial_account(FinancialAccount("citi-card", "Citi Card", "liability", "citi"))
            store.add_category_account("category:food", "Food", "expense")
            store.add_category_account("category:travel", "Travel", "expense")
            store.add_category_account("category:cash-income", "Demo income", "income")
            store.add_category_account("category:other-income", "Other income", "income")
            store.set_category_budget_rate("category:food", date(2026, 10, 1), 10_000)
            if args.comparison:
                bank_account = bank_evidence.payload.accounts[0]
                store.bind_source_account(
                    bank_evidence.source_sha256,
                    bank_account.source_identity,
                    bank_account.source_identity_form,
                    "savings-a",
                )
                store.record_statement_source_review(
                    "savings-a",
                    bank_evidence.source_sha256,
                    expected_revision_id=None,
                    opening_origin="reported",
                    closing_origin="reported",
                    timing_confirmed=True,
                    posting_dates="reported",
                    source_reference="Disposable synthetic statement summary and activity table",
                )
                store.post_reviewed_opening("savings-a")
                interest, withdrawal = bank_account.rows
                store.post_reviewed_cash_category(
                    interest.row_id, "category:cash-income", reason="Disposable reviewed interest"
                )
                store.post_reviewed_cash_category(
                    withdrawal.row_id, "category:travel", reason="Disposable reviewed withdrawal"
                )
                card_account = card_evidence.payload.accounts[0]
                store.bind_source_account(
                    card_evidence.source_sha256,
                    card_account.source_identity,
                    card_account.source_identity_form,
                    "card-a",
                )
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
            "Review source accounts, then open Review cash activity. Post Coffee to Food; "
            "correct it to Travel. Deposit remains pending unless you explicitly classify it as income; "
            "the demo offers two income categories for that review. "
            "Select the card source to review its last-four match. "
            "Older Citi sources: inspect the period-overlap warning; one source previews an unclassified dollar line. "
            "Recent Citi source: Preview evidence > Unclassified page text shows its General notice. "
            "Import folder selects only CSV/PDF files immediately in this temporary folder. "
            "Statement coverage shows the explicitly bound older Citi overlap without claiming reconciliation. "
            "Its Printed openings tab shows read-only earliest source candidates and timing blockers. "
            "Categories: rename Food, add a category, or change Food's October $100 target. "
            "Reviewed reports > Monthly budgets: October shows Food's $100 target and reviewed Coffee spending. "
            "Reviewed reports > Income: after explicitly posting the synthetic Deposit, October shows $10 income. "
            "Select the LendingClub bank statement, bind its printed account to Savings A, then review "
            "its interest and withdrawal separately. "
            "Profile menu: back up this disposable profile, restore to a new .db, then reopen the original. "
        )
        demo_paths = QFormLayout()
        for label, path in (
            ("Import source:", more_path),
            ("Import folder:", root),
            ("Install signed catalog:", next_release),
        ):
            path_field = QLineEdit(str(path))
            path_field.setReadOnly(True)
            path_field.setCursorPosition(0)
            demo_paths.addRow(label, path_field)
        window.centralWidget().layout().addLayout(demo_paths)
        window.show()
        if args.comparison:
            window.status.setText(
                "Disposable statement check: Savings A has reviewed source, opening and movements; "
                "Card A remains pending. The separate Statement coverage window is open on Reconciliation check. "
                "In Saved periods, select Savings A or Card A and click Review selected source to inspect provenance."
            )
            comparison = V2StatementCoverageDialog(workspace.profile_path, window)
            comparison.findChild(QTabWidget).setCurrentIndex(3)
            comparison.show()
            window._comparison_preview = comparison
        return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
