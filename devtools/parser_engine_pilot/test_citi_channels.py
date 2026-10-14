"""Source-channel decisions that a coarse date/amount match cannot make."""

from __future__ import annotations

from datetime import date

import pytest

from devtools.parser_engine_pilot.citi_channels import Candidate, CitiChannelError, resolve

DAY = date(2026, 8, 2)


def row(description: str, amount: int, channel: str, line: int, page: int = 3) -> Candidate:
    return Candidate(DAY, DAY, amount, description, channel, page, line)


def test_pairs_copies_and_keeps_a_real_duplicate_and_text_only_rows() -> None:
    table = [row("N-N OUT", -100, "table", 1), row("REPEATED", -200, "table", 2)]
    text = [
        row("IN-N OUT", -100, "text", 10),
        row("08/02", -100, "text", 11),
        row("REPEATED", -200, "text", 12),
        row("REPEATED", -200, "text", 13),
        row("PAYMENT", 500, "text", 14),
    ]
    fee = row("FEE", -25, "fee", 20, 4)
    result = resolve(table, text, [fee], opening_minor=-1000, closing_minor=-1025)
    assert [(item.representative.description, item.disposition) for item in result.rows] == [
        ("IN-N OUT", "table"),
        ("REPEATED", "table"),
        ("REPEATED", "additional_text_occurrence"),
        ("PAYMENT", "text_only"),
        ("FEE", "fee"),
    ]
    assert len(result.rows[0].sources) == 2
    assert [item.line for item in result.incomplete_text_copies] == [11]
    assert result.first_character_corrections == 1
    assert result.balance_reconciled


def test_refuses_unexplained_overlap_or_unbalanced_candidate_set() -> None:
    table = [row("STORE A", -100, "table", 1)]
    with pytest.raises(CitiChannelError, match="unresolved_text_overlap"):
        resolve(table, [row("STORE B", -100, "text", 2)], [], opening_minor=0, closing_minor=-100)
    with pytest.raises(CitiChannelError, match="balance_mismatch"):
        resolve(table, [row("STORE A", -100, "text", 2)], [], opening_minor=0, closing_minor=-200)
    with pytest.raises(CitiChannelError, match="unresolved_text_overlap"):
        resolve([], [row("08/02", -100, "text", 2)], [], opening_minor=0, closing_minor=0)


def test_refuses_duplicate_location_and_fee_overlap() -> None:
    table = [row("STORE", -100, "table", 1)]
    with pytest.raises(CitiChannelError, match="duplicate_source_location"):
        resolve(table, [row("STORE", -100, "text", 2)] * 2, [], opening_minor=0, closing_minor=-100)
    with pytest.raises(CitiChannelError, match="fee_overlap"):
        resolve(table, [], [row("FEE", -100, "fee", 3)], opening_minor=0, closing_minor=-200)
