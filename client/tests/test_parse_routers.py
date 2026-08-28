import tempfile
from pathlib import Path
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


def test_decrypted_devtool_input_parses_when_temp_creation_is_denied(monkeypatch: Any) -> None:
    def deny_temp_file(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("decrypted statement attempted to use temporary storage")

    monkeypatch.setattr(tempfile, "NamedTemporaryFile", deny_temp_file)
    monkeypatch.setattr(tempfile, "TemporaryFile", deny_temp_file)
    monkeypatch.setattr(tempfile, "mkstemp", deny_temp_file)
    monkeypatch.setattr(tempfile, "mkdtemp", deny_temp_file)
    monkeypatch.setattr(Path, "write_bytes", deny_temp_file)

    parse_input = ParseInput.from_decrypted(
        b"marker,value\n1,2\n",
        "encrypted-upload.bin",
        {"filename": "statement.CSV"},
    )
    router = CSVRouter(None, plugin_manager_for(".csv"), parse_input)
    expected = object()
    monkeypatch.setattr(router, "extract_statement", lambda _plugin, _rows: expected)

    assert router.parse() is expected
    assert parse_input.name == "statement.CSV"
    assert parse_input.suffix == ".csv"
    assert parse_input.data == b"marker,value\n1,2\n"
