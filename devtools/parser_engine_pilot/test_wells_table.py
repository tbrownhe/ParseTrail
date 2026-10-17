"""Synthetic geometry, row-disposition and refusal cases for the Wells pilot."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest
from parsetrail.core.v2_wells_table import (
    WellsTableDefinition,
    WellsTableError,
    extract_table_rows,
)

DEFINITION = Path(__file__).with_name("wells-table-pilot-definition.json")


@dataclass
class FakeRow:
    bbox: tuple[float, float, float, float]


class FakeTable:
    def __init__(self, cells: list[list[str | None]]):
        self.cells = cells
        self.rows = [FakeRow((7, 20 + i * 10, 302, 30 + i * 10)) for i in range(len(cells))]

    def extract(self):
        return self.cells


class FakePage:
    width = 320
    height = 400

    def __init__(self, cells: list[list[str | None]], *, duplicate_header: bool = False):
        self.cells = cells
        self.duplicate_header = duplicate_header

    def extract_words(self):
        words = [
            {"text": name, "x0": x0, "x1": x1, "top": 10, "bottom": 12}
            for name, x0, x1 in (
                ("Date", 10, 22),
                ("Description", 60, 120),
                ("Credits", 160, 200),
                ("Debits", 220, 260),
                ("balance", 280, 300),
            )
        ]
        if self.duplicate_header:
            words.append({"text": "Date", "x0": 12, "x1": 24, "top": 10, "bottom": 12})
        return words

    def crop(self, region):
        assert region == (7, 12.1, 302, 400)
        return self

    def find_table(self, *, table_settings):
        assert table_settings["vertical_strategy"] == "explicit"
        assert table_settings["horizontal_strategy"] == "text"
        assert len(table_settings["explicit_vertical_lines"]) == 7
        return FakeTable(self.cells)


def cells() -> list[list[str | None]]:
    return [
        ["1/1", "", "Printed description", "$1.00", "", "$101.00"],
        ["", "", "continuation", "", "", ""],
        ["", "", "", "", "", ""],
        ["Summary", "", "Other section", "", "", ""],
    ]


def parse(pages=None, *, definition=None, cancelled=None):
    return extract_table_rows(
        definition if definition is not None else DEFINITION.read_bytes(),
        b"%PDF-synthetic",
        pages if pages is not None else [FakePage(cells())],
        extraction_library="synthetic-pdf-1",
        cancelled=cancelled,
    )


def test_regions_and_every_table_row_have_explicit_disposition() -> None:
    evidence = parse()
    assert [row.disposition for row in evidence.rows] == [
        "dated_candidate",
        "description_continuation",
        "terminator",
        "unresolved_after_stop",
    ]
    assert evidence.rows[0].raw_cells[3] == "$1.00"
    assert evidence.rows[0].region == (7, 20, 302, 30)
    assert evidence.pages[0].vertical_lines == (7, 24, 58, 157, 202, 262, 302)
    assert evidence.coverage_verified is False and evidence.account_balance_reconciled is False
    changed = json.loads(DEFINITION.read_bytes())
    changed["revision"] = "2"
    assert parse(definition=json.dumps(changed).encode()).rows[0].row_id != evidence.rows[0].row_id


def test_ambiguous_header_and_post_stop_dated_row_fail() -> None:
    with pytest.raises(WellsTableError, match="ambiguous_header_words"):
        parse([FakePage(cells(), duplicate_header=True)])
    changed = cells()
    changed[-1][0] = "1/2"
    with pytest.raises(WellsTableError, match="dated_row_after_stop"):
        parse([FakePage(changed)])
    changed = cells()
    changed[0][0] = "Unrecognized"
    with pytest.raises(WellsTableError, match="unresolved_table_row"):
        parse([FakePage(changed)])


def test_definition_schema_and_cancellation() -> None:
    saved = json.loads(Path(__file__).with_name("wells-table-declaration-schema-v1.json").read_text(encoding="utf-8"))
    assert saved == WellsTableDefinition.model_json_schema()
    assert saved["additionalProperties"] is False
    changed = json.loads(DEFINITION.read_bytes())
    changed["python"] = "import os"
    with pytest.raises(WellsTableError, match="invalid_definition"):
        parse(definition=json.dumps(changed).encode())
    with pytest.raises(WellsTableError, match="cancelled"):
        parse(cancelled=lambda: True)
