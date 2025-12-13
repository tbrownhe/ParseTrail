"""
Generate a synthetic ParseTrail SQLite database for demos and screenshots.

Usage:
    python -m devtools.synthetic.generate_db --output synthetic.parsetrail.db --years 3 --seed 42
"""

from __future__ import annotations

import argparse
import hashlib
import random
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

# Ensure client sources are importable when run from repo root
ROOT = Path(__file__).resolve().parents[2]
CLIENT_SRC = ROOT / "client" / "src"
sys.path.insert(0, str(CLIENT_SRC))

try:
    from parsetrail.core import orm  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    raise


@dataclass
class AccountSpec:
    name: str
    company: str
    type_name: str
    asset_type: str
    account_number: str
    starting_balance: float
    income_monthly: float = 0.0
    expense_bias: float = 1.0  # >1 => heavier spending
    investment: bool = False
    volatility: float = 0.002  # daily stddev for drift (% of balance)
    drift_bias: float = 0.0  # daily mean drift (% of balance)
    drift_cap_multiplier: float = 0.005  # cap as % of balance
    drift_cap_abs: float = 500.0  # minimum/maximum absolute cap for drift
    spend_min: float = 20.0
    spend_max: float = 500.0
    spend_events_per_day: float = 1.0


CATEGORIES = [
    ("Salary", "Income"),
    ("Bonus", "Income"),
    ("Rent", "Housing"),
    ("Mortgage", "Housing"),
    ("Groceries", "Living"),
    ("Dining", "Living"),
    ("Utilities", "Living"),
    ("Internet", "Living"),
    ("Fuel", "Transport"),
    ("Transit", "Transport"),
    ("Shopping", "Discretionary"),
    ("Travel", "Discretionary"),
    ("Entertainment", "Discretionary"),
    ("Insurance", "Financial"),
    ("Investments", "Financial"),
    ("Credit Card Payment", "Transfer"),
    ("Transfer", "Transfer"),
    ("Fees", "Fees"),
    ("Refund", "Adjustments"),
]

MERCHANTS = {
    "Groceries": ["Fresh Fields", "GreenMart", "Daily Market", "Food Junction"],
    "Dining": ["Noodle House", "Cafe Aurora", "Pizzeria Uno", "Taco Villa"],
    "Utilities": ["City Power", "Aqua Water", "UtilityHub"],
    "Internet": ["FiberNet", "WebWave"],
    "Fuel": ["FuelUp", "GasGo", "PetroMax"],
    "Transit": ["MetroRail", "CityTransit", "RideNow"],
    "Shopping": ["General Store", "MallMart", "Style Corner"],
    "Travel": ["Skyways Air", "StayWell Hotels", "CityCar Rental"],
    "Entertainment": ["Cineplex", "MusicBox", "PlayHub"],
    "Insurance": ["SecureLife Insurance", "SureGuard"],
    "Fees": ["Service Fee", "Card Fee"],
    "Refund": ["Refund"],
}


def sha_md5(*parts: str) -> str:
    h = hashlib.md5()
    random.random()
    text = "|".join(parts) + str(random.random())
    h.update(text.encode())
    return h.hexdigest()


def month_range(start: date, months: int) -> tuple[date, date]:
    """Return the start and end date for the month offset from `start`."""
    year = start.year + (start.month - 1 + months) // 12
    month = (start.month - 1 + months) % 12 + 1
    period_start = date(year, month, 1)
    # First day of the next month minus one day
    next_year = year + (month // 12)
    next_month = (month % 12) + 1
    period_end = date(next_year, next_month, 1) - timedelta(days=1)
    return period_start, period_end


def pick_merchant(category: str) -> str:
    choices = MERCHANTS.get(category, ["Vendor"])
    return random.choice(choices)


def generate_transactions_for_account(
    spec: AccountSpec,
    start_date: date,
    end_date: date,
    categories: dict[str, orm.Categories],
) -> list[dict]:
    txs: list[dict] = []
    balance = spec.starting_balance

    current = start_date
    while current <= end_date:
        # Income events (1st and 15th)
        if spec.income_monthly > 0 and current.day in (1, 15):
            amount = spec.income_monthly / 2.0
            balance += amount
            txs.append(
                {
                    "Date": current.isoformat(),
                    "Amount": amount,
                    "Balance": balance,
                    "Description": "Payroll Deposit",
                    "Category": categories["Salary"],
                    "Verified": 1,
                }
            )

        # Time-dependent drift (random walk) to create variability without runaway
        drift_amount = 0.0
        if spec.asset_type.lower() != "debt":
            drift_rate = random.gauss(spec.drift_bias, spec.volatility)
            drift_amount = balance * drift_rate if balance else random.uniform(-25, 25)
            cap = max(
                spec.drift_cap_abs,
                spec.drift_cap_multiplier * abs(balance) if balance else 0.0,
            )
            drift_amount = max(-cap, min(cap, drift_amount))
            balance += drift_amount
            txs.append(
                {
                    "Date": current.isoformat(),
                    "Amount": drift_amount,
                    "Balance": balance,
                    "Description": "Daily drift",
                    "Category": categories["Investments"],
                    "Verified": 0,
                }
            )

        # Daily spending (halve frequency)
        daily_spend_events = random.randint(0, max(1, int(spec.spend_events_per_day)))
        for _ in range(daily_spend_events):
            category_name, category_type = random.choice(CATEGORIES)
            if category_type in {"Income", "Transfer"}:
                continue
            # Per-account spend range
            amount = round(
                random.uniform(spec.spend_min, spec.spend_max) * spec.expense_bias, 2
            )
            balance -= amount
            merchant = pick_merchant(category_name)
            txs.append(
                {
                    "Date": current.isoformat(),
                    "Amount": -amount,
                    "Balance": balance,
                    "Description": f"{merchant}",
                    "Category": categories.get(category_name, categories["Shopping"]),
                    "Verified": 0,
                }
            )

        # Occasional fees/refunds
        if random.random() < 0.0001:
            fee = round(random.uniform(1, 10), 2)
            balance -= fee
            txs.append(
                {
                    "Date": current.isoformat(),
                    "Amount": -fee,
                    "Balance": balance,
                    "Description": "Service Fee",
                    "Category": categories["Fees"],
                    "Verified": 0,
                }
            )
        if random.random() < 0.02:
            refund = round(random.uniform(5, 150), 2)
            balance += refund
            txs.append(
                {
                    "Date": current.isoformat(),
                    "Amount": refund,
                    "Balance": balance,
                    "Description": "Refund",
                    "Category": categories["Refund"],
                    "Verified": 0,
                }
            )

        current += timedelta(days=1)

    return txs


def create_synthetic_db(output: Path, years: int, seed: int) -> Path:
    random.seed(seed)
    output.parent.mkdir(parents=True, exist_ok=True)

    SessionLocal = orm.create_database(output)
    with SessionLocal() as session:
        _reset_tables(session)
        _populate(session, years)
        _set_alembic_version(session)
        session.commit()
    return output


def _populate(session: Session, years: int) -> None:
    # Account types (avoid duplicates if the DB already has entries)
    type_map = {}
    required_types = [
        ("Checking", "Asset"),
        ("Savings", "Asset"),
        ("Credit Card", "Debt"),
        ("401k", "Asset"),
        ("HSA", "Asset"),
        ("Loan", "Debt"),
        ("TangibleAsset", "TangibleAsset"),
        ("Brokerage", "Asset"),  # used by synthetic accounts
    ]
    for name, asset in required_types:
        existing = (
            session.query(orm.AccountTypes).filter_by(AccountType=name).one_or_none()
        )
        if existing:
            # Ensure AssetType matches desired value
            if existing.AssetType != asset:
                existing.AssetType = asset
            type_map[name] = existing
            continue
        obj = orm.AccountTypes(AccountType=name, AssetType=asset)
        session.add(obj)
        session.flush()
        type_map[name] = obj

    # Categories
    category_map: dict[str, orm.Categories] = {}
    for name, cat_type in CATEGORIES:
        existing = session.query(orm.Categories).filter_by(Name=name).one_or_none()
        if existing:
            category_map[name] = existing
            continue
        cat = orm.Categories(Name=name, Type=cat_type, Active=1)
        session.add(cat)
        session.flush()
        category_map[name] = cat

    # Plugins (single synthetic plugin)
    plugin = orm.Plugins(
        PluginName="synthetic_seed",
        Version="0.0.1",
        Suffix=".csv",
        Company="Synthetic Bank",
        StatementType="Synthetic Statement",
    )
    session.add(plugin)
    session.flush()

    # Accounts (renamed/retyped to match behavioral patterns)
    specs = [
        # Behaves like a 401k with contributions and market drift
        AccountSpec(
            name="401k Plan",
            company="Workplace Retirement",
            type_name="401k",
            asset_type="Asset",
            account_number="401K-10001",
            starting_balance=25000.0,
            income_monthly=800.0,
            expense_bias=0.05,
            volatility=0.01,
            drift_bias=0.001,
            drift_cap_multiplier=0.003,
            drift_cap_abs=1200.0,
            spend_min=0.0,
            spend_max=50.0,
            spend_events_per_day=0.2,
            investment=True,
        ),
        # Behaves like a credit card (formerly high-yield savings)
        AccountSpec(
            name="Travel Rewards Card",
            company="Alpine Bank",
            type_name="Credit Card",
            asset_type="Debt",
            account_number="5444333322221111",
            starting_balance=-400.0,
            income_monthly=0.0,
            expense_bias=0.7,
            volatility=0.0,
            drift_bias=0.0,
            drift_cap_multiplier=0.0,
            drift_cap_abs=0.0,
            spend_min=20.0,
            spend_max=300.0,
            spend_events_per_day=1.2,
        ),
        # Behaves like a credit card (reduce negatives)
        AccountSpec(
            name="Everyday Credit",
            company="Metro Card",
            type_name="Credit Card",
            asset_type="Debt",
            account_number="4111111111111111",
            starting_balance=-300.0,
            expense_bias=0.6,
            volatility=0.0,
            drift_bias=0.0,
            drift_cap_multiplier=0.0,
            drift_cap_abs=0.0,
            spend_min=15.0,
            spend_max=200.0,
            spend_events_per_day=1.0,
        ),
        # Behaves like a savings account (formerly brokerage)
        AccountSpec(
            name="High Yield Savings",
            company="NorthStar Savings",
            type_name="Savings",
            asset_type="Cash",
            account_number="2000987654",
            starting_balance=15000.0,
            income_monthly=0.0,
            expense_bias=0.15,
            volatility=0.05,
            drift_bias=0.006,
            drift_cap_multiplier=0.01,
            drift_cap_abs=1500.0,
            spend_min=10.0,
            spend_max=150.0,
            spend_events_per_day=0.5,
        ),
    ]

    start_date = date.today().replace(day=1) - timedelta(days=365 * years)
    end_date = date.today()

    for spec in specs:
        existing_account = (
            session.query(orm.Accounts).filter_by(AccountName=spec.name).one_or_none()
        )
        if existing_account:
            account = existing_account
        else:
            account = orm.Accounts(
                AccountName=spec.name,
                AccountTypeID=type_map[spec.type_name].AccountTypeID,
                Company=spec.company,
                Description=f"Synthetic {spec.type_name} account",
                AppreciationRate=0,
            )
            session.add(account)
            session.flush()

        existing_number = (
            session.query(orm.AccountNumbers)
            .filter_by(AccountID=account.AccountID, AccountNumber=spec.account_number)
            .one_or_none()
        )
        if not existing_number:
            session.add(
                orm.AccountNumbers(
                    AccountID=account.AccountID,
                    AccountNumber=spec.account_number,
                )
            )

        txs = generate_transactions_for_account(
            spec, start_date, end_date, category_map
        )

        # Group into monthly statements
        month = 0
        while True:
            period_start, period_end = month_range(start_date, month)
            month += 1
            if period_start > end_date:
                break
            period_end = min(period_end, end_date)
            monthly_txs = [
                t
                for t in txs
                if period_start.isoformat() <= t["Date"] <= period_end.isoformat()
            ]
            if not monthly_txs:
                continue
            start_balance = monthly_txs[0]["Balance"] - monthly_txs[0]["Amount"]
            end_balance = monthly_txs[-1]["Balance"]

            stmt = orm.Statements(
                PluginID=plugin.PluginID,
                AccountID=account.AccountID,
                ImportDate=datetime.utcnow().isoformat(),
                StartDate=period_start.isoformat(),
                EndDate=period_end.isoformat(),
                StartBalance=start_balance,
                EndBalance=end_balance,
                TransactionCount=len(monthly_txs),
                Filename=f"{spec.account_number}_{period_start:%Y%m}.csv",
                MD5=sha_md5(spec.account_number, period_start.isoformat()),
            )
            session.add(stmt)
            session.flush()

            for tx in monthly_txs:
                desc = tx["Description"]
                category_id = tx["Category"].CategoryID
                session.add(
                    orm.Transactions(
                        StatementID=stmt.StatementID,
                        AccountID=account.AccountID,
                        Date=tx["Date"],
                        Amount=tx["Amount"],
                        Balance=tx["Balance"],
                        Description=desc,
                        MD5=sha_md5(
                            tx["Date"], str(tx["Amount"]), spec.account_number, desc
                        ),
                        CategoryID=category_id,
                        Verified=tx["Verified"],
                        ConfidenceScore=0.9,
                    )
                )


def _set_alembic_version(session: Session) -> None:
    """
    Ensure alembic_version table exists and set a fixed revision marker.
    """
    session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS alembic_version (
                version_num VARCHAR(32) NOT NULL
            )
            """
        )
    )
    session.execute(text("DELETE FROM alembic_version"))
    session.execute(
        text("INSERT INTO alembic_version (version_num) VALUES ('e0ecdd6abcc6')")
    )


def _reset_tables(session: Session) -> None:
    """
    Clear existing data so reruns don't hit UNIQUE constraints.
    """
    session.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS alembic_version (
                version_num VARCHAR(32) NOT NULL
            )
            """
        )
    )
    session.execute(text("DELETE FROM Transactions"))
    session.execute(text("DELETE FROM Statements"))
    session.execute(text("DELETE FROM AccountNumbers"))
    session.execute(text("DELETE FROM Accounts"))
    session.execute(text("DELETE FROM Categories"))
    session.execute(text("DELETE FROM AccountTypes"))
    session.execute(text("DELETE FROM Plugins"))
    session.execute(text("DELETE FROM alembic_version"))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a synthetic ParseTrail SQLite database."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("synthetic.parsetrail.db"),
        help="Path to write DB file.",
    )
    parser.add_argument(
        "--years", type=int, default=3, help="Years of history to generate."
    )
    parser.add_argument(
        "--seed", type=int, default=1234, help="Random seed for reproducibility."
    )
    args = parser.parse_args()

    out_path = create_synthetic_db(args.output, args.years, args.seed)
    print(f"Synthetic database created at {out_path.resolve()}")


if __name__ == "__main__":
    main()
