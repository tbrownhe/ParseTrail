import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from parsetrail.core.parse import CSVRouter, ParseInput, PDFRouter, XLSXRouter
from parsetrail.core.parser_routing import AmbiguousParserMatchError


def plugin_manager_for(suffix: str, *, ambiguous: bool = False) -> Any:
    metadata = {"only": {"SUFFIX": suffix, "SEARCH_STRING": "marker"}}
    if ambiguous:
        metadata["also"] = {"SUFFIX": suffix, "SEARCH_STRING": "marker"}
    return SimpleNamespace(metadata=metadata)


def test_csv_router_uses_the_unique_matching_parser(monkeypatch: Any) -> None:
    router = CSVRouter(
        plugin_manager_for(".csv"),
        ParseInput(name="statement.csv", suffix=".csv", data=b"marker,value\n1,2\n"),
    )
    expected = object()
    attempted: list[str] = []

    def extract(plugin: str, rows: list[list[str]]) -> object:
        attempted.append(plugin)
        assert rows == [["marker", "value"], ["1", "2"]]
        assert plugin == "only"
        return expected

    monkeypatch.setattr(router, "extract_statement", extract)

    assert router.parse() is expected
    assert attempted == ["only"]


def test_xlsx_router_uses_the_unique_matching_parser(monkeypatch: Any) -> None:
    router = XLSXRouter(
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
        assert plugin == "only"
        return expected

    monkeypatch.setattr(router, "extract_statement", extract)

    assert router.parse() is expected
    assert attempted == ["only"]


def test_csv_router_rejects_ambiguous_metadata_before_running_a_parser(monkeypatch: Any) -> None:
    router = CSVRouter(
        plugin_manager_for(".csv", ambiguous=True),
        ParseInput(name="statement.csv", suffix=".csv", data=b"marker,value\n1,2\n"),
    )
    monkeypatch.setattr(
        router,
        "extract_statement",
        lambda *_args: pytest.fail("an ambiguous route must not execute a parser"),
    )

    with pytest.raises(AmbiguousParserMatchError):
        router.parse()


def test_pdf_router_builds_features_without_a_display_server(monkeypatch: Any) -> None:
    class FakeReader:
        def __init__(self, _data: bytes, _path: Path):
            self.pages_simple = ["Marker header\nOther text"]
            self.PDF = SimpleNamespace(metadata={"Creator": "Fixture"}, pages=[object()])

        def __enter__(self):
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def extract_text_simple(self) -> str:
            return "Marker header\nOther text"

    monkeypatch.setattr("parsetrail.core.parse.PDFReader", FakeReader)
    router = PDFRouter(
        plugin_manager_for(".pdf"),
        ParseInput(name="statement.pdf", suffix=".pdf", data=b"fixture"),
    )
    expected = object()
    monkeypatch.setattr(router, "extract_statement", lambda plugin, _reader: (plugin, expected))

    assert router.parse() == ("only", expected)


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
    router = CSVRouter(plugin_manager_for(".csv"), parse_input)
    expected = object()
    monkeypatch.setattr(router, "extract_statement", lambda _plugin, _rows: expected)

    assert router.parse() is expected
    assert parse_input.name == "statement.CSV"
    assert parse_input.suffix == ".csv"
    assert parse_input.data == b"marker,value\n1,2\n"
