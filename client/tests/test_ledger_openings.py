import copy
import importlib.util
from pathlib import Path

import pytest
from parsetrail.core.ledger import LedgerError
from parsetrail.core.ledger_candidates import build_candidates, create_candidates
from parsetrail.core.ledger_openings import build_opening_readiness
from parsetrail.core.ledger_rebuild import key

from .test_ledger_candidates import accepted_folder
from .test_ledger_candidates import rebuild as rebuild


def plans(rebuild):
    for fid, row in rebuild["evidence"]["files"].items():
        row["filename"] = fid + ".pdf"
    return rebuild, build_candidates(rebuild)


def test_openings_remain_unreviewed_including_zero_and_do_not_mutate_inputs(rebuild):
    rebuild, candidates = plans(rebuild)
    originals = copy.deepcopy((rebuild, candidates))
    result = build_opening_readiness(rebuild, candidates)
    assert (rebuild, candidates) == originals
    assert result == build_opening_readiness(rebuild, candidates)
    assert result["anchor_count"] == 3
    assert result["zero_balance_count"] == 3
    assert result["unambiguous_nonzero_count"] == 0
    assert not result["ready_for_opening_posting"] and result["journal_entries_posted"] == 0
    for anchor in result["anchors"]:
        assert anchor["proposed_date"] == "2026-07-31"
        assert anchor["blockers"] == ["source_balance_and_timing_review_required"]
        assert not anchor["reviewed"] and not anchor["posted"]
        assert anchor["sources"][0]["opening_provenance"] == "assumed"
    assert result["anchors"][1]["posting_date_limitations"]


def test_nonzero_liability_opening_keeps_sign_without_creating_an_expense(rebuild):
    rebuild["evidence"]["statements"]["s2"]["opening_minor"] = -5000
    rebuild["evidence"]["statements"]["s2"]["closing_minor"] -= 5000
    result = build_opening_readiness(*plans(rebuild))
    assert result["anchors"][1]["proposed_amount_minor"] == -5000
    assert result["unambiguous_nonzero_count"] == 1
    assert not result["ready_for_opening_posting"]


def add_period(rebuild, sid, start, end, opening=0, closing=0):
    rebuild["evidence"]["statements"][sid] = {
        **rebuild["evidence"]["statements"]["s1"],
        "id": sid,
        "start": start,
        "end": end,
        "opening_minor": opening,
        "closing_minor": closing,
    }


@pytest.mark.parametrize(
    "opening,closing,expected", [(0, 0, "adjacent_balances_agree"), (1, 1, "adjacent_balance_difference")]
)
def test_adjacent_boundaries_compare_exactly_without_certifying_reconciliation(rebuild, opening, closing, expected):
    add_period(rebuild, "prior", "2026-07-01", "2026-07-31", opening, closing)
    result = build_opening_readiness(*plans(rebuild))
    boundary = result["continuity"][0]
    assert boundary["status"] == expected
    assert boundary["endpoint_differences_minor"] == [-closing]
    assert not boundary["independently_verified"]


def test_gap_with_equal_balances_is_still_uncovered(rebuild):
    add_period(rebuild, "prior", "2026-06-01", "2026-06-30")
    result = build_opening_readiness(*plans(rebuild))
    boundary = result["continuity"][0]
    assert boundary["status"] == "coverage_gap"
    assert boundary["uncovered_days"] == 31
    assert (boundary["gap_start"], boundary["gap_end"]) == ("2026-07-01", "2026-07-31")
    assert boundary["endpoint_differences_minor"] == [0]


def test_nested_period_does_not_manufacture_gap(rebuild):
    add_period(rebuild, "outer", "2026-07-01", "2026-07-31")
    add_period(rebuild, "inner", "2026-07-10", "2026-07-20")
    result = build_opening_readiness(*plans(rebuild))
    assert result["continuity_summary"] == {"overlapping_periods": 1, "adjacent_balances_agree": 1}
    assert result["continuity"][-1]["prior_statement_ids"] == ["outer"]


def test_same_end_conflicting_closings_cannot_arbitrarily_choose_one(rebuild):
    add_period(rebuild, "one", "2026-07-01", "2026-07-31")
    add_period(rebuild, "two", "2026-07-10", "2026-07-31", 10, 10)
    result = build_opening_readiness(*plans(rebuild))
    assert result["continuity"][-1]["status"] == "conflicting_prior_closings"
    assert result["continuity"][-1]["endpoint_differences_minor"] == [-10, 0]


def test_earliest_conflict_or_ineligible_source_never_falls_back_to_later_period(rebuild):
    add_period(rebuild, "prior", "2026-07-01", "2026-07-31", 10, 11)
    add_period(rebuild, "conflict", "2026-07-01", "2026-07-15", 12, 12)
    result = build_opening_readiness(*plans(rebuild))
    anchor = result["anchors"][0]
    assert anchor["proposed_amount_minor"] is None
    assert anchor["proposed_date"] == "2026-06-30"
    assert {"conflicting_earliest_openings", "earliest_statement_not_eligible"}.issubset(anchor["blockers"])


def test_unknown_replay_and_account_without_statements_are_explicit(rebuild):
    rebuild["evidence"]["files"]["missing"] = {"status": "missing"}
    rebuild["legacy_metadata"]["Accounts"].append(
        {"AccountID": 9, "AccountName": "Empty", "AccountTypeID": 1, "CurrencyCode": "USD"}
    )
    result = build_opening_readiness(*plans(rebuild))
    assert "source_replay_incomplete" in result["anchors"][0]["blockers"]
    assert result["anchors"][-1]["status"] == "no_source_statement"
    assert result["incomplete_source_ids"] == ["missing"]


def test_different_rebuild_binding_is_rejected(rebuild):
    rebuild, candidates = plans(rebuild)
    candidates["rebuild_hash"] = key({"other": True})
    with pytest.raises(LedgerError, match="different rebuilds"):
        build_opening_readiness(rebuild, candidates)


def report_tool():
    path = Path(__file__).resolve().parents[2] / "devtools/ledger_audit/openings.py"
    spec = importlib.util.spec_from_file_location("opening_audit_tool", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.create_report


def test_report_reproduces_and_refuses_overwrite_without_touching_inputs(tmp_path, rebuild):
    plans(rebuild)
    source = accepted_folder(tmp_path, rebuild)
    candidates = tmp_path / "candidates"
    create_candidates(source, candidates)
    snapshots = {p: p.read_bytes() for folder in (source, candidates) for p in folder.iterdir()}
    create_report = report_tool()
    first = create_report(source, candidates, tmp_path / "first")
    assert first == create_report(source, candidates, tmp_path / "second")
    assert (tmp_path / "first/readiness.json").read_bytes() == (tmp_path / "second/readiness.json").read_bytes()
    with pytest.raises(FileExistsError):
        create_report(source, candidates, tmp_path / "first")
    assert all(p.read_bytes() == content for p, content in snapshots.items())


@pytest.mark.parametrize("tamper", ["plan", "database", "active"])
def test_report_refuses_changed_or_active_inputs(tmp_path, rebuild, tamper):
    plans(rebuild)
    source = accepted_folder(tmp_path, rebuild)
    candidates = tmp_path / "candidates"
    create_candidates(source, candidates)
    if tamper == "active":
        (candidates / "candidates.db-wal").touch()
    else:
        target = source / "plan.json" if tamper == "plan" else candidates / "candidates.db"
        with target.open("ab") as f:
            f.write(b"changed")
    with pytest.raises(LedgerError):
        report_tool()(source, candidates, tmp_path / "bad")
    assert not (tmp_path / "bad").exists()
