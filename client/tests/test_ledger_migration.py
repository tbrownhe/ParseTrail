import copy
from dataclasses import replace
from datetime import date

import pytest
from parsetrail.core.ledger import LedgerError
from parsetrail.core.ledger_migration import apply_plan, build_plan, reconcile_plan, verify_approved_preview
from parsetrail.core.ledger_store import LedgerStore, decode_entry, encoded


@pytest.fixture
def legacy():
    return {
        "Accounts": [
            {"AccountID": i, "AccountName": name, "AccountTypeID": kind, "CurrencyCode": "USD"}
            for i, name, kind in [(1, "Checking", 1), (2, "Card", 2), (3, "HSA", 3), (4, "Loan", 4)]
        ],
        "AccountTypes": [
            {"AccountTypeID": i, "AccountType": name, "AssetType": asset}
            for i, name, asset in [
                (1, "Checking", "Asset"),
                (2, "Credit Card", "Debt"),
                (3, "HSA", "Asset"),
                (4, "Loan", "Debt"),
            ]
        ],
        "Categories": [
            {"CategoryID": i, "Name": name, "Type": name}
            for i, name in [(1, "Expense"), (2, "Income"), (3, "Transfer")]
        ],
        "Plugins": [{"PluginID": 1, "PluginName": "pdf_hehsa"}, {"PluginID": 2, "PluginName": "synthetic"}],
        "Transactions": [
            row(1, 2, -1000, -1000, "Purchase", 1),
            row(2, 1, -1000, 0, "Card payment", 3),
            row(3, 2, 1000, 0, "Card payment received", 3),
            row(4, 1, 2000, 2000, "Income", 2),
            row(5, 3, 1, 1001, "HSA interest", 2),
            row(6, 1, -2000, 0, "Manual Entry: Account Closed Manually", 1),
            row(7, 4, -5000, -5000, "LOAN ORIGINATION", 3),
            row(8, 1, 0, 0, "Zero", 1),
        ],
        "Statements": [
            statement(1, 3, 1, 1000, 1001),
            statement(2, 1, 2, 0, 1000),
            statement(3, 2, 2, 0, 0),
            statement(4, 4, 2, 0, -5000),
        ],
        "StatementTransactions": [
            {"StatementID": sid, "TransactionID": tid, "StatementRow": index}
            for sid, tid, index in [(1, 5, 1), (2, 4, 1), (2, 2, 2), (2, 8, 3), (3, 1, 1), (3, 3, 2), (4, 7, 1)]
        ],
    }


def row(tid, aid, amount, balance, description, category):
    return {
        "TransactionID": tid,
        "AccountID": aid,
        "AmountMinor": amount,
        "BalanceMinor": balance,
        "Description": description,
        "CategoryID": category,
        "Verified": True,
        "PostingDate": "2026-08-20",
        "TransactionDate": "2026-08-20",
        "CurrencyCode": "USD",
    }


def statement(sid, aid, plugin, opening, closing):
    return {
        "StatementID": sid,
        "AccountID": aid,
        "PluginID": plugin,
        "StartDate": "2026-08-01",
        "EndDate": "2026-08-31",
        "StartBalanceMinor": opening,
        "EndBalanceMinor": closing,
        "CurrencyCode": "USD",
        "ContentHash": str(sid) * 64,
    }


def corrections():
    return [
        {
            "statement_id": 1,
            "source_hash": "1" * 64,
            "opening_minor": 1000,
            "closing_minor": 1101,
            "parser": "pdf_hehsa_201810",
            "version": "0.2.1",
            "rows": [
                {"PostingDate": "2026-08-20", "AmountMinor": 1, "BalanceMinor": 1001, "Description": "HSA interest"},
                {
                    "PostingDate": "2026-08-21",
                    "AmountMinor": 100,
                    "BalanceMinor": 1101,
                    "Description": "Source addition",
                },
            ],
        }
    ]


def test_plan_is_deterministic_preserves_input_and_never_guesses_transfers(legacy, tmp_path):
    original = copy.deepcopy(legacy)
    plan = build_plan(legacy, source_id="synthetic", corrections=corrections())
    assert legacy == original
    assert plan == build_plan(legacy, source_id="synthetic", corrections=corrections())
    assert len(plan["added_source_rows"]) == 1
    assert plan["summary"]["unconfirmed_transfer"] == 2
    assert plan["summary"]["manual_closure_control_evidence"] == 1
    assert plan["summary"]["synthetic_loan_opening_review"] == 1
    assert plan["summary"]["zero_amount_evidence"] == 1
    assert all(not entry["reviewed"] for entry in plan["entries"])
    assert all(p["status"] == "unposted_anchor_proposal" for p in plan["opening_proposals"])
    with LedgerStore(tmp_path / "ledger.db", create=True) as store:
        apply_plan(plan, store)
        before = store.balances(date(2026, 8, 31))
        apply_plan(plan, store)
        assert store.balances(date(2026, 8, 31)) == before
        assert store.connection.execute("SELECT count(*) FROM LedgerEntries").fetchone()[0] == 3
        assert len(store.observations()) == 6
        assert reconcile_plan(plan, store)["unallocated_observation_count"] == 3


def test_overlapping_membership_does_not_duplicate_observation_or_expense(legacy, tmp_path):
    legacy["Statements"].append({**legacy["Statements"][2], "StatementID": 5})
    legacy["StatementTransactions"] += [
        {"StatementID": 5, "TransactionID": tid, "StatementRow": n} for n, tid in enumerate((1, 3), 1)
    ]
    plan = build_plan(legacy, source_id="synthetic", corrections=[])
    with LedgerStore(tmp_path / "ledger.db", create=True) as store:
        apply_plan(plan, store)
        assert len([o for o in store.observations() if o.endswith(":transaction:1")]) == 1
        assert len(plan["entries"]) == 2


@pytest.mark.parametrize("bad", ["removed", "opening", "source", "equation", "duplicate"])
def test_correction_requires_preserved_rows_identity_and_exact_equation(legacy, bad):
    changed = corrections()
    if bad == "removed":
        changed[0]["rows"] = changed[0]["rows"][1:]
    elif bad == "opening":
        changed[0]["opening_minor"] += 1
    elif bad == "source":
        changed[0]["source_hash"] = "wrong"
    elif bad == "equation":
        changed[0]["closing_minor"] += 1
    else:
        changed.append(copy.deepcopy(changed[0]))
    with pytest.raises(ValueError):
        build_plan(legacy, source_id="synthetic", corrections=changed)


def test_reported_continuity_gap_remains_exception_without_adjustment(legacy, tmp_path):
    later = {
        **legacy["Statements"][0],
        "StatementID": 5,
        "StartDate": "2026-09-01",
        "EndDate": "2026-09-30",
        "StartBalanceMinor": 1200,
        "EndBalanceMinor": 1200,
        "ContentHash": "5" * 64,
    }
    legacy["Statements"].append(later)
    changed = corrections() + [
        {
            "statement_id": 5,
            "source_hash": "5" * 64,
            "opening_minor": 1200,
            "closing_minor": 1200,
            "parser": "synthetic",
            "version": "1",
            "rows": [],
        }
    ]
    plan = build_plan(legacy, source_id="synthetic", corrections=changed)
    assert plan["continuity_exceptions"] == [
        {"account_id": 3, "statement_ids": [1, 5], "difference_minor": 99, "both_reported": True}
    ]
    assert all(entry["origin"] == "imported" for entry in plan["entries"])
    with LedgerStore(tmp_path / "ledger.db", create=True) as store:
        apply_plan(plan, store)
        report = reconcile_plan(plan, store)
        assert report["reconciled_statement_count"] == 0


def test_partial_batch_failure_rolls_back_accounts_observations_and_postings(legacy, tmp_path):
    plan = build_plan(legacy, source_id="synthetic", corrections=corrections())
    with LedgerStore(tmp_path / "good.db", create=True) as good:
        apply_plan(plan, good)
        accounts = list(good.accounts().values())
        observations = list(good.observations().values())
    entries = [decode_entry(encoded(r)) for r in plan["entries"]]
    invalid = replace(entries[-1], key="invalid", postings=entries[-1].postings[:1])
    with LedgerStore(tmp_path / "bad.db", create=True) as store:
        with pytest.raises(LedgerError):
            store.load_batch(accounts, observations, [], entries + [invalid])
        assert store.accounts() == {}
        assert store.observations() == {}
        assert store.connection.execute("SELECT count(*) FROM LedgerEntries").fetchone()[0] == 0


def test_tampered_plan_is_rejected_before_any_writes(legacy, tmp_path):
    plan = build_plan(legacy, source_id="synthetic", corrections=[])
    plan["entries"][0]["postings"][0]["amount_minor"] += 1
    with LedgerStore(tmp_path / "ledger.db", create=True) as store:
        with pytest.raises(ValueError, match="checksum"):
            apply_plan(plan, store)
        assert store.accounts() == {}


def test_new_source_rows_have_stable_identity_and_remain_unclassified(legacy):
    plan = build_plan(legacy, source_id="synthetic", corrections=corrections())
    added = plan["added_source_rows"][0]["observation_id"]
    assert next(d for d in plan["decisions"] if d["observation_id"] == added)["reason"] == "uncategorized_evidence"
    assert not any(
        p["allocations"] and p["allocations"][0]["observation_id"] == added
        for e in plan["entries"]
        for p in e["postings"]
    )


def test_preview_binding_rejects_any_change_to_owner_approved_source_rows(legacy):
    correction = corrections()
    plan = build_plan(legacy, source_id="synthetic", corrections=correction)
    preview = {
        "parser_version": "0.2.1",
        "remaining_continuity_exceptions": [],
        "statements": [
            {
                "statement_id": 1,
                "opening_minor": 1000,
                "closing_minor": 1101,
                "added": [["2026-08-21", 100, 1101, "Source addition"]],
            }
        ],
    }
    verify_approved_preview(legacy, correction, plan, preview)
    preview["statements"][0]["added"][0][1] = 101
    with pytest.raises(ValueError, match="approved preview"):
        verify_approved_preview(legacy, correction, plan, preview)


def test_transfer_matches_are_only_candidates_even_when_unique(legacy):
    plan = build_plan(legacy, source_id="synthetic", corrections=[])
    assert len(plan["transfer_candidates"]) == 2
    assert all(not c["confirmed"] for c in plan["transfer_candidates"])
    assert all(len(c["candidate_ids"]) >= 1 for c in plan["transfer_candidates"])
    assert all("Card payment" not in e["description"] for e in plan["entries"])
