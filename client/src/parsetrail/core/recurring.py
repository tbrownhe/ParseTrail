"""Headless recurring-analysis inputs and results, safe to execute in a worker."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import pandas as pd

from parsetrail.core import cluster
from parsetrail.core.analysis import CancellationCheck, check_cancelled
from parsetrail.core.transactions import TransactionService

ReviewSnapshot = tuple[tuple[int, date, Decimal, str], ...]


@dataclass(frozen=True)
class RecurringResult:
    input_count: int
    transactions: pd.DataFrame


def analyze_range(
    service: TransactionService,
    start: date,
    end: date,
    options: dict,
    cancelled: CancellationCheck,
) -> RecurringResult:
    check_cancelled(cancelled)
    # in_range opens and closes its session in this calling (worker) thread.
    rows = service.in_range(start, end)
    values = []
    for row in rows:
        check_cancelled(cancelled)
        values.append((row.account_name, row.date, row.amount, row.category, row.description))
    frame = pd.DataFrame(values, columns=["AccountName", "Date", "Amount", "Category", "Description"])
    return RecurringResult(len(rows), cluster.recurring_transactions(frame, cancelled=cancelled, **options))


def analyze_snapshot(snapshot: ReviewSnapshot, options: dict, cancelled: CancellationCheck) -> pd.DataFrame:
    check_cancelled(cancelled)
    frame = pd.DataFrame(snapshot, columns=["TransactionID", "Date", "Amount", "Description"])
    return cluster.recurring_transactions(frame, cancelled=cancelled, **options)
