import copy
import json
import sqlite3
from contextlib import closing

import pytest
from parsetrail.core.ledger import LedgerError
from parsetrail.core.ledger_candidates import apply_candidates, build_candidates, create_candidates
from parsetrail.core.ledger_rebuild import write_rebuild
from parsetrail.core.ledger_store import LedgerStore, decode_entry, encoded
from parsetrail.core.recovery_bundle import digest


@pytest.fixture
def rebuild():
    roles = [("Checking", "Asset"), ("Credit Card", "Debt"), ("Savings", "Asset"), ("Loan", "Debt")]
    metadata = {
        "AccountTypes": [
            {"AccountTypeID": i, "AccountType": role, "AssetType": kind} for i, (role, kind) in enumerate(roles, 1)
        ],
        "Accounts": [
            {"AccountID": i, "AccountName": role, "AccountTypeID": i, "CurrencyCode": "USD"}
            for i, (role, _) in enumerate(roles, 1)
        ],
        "Categories": [{"CategoryID": 1, "Name": "Food", "Type": "Expense", "ParentID": None}],
    }
    transactions, annotations = {}, []
    for tid, aid, amount, verified in [
        ("bank_purchase", 1, -1500, True),
        ("bank_payment", 1, -1000, False),
        ("card_purchase", 2, -3000, True),
        ("card_refund", 2, 500, True),
        ("card_payment", 2, 1000, False),
        ("bank_refund", 1, 200, True),
        ("zero", 3, 0, False),
        ("interest", 3, 10, False),
        ("loan", 4, -100, True),
    ]:
        transactions[tid] = {
            "id": tid,
            "AccountID": aid,
            "AmountMinor": amount,
            "CurrencyCode": "USD",
            "PostingDate": "2026-08-20",
            "TransactionDate": "2026-08-19",
            "Description": tid,
        }
        if verified:
            annotations.append(
                {
                    "legacy_id": len(annotations) + 1,
                    "transaction_id": tid,
                    "status": "restored",
                    "account_id": aid,
                    "amount_minor": amount,
                    "currency": "USD",
                    "category_id": 1,
                    "legacy": {"Verified": True},
                }
            )
    statements, memberships = {}, []
    for aid in range(1, 5):
        sid = f"s{aid}"
        rows = [t for t, row in transactions.items() if row["AccountID"] == aid]
        statements[sid] = {
            "id": sid,
            "source": "card" if aid == 2 else "bank",
            "account_id": aid,
            "start": "2026-08-01",
            "end": "2026-08-31",
            "opening_minor": 0,
            "closing_minor": sum(transactions[t]["AmountMinor"] for t in rows),
            "status": "parsed",
            "balance_provenance": "parser output; unverified",
        }
        memberships.extend(
            {"statement_id": sid, "transaction_id": t, "source": statements[sid]["source"], "row": i}
            for i, t in enumerate(rows, 1)
        )
    return {
        "legacy_metadata": metadata,
        "evidence": {
            "files": {
                "bank": {"plugin": "pdf_wfbankper_202105", "status": "parsed"},
                "card": {"plugin": "pdf_chasecc_202602", "status": "parsed"},
            },
            "transactions": transactions,
            "statements": statements,
            "memberships": memberships,
        },
        "annotations": {"decisions": annotations},
    }


def test_expense_and_refund_signs_preserve_cash_and_card_evidence(rebuild):
    original = copy.deepcopy(rebuild)
    result = build_candidates(rebuild)
    assert rebuild == original
    assert result == build_candidates(rebuild)
    assert result["summary"] == {
        "proposed_expense": 2,
        "proposed_refund": 2,
        "needs_interpretation": 3,
        "zero_amount_evidence": 1,
        "outside_cash_card_scope": 1,
    }
    for proposal in result["proposals"]:
        tid = proposal["key"].removeprefix("proposal:")
        source = rebuild["evidence"]["transactions"][tid]
        first, second = proposal["postings"]
        assert first["amount_minor"] == source["AmountMinor"]
        assert second["amount_minor"] == -source["AmountMinor"]
        assert first["allocations"] == ({"observation_id": f"source:{tid}", "amount_minor": source["AmountMinor"]},)
        assert proposal["posting_date"] == source["PostingDate"]
        assert not proposal["reviewed"]
    assert len(result["observations"]) == 7
    assert all(s["opening_provenance"] == s["closing_provenance"] == "assumed" for s in result["statements"])
    assert result["journal_entries_posted"] == 0


def test_overlap_uses_one_observation_and_proposal(rebuild):
    evidence = rebuild["evidence"]
    evidence["statements"]["overlap"] = {**evidence["statements"]["s1"], "id": "overlap"}
    evidence["memberships"] += [
        {**link, "statement_id": "overlap"} for link in evidence["memberships"] if link["statement_id"] == "s1"
    ]
    result = build_candidates(rebuild)
    assert len(result["observations"]) == 7
    assert len(result["proposals"]) == 4
    assert len(result["statements"]) == 4


@pytest.mark.parametrize(
    "problem,status",
    [
        ("plugin", "source_sign_contract_pending"),
        ("date", "source_date_exception"),
        ("balance", "source_balance_difference"),
        ("warning", "source_review_pending"),
    ],
)
def test_source_exceptions_block_interpretation(rebuild, problem, status):
    evidence = rebuild["evidence"]
    if problem == "plugin":
        evidence["files"]["card"]["plugin"] = "unknown"
    elif problem == "date":
        evidence["transactions"]["card_purchase"]["PostingDate"] = "2026-09-01"
    elif problem == "balance":
        evidence["statements"]["s2"]["closing_minor"] += 1
    else:
        evidence["files"]["card"]["status"] = "review_pending"
    result = build_candidates(rebuild)
    assert result["statement_decisions"]["s2"]["status"] == status
    assert not any(o["account_id"] == "account:2" for o in result["observations"])
    assert all(d["status"] == "source_review_pending" for d in result["decisions"] if d["account_id"] == 2)


@pytest.mark.parametrize("problem", ["owner", "duplicate", "currency", "class", "category", "verification"])
def test_contradictory_evidence_is_rejected(rebuild, problem):
    if problem == "owner":
        rebuild["evidence"]["memberships"][0]["source"] = "card"
    elif problem == "duplicate":
        rebuild["evidence"]["memberships"].append(rebuild["evidence"]["memberships"][0])
    elif problem == "currency":
        rebuild["legacy_metadata"]["Accounts"][0]["CurrencyCode"] = "EUR"
    elif problem == "class":
        rebuild["legacy_metadata"]["AccountTypes"][1]["AssetType"] = "Asset"
    elif problem == "category":
        rebuild["annotations"]["decisions"][0]["amount_minor"] += 1
    else:
        rebuild["annotations"]["decisions"][0]["legacy"]["Verified"] = False
    with pytest.raises(LedgerError):
        build_candidates(rebuild)


def test_immutable_proposals_do_not_post_consume_or_promote_review(rebuild, tmp_path):
    plan = build_candidates(rebuild)
    path = tmp_path / "fresh.db"
    write_rebuild(path, rebuild)
    with LedgerStore(path) as store:
        annotations = store.connection.execute("SELECT * FROM CategoryAnnotations").fetchall()
        apply_candidates(store, plan)
        before = list(store.connection.iterdump())
        apply_candidates(store, plan)
        assert list(store.connection.iterdump()) == before
        assert store.connection.execute("SELECT count(*) FROM JournalProposals").fetchone() == (4,)
        for table in ("LedgerEntries", "LedgerAllocations", "LedgerReviews", "LedgerReconciliations"):
            assert store.connection.execute(f"SELECT count(*) FROM {table}").fetchone() == (0,)
        assert store.consumed() == {}
        assert store.connection.execute("SELECT * FROM CategoryAnnotations").fetchall() == annotations
        for table in ("JournalProposals", "JournalProposalPlans"):
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                store.connection.execute(f"DELETE FROM {table}")
        for rename in (False, True):
            changed = copy.deepcopy(plan)
            changed["proposals"][0]["key" if rename else "description"] += "changed"
            with pytest.raises(LedgerError, match="different contents"):
                apply_candidates(store, changed)
            assert list(store.connection.iterdump()) == before


@pytest.mark.parametrize("problem", ["unbalanced", "duplicate", "reviewed", "sign", "partial", "reordered"])
def test_invalid_proposals_cannot_partially_install(rebuild, tmp_path, problem):
    plan = build_candidates(rebuild)
    entry = plan["proposals"][0]
    if problem == "unbalanced":
        entry["postings"][1]["amount_minor"] += 1
    elif problem == "duplicate":
        plan["proposals"].append(copy.deepcopy(entry))
    elif problem == "reviewed":
        entry["reviewed"] = True
    elif problem in ("sign", "partial"):
        for posting in entry["postings"]:
            posting["amount_minor"] = -posting["amount_minor"] if problem == "sign" else posting["amount_minor"] // 2
        entry["postings"][0]["allocations"][0]["amount_minor"] = entry["postings"][0]["amount_minor"]
    else:
        entry["postings"] = tuple(reversed(entry["postings"]))
    with LedgerStore(tmp_path / "test.db", create=True) as store:
        before = list(store.connection.iterdump())
        with pytest.raises(LedgerError):
            apply_candidates(store, plan)
        assert list(store.connection.iterdump()) == before


def test_posted_database_is_not_a_proposal_target(rebuild, tmp_path):
    plan = build_candidates(rebuild)
    with LedgerStore(tmp_path / "posted.db", create=True) as store:
        apply_candidates(store, plan)
        store.post(decode_entry(encoded(plan["proposals"][0])))
        with pytest.raises(LedgerError, match="unposted ledger"):
            apply_candidates(store, plan)


def accepted_folder(tmp_path, rebuild):
    folder = tmp_path / "accepted"
    folder.mkdir()
    write_rebuild(folder / "fresh.db", rebuild)
    (folder / "plan.json").write_text(encoded(rebuild), encoding="utf-8")
    (folder / "legacy.db").write_bytes(b"retained historical snapshot")
    (folder / "report.json").write_text(
        json.dumps(
            {
                "plan_sha256": digest(folder / "plan.json"),
                "database_sha256": digest(folder / "fresh.db"),
                "source_sha256": digest(folder / "legacy.db"),
            }
        ),
        encoding="utf-8",
    )
    return folder


def test_independent_copies_reproduce_and_preserve_all_original_tables(rebuild, tmp_path):
    folder = accepted_folder(tmp_path, rebuild)
    original = digest(folder / "fresh.db")
    reports = [create_candidates(folder, tmp_path / name) for name in ("one", "two")]
    assert reports[0] == reports[1]
    assert reports[0]["proposal_count"] == 4
    assert not reports[0]["ready_for_cutover"]
    with (
        closing(sqlite3.connect(folder / "fresh.db")) as source,
        closing(sqlite3.connect(tmp_path / "one" / "candidates.db")) as target,
    ):
        for (table,) in source.execute("SELECT name FROM sqlite_master WHERE type='table'"):
            if table in {"LedgerAccounts", "LedgerObservations", "LedgerStatements"}:
                continue
            assert (
                source.execute(f'SELECT * FROM "{table}"').fetchall()
                == target.execute(f'SELECT * FROM "{table}"').fetchall()
            )
    with pytest.raises(FileExistsError):
        create_candidates(folder, tmp_path / "one")
    assert digest(folder / "fresh.db") == original


@pytest.mark.parametrize("artifact", ["plan.json", "fresh.db", "legacy.db"])
def test_checksum_tampering_cannot_produce_a_candidate(rebuild, tmp_path, artifact):
    folder = accepted_folder(tmp_path, rebuild)
    with (folder / artifact).open("ab") as file:
        file.write(b"changed")
    with pytest.raises(LedgerError, match="artifact has changed"):
        create_candidates(folder, tmp_path / "bad")
    assert not (tmp_path / "bad").exists()


def test_active_database_and_mismatched_plan_cannot_complete(rebuild, tmp_path):
    folder = accepted_folder(tmp_path, rebuild)
    sidecar = folder / "fresh.db-wal"
    sidecar.touch()
    with pytest.raises(LedgerError, match="inactive"):
        create_candidates(folder, tmp_path / "active")
    sidecar.unlink()
    rebuild["extra"] = "a different accepted plan"
    (folder / "plan.json").write_text(encoded(rebuild), encoding="utf-8")
    report = json.loads((folder / "report.json").read_text(encoding="utf-8"))
    report["plan_sha256"] = digest(folder / "plan.json")
    (folder / "report.json").write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(LedgerError, match="does not belong"):
        create_candidates(folder, tmp_path / "mismatch")
    assert not (tmp_path / "mismatch" / "report.json").exists()


def test_proposal_failure_is_recoverable_without_partial_registration(rebuild, tmp_path):
    plan = build_candidates(rebuild)
    with LedgerStore(tmp_path / "retry.db", create=True) as store:
        apply_candidates(store, {**plan, "proposals": []})
        before_plans = store.connection.execute("SELECT * FROM JournalProposalPlans").fetchall()
        # Abort after at least one proposal insert; the entire registration must roll back.
        store.connection.execute("""CREATE TRIGGER interrupt_proposals BEFORE INSERT ON JournalProposals
            WHEN (SELECT count(*) FROM JournalProposals) > 0
            BEGIN SELECT RAISE(ABORT,'simulated interruption'); END""")
        with pytest.raises(sqlite3.IntegrityError, match="simulated interruption"):
            apply_candidates(store, plan)
        assert store.connection.execute("SELECT count(*) FROM JournalProposals").fetchone() == (0,)
        assert store.connection.execute("SELECT * FROM JournalProposalPlans").fetchall() == before_plans
        assert store.connection.execute("SELECT count(*) FROM LedgerEntries").fetchone() == (0,)
        store.connection.execute("DROP TRIGGER interrupt_proposals")
        apply_candidates(store, plan)
        assert store.connection.execute("SELECT count(*) FROM JournalProposals").fetchone() == (4,)
