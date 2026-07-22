from types import SimpleNamespace
from typing import Any

from parsetrail.core.parse import CSVRouter, ParseInput, XLSXRouter


def plugin_manager_for(suffix: str) -> Any:
    return SimpleNamespace(
        metadata={
            "first": {"SUFFIX": suffix, "SEARCH_STRING": "marker"},
            "second": {"SUFFIX": suffix, "SEARCH_STRING": "marker"},
        }
    )


def test_csv_router_tries_each_matching_parser(monkeypatch: Any) -> None:
    router = CSVRouter(
        None,
        plugin_manager_for(".csv"),
        ParseInput(name="statement.csv", suffix=".csv", data=b"marker,value\n1,2\n"),
    )
    expected = object()
    attempted: list[str] = []

    def extract(plugin: str, rows: list[list[str]]) -> object:
        attempted.append(plugin)
        assert rows == [["marker", "value"], ["1", "2"]]
        if plugin == "first":
            raise ValueError("wrong CSV layout")
        return expected

    monkeypatch.setattr(router, "extract_statement", extract)

    assert router.parse() is expected
    assert attempted == ["first", "second"]


def test_xlsx_router_tries_each_matching_parser(monkeypatch: Any) -> None:
    router = XLSXRouter(
        None,
        plugin_manager_for(".xlsx"),
        ParseInput(name="statement.xlsx", suffix=".xlsx", data=b"unused"),
    )
    sheets = {"Sheet1": [("marker", "value")]}
    expected = object()
    attempted: list[str] = []

    monkeypatch.setattr(router, "read_xlsx", lambda: sheets)

    def extract(plugin: str, workbook_data: dict[str, list]) -> object:
        attempted.append(plugin)
        assert workbook_data is sheets
        if plugin == "first":
            raise ValueError("wrong XLSX layout")
        return expected

    monkeypatch.setattr(router, "extract_statement", extract)

    assert router.parse() is expected
    assert attempted == ["first", "second"]
