from datetime import datetime
from decimal import Decimal
from pathlib import Path

from parsetrail.core.parser_classification import DocumentFeatures, matching_plugins, normalize_pdf_metadata
from parsetrail.core.plugin_loader import load_plugin
from parsetrail.plugins.pdf_happenbank_202606 import Parser as HappenParser
from parsetrail.plugins.pdf_lendingclubsavings_202601 import Parser as LendingClubParser


def test_legacy_layout_parses_undated_adjustments_and_interest() -> None:
    parser = LendingClubParser()
    parser.lines = [
        "************************* LevelUp Savings 1234560394 ***********************",
        "12/31 Balance Forward -------------------------------------> 4,052.75",
        "01/12 CITI CARD TRIAL ACCTVERIFY .12 4,052.87",
        "CITI CARD TRIAL ACCTVERIFY .12- 4,052.75",
        "Interest Paid 8.45 4,061.20",
        "Previous Statement Date: 12/31/25",
    ]

    start_balance, transactions = parser.extract_activity(
        datetime(2026, 1, 1),
        datetime(2026, 1, 30),
    )

    assert start_balance == Decimal("4052.75")
    assert [transaction.amount for transaction in transactions] == [
        Decimal("0.12"),
        Decimal("-0.12"),
        Decimal("8.45"),
    ]
    assert transactions[1].posting_date.isoformat() == "2026-01-12"
    assert transactions[2].posting_date.isoformat() == "2026-01-30"


def test_happen_layout_parses_deposits_withdrawals_and_interest() -> None:
    parser = HappenParser()
    parser.lines = [
        "Transactional Detail",
        "Date Description Deposits Withdrawals Balance",
        "07/01 Beginning Balance 10,624.56",
        "07/15 EXTERNAL TRANSFER FROM CHECKING 500.00 11,124.56",
        "07/20 EXTERNAL TRANSFER TO CHECKING 2,000.00- 9,124.56",
        "07/31 Interest Paid 28.83 9,153.39",
        "07/31 Ending Balance 9,153.39",
        "Overdraft/Return Item Summary",
    ]

    transactions = parser.extract_transactions(
        datetime(2026, 7, 1),
        datetime(2026, 7, 31),
    )

    assert [transaction.amount for transaction in transactions] == [
        Decimal("500.00"),
        Decimal("-2000.00"),
        Decimal("28.83"),
    ]


def test_savings_layouts_route_to_disjoint_plugins() -> None:
    plugin_dir = Path(__file__).parents[1] / "src" / "parsetrail" / "plugins"
    catalog = {}
    for plugin_name in ("pdf_lendingclubsavings_202601", "pdf_happenbank_202606"):
        plugin_id, _, metadata = load_plugin(plugin_dir / f"{plugin_name}.py")
        catalog[plugin_id] = metadata

    legacy = DocumentFeatures(
        suffix=".pdf",
        body_text="LevelUp Savings",
        header_text="Date_Description\nPrevious Statement Date:",
        pdf_metadata=normalize_pdf_metadata({"Creator": "ImageCentre Statements"}),
    )
    happen = DocumentFeatures(
        suffix=".pdf",
        body_text="LevelUp Savings",
        header_text="Summary of Accounts\nLevelUp Savings Account Number:",
        pdf_metadata=normalize_pdf_metadata({"Creator": "VCTransaction", "Title": "StmtAPISvc"}),
    )

    assert matching_plugins(legacy, catalog) == ("pdf_lendingclubsavings_202601",)
    assert matching_plugins(happen, catalog) == ("pdf_happenbank_202606",)
