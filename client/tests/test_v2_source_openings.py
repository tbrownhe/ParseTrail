"""Earliest source openings remain read-only candidates until timing review."""

from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

from parsetrail.core.source_evidence import DateValue
from parsetrail.core.v2_profile_store import FinancialAccount, V2ProfileStore
from parsetrail.core.v2_table_bank_source_output import from_anchored_bank

from devtools.parser_engine_pilot.test_table_bank_source_output import DEFINITION, SOURCE
from devtools.parser_engine_pilot.test_table_bank_source_output import evidence as bank_channels


def _variant(evidence, source: bytes, *, opening_minor: int | None = None, unknown_start: bool = False):
    digest = hashlib.sha256(source).hexdigest()
    original = evidence.payload.accounts[0]
    rows = tuple(
        row.model_copy(update={"row_id": hashlib.sha256((digest + row.row_id).encode()).hexdigest()})
        for row in original.rows
    )
    opening = original.opening
    if opening_minor is not None:
        opening = opening.model_copy(update={"raw": f"${opening_minor / 100:.2f}", "minor": opening_minor})
    account = original.model_copy(update={"opening": opening, "rows": rows})
    payload = evidence.payload.model_copy(
        update={
            "start": DateValue(raw=None, iso=None, provenance="unknown", locations=())
            if unknown_start
            else evidence.payload.start,
            "accounts": (account,),
            "independent_balance_verified": False,
        }
    )
    return evidence.model_copy(update={"source_sha256": digest, "payload": payload})


def test_earliest_bound_opening_preserves_conflicts_and_unknown_periods(tmp_path: Path) -> None:
    evidence = from_anchored_bank(DEFINITION, *bank_channels())
    profile = tmp_path / "fresh.db"
    with V2ProfileStore.create(profile) as store:
        store.add_financial_account(FinancialAccount("cash", "Savings", "asset", "lendingclub"))
        store.add_financial_account(FinancialAccount("other", "Other", "asset", "lendingclub"))
        assert store.earliest_source_openings()[0].blockers == ("no_bound_statement",)
        store.import_source(SOURCE, DEFINITION, evidence, suffix=".pdf")
        account = evidence.payload.accounts[0]
        store.bind_source_account(evidence.source_sha256, account.source_identity, account.source_identity_form, "cash")
        first = store.earliest_source_openings()[1]
        assert first.earliest_period_start == date(2026, 1, 1)
        assert first.printed_opening_minor == 10_000
        assert first.blockers == ("source_timing_unreviewed",)

        conflicting_source = SOURCE + b"-conflicting"
        conflicting = _variant(evidence, conflicting_source, opening_minor=20_000)
        store.import_source(conflicting_source, DEFINITION, conflicting, suffix=".pdf")
        store.bind_source_account(
            conflicting.source_sha256, account.source_identity, account.source_identity_form, "cash"
        )
        tied = store.earliest_source_openings()[1]
        assert tied.printed_opening_minor is None
        assert tied.bound_statement_sections == 2
        assert len(tied.earliest_source_ids) == 2
        assert "conflicting_earliest_openings" in tied.blockers

        unknown_source = SOURCE + b"-unknown-period"
        unknown = _variant(evidence, unknown_source, unknown_start=True)
        store.import_source(unknown_source, DEFINITION, unknown, suffix=".pdf")
        store.bind_source_account(unknown.source_sha256, account.source_identity, account.source_identity_form, "cash")
        uncertain = store.earliest_source_openings()[1]
        assert uncertain.earliest_period_start is None
        assert uncertain.printed_opening_minor is None
        assert uncertain.blockers == ("unknown_source_period", "source_timing_unreviewed")
        assert store.connection.execute("SELECT COUNT(*) FROM JournalEntries").fetchone() == (0,)
    with V2ProfileStore.open(profile, read_only=True) as store:
        assert store.earliest_source_openings()[1] == uncertain
