import csv
from collections.abc import Mapping
from dataclasses import dataclass
from io import BytesIO, StringIO
from pathlib import Path
from typing import Any, Generic, Protocol, TypeVar

import openpyxl
from loguru import logger

from parsetrail.core.interfaces import IParser
from parsetrail.core.parser_classification import (
    DocumentFeatures,
    matching_plugins,
    normalize_pdf_metadata,
)
from parsetrail.core.parser_routing import (
    InvalidPluginSearchError,
    ParseResult,
    ParserOutputError,
    StatementValidationError,
    UnsupportedStatementFormatError,
    raise_execution_error,
    require_unique_candidate,
)
from parsetrail.core.search_expression import SearchExpressionError
from parsetrail.core.search_expression import parse_search_string as parse_search_string
from parsetrail.core.utils import PDFReader
from parsetrail.core.validation import Statement, validate_statement


@dataclass
class ParseInput:
    """Canonical in-memory representation of a statement."""

    name: str
    suffix: str
    data: bytes

    @classmethod
    def from_path(cls, fpath: Path) -> "ParseInput":
        return cls(name=fpath.name, suffix=fpath.suffix.lower(), data=fpath.read_bytes())

    @classmethod
    def from_decrypted(
        cls,
        data: bytes,
        fallback_name: str,
        metadata: dict,
    ) -> "ParseInput":
        """Build a parse input for a decrypted submission without materializing it."""
        metadata_name = metadata.get("filename") or metadata.get("file_name")
        name = metadata_name if isinstance(metadata_name, str) and metadata_name else fallback_name
        suffix = Path(name).suffix or ".bin"
        return cls(name=name, suffix=suffix.lower(), data=data)

    @property
    def path_hint(self) -> Path:
        """Synthetic path used for metadata/logging without touching disk."""
        return Path(self.name)


T = TypeVar("T")


class ParserRegistry(Protocol):
    metadata: Mapping[str, Mapping[str, Any]]

    def get_parser(self, plugin_id: str) -> Any: ...


class BaseRouter(Generic[T]):
    """Provides parser routing logic common to all parsers.

    Args:
        Generic (T): T adopts the type passed to it when a child class inherits this class
    """

    def __init__(
        self,
        plugin_manager: ParserRegistry,
        parse_input: ParseInput,
        path_hint: Path | None = None,
    ):
        self.plugin_manager = plugin_manager
        self.parse_input = parse_input
        # Use the provided hint for metadata/logging; otherwise default to the ParseInput name.
        self.fpath = path_hint or parse_input.path_hint

    def select_parser(self, features: DocumentFeatures) -> str:
        """Require plugin metadata to identify exactly one parser.

        Args:
            features: Normalized in-memory statement features.

        Returns:
            str: The one matching plugin identifier.
        """
        try:
            plugins = matching_plugins(features, self.plugin_manager.metadata)
        except SearchExpressionError as exc:
            raise InvalidPluginSearchError("plugin catalog") from exc
        return require_unique_candidate(plugins, suffix=features.suffix)

    def extract_statement(self, plugin_name: str, input_data: T) -> ParseResult:
        """Dynamically loads and runs the parser to extract the statement data."""
        try:
            parser_class = self.plugin_manager.get_parser(plugin_name)
            statement = self.run_parser(plugin_name, parser_class, input_data)
        except ParserOutputError:
            raise
        except Exception as exc:
            raise_execution_error(plugin_name, exc)

        # Make sure all balances are populated
        for account in statement.accounts:
            account.sort_and_compute_balances()

        # Attach parser metadata
        statement.add_metadata(self.fpath, plugin_name)

        # Validate without importing or invoking any UI adapter.
        report = validate_statement(statement)
        diagnostics = tuple(item.for_plugin(plugin_name) for item in report.diagnostics)
        if report.errors:
            logger.error("Parser {} produced {} validation error(s).", plugin_name, len(report.errors))
            raise StatementValidationError(plugin_name, diagnostics)
        return ParseResult(statement=statement, plugin_name=plugin_name, diagnostics=diagnostics)

    def run_parser(self, plugin_name: str, parser: IParser, input_data: T) -> Statement:
        """
        Run the parser and enforce return type.

        Args:
            parser (IParser): The parser class that must conform to IParser.
            input_data (T): Input data (e.g., PDFReader, CSV array, etc.).

        Returns:
            Statement: The parsed statement data.
        """
        result = parser().parse(input_data)
        if not isinstance(result, Statement):
            raise ParserOutputError(plugin_name)
        return result


class PDFRouter(BaseRouter[PDFReader]):
    """_summary_

    Args:
        BaseRouter (PDFReader): _description_
    """

    def __init__(
        self,
        plugin_manager: ParserRegistry,
        parse_input: ParseInput,
        path_hint: Path | None = None,
    ):
        super().__init__(plugin_manager, parse_input, path_hint=path_hint)

    def parse(self) -> ParseResult:
        """Opens the PDF file, determines its type, and routes its reader
        to the appropriate parsing module.

        Returns:
            Statement: Statement contents in the dataclass
        """
        with PDFReader(self.parse_input.data, self.fpath) as reader:
            text = reader.extract_text_simple()
            header = "\n".join(
                " ".join(line.split()) for page in (reader.pages_simple or []) for line in page.splitlines()[:40]
            )
            features = DocumentFeatures(
                suffix=".pdf",
                body_text=text,
                header_text=header,
                pdf_metadata=normalize_pdf_metadata(reader.PDF.metadata),
                page_count=len(reader.PDF.pages),
            )
            plugin = self.select_parser(features)
            return self.extract_statement(plugin, reader)


class CSVRouter(BaseRouter[list[list[str]]]):
    ENCODING = "utf-8-sig"

    def __init__(
        self,
        plugin_manager: ParserRegistry,
        parse_input: ParseInput,
        path_hint: Path | None = None,
    ):
        super().__init__(plugin_manager, parse_input, path_hint=path_hint)

    def parse(self) -> ParseResult:
        """Opens the CSV file, determines its type, and routes its contents
        to the appropriate parsing script.

        Returns:
            Statement: Statement contents in the dataclass
        """
        # Get the raw data from the csv
        text = self.read_csv_as_text()
        array = self.read_csv_as_array()

        # Extract the statement data
        features = DocumentFeatures(
            suffix=".csv",
            body_text=text,
            header_text="\n".join(text.splitlines()[:25]),
        )
        plugin = self.select_parser(features)
        return self.extract_statement(plugin, array)

    def read_csv_as_text(self) -> str:
        """Reads the CSV file and returns its contents as plain text."""
        return self.parse_input.data.decode(self.ENCODING)

    def read_csv_as_array(self) -> list[list[str]]:
        """Reads the CSV file and returns its contents as a list of rows."""
        reader = csv.reader(StringIO(self.read_csv_as_text()))
        return list(reader)


class XLSXRouter(BaseRouter):
    def __init__(
        self,
        plugin_manager: ParserRegistry,
        parse_input: ParseInput,
        path_hint: Path | None = None,
    ):
        super().__init__(plugin_manager, parse_input, path_hint=path_hint)

    def parse(self) -> ParseResult:
        """Opens the XLSX file, determines its type, and routes its contents
        to the appropriate parsing script.

        Returns:
            Statement: Statement contents in the dataclass
        """
        sheets = self.read_xlsx()
        text = self.plain_text(sheets)
        features = DocumentFeatures(
            suffix=".xlsx",
            body_text=text,
            header_text="\n".join(text.splitlines()[:25]),
        )
        plugin = self.select_parser(features)
        return self.extract_statement(plugin, sheets)

    def plain_text(self, sheets) -> str:
        """Convert all workbook data to plaintext"""
        text = "\n".join(
            "\n".join(", ".join(str(cell) for cell in row if cell) for row in sheet) for sheet in sheets.values()
        )
        return text

    def read_xlsx(self) -> dict[str, list]:
        """Load the worksheets, skipping any blank rows"""
        workbook = openpyxl.load_workbook(BytesIO(self.parse_input.data))
        sheets = {sheet.title: [row for row in sheet.values if any(row)] for sheet in workbook.worksheets}
        return sheets


# Router registration framework
ROUTERS: dict[str, type[BaseRouter]] = {}


def register_router(suffix: str, router_class: type[BaseRouter]):
    ROUTERS[suffix] = router_class


# Add more routers here as they are developed
register_router(".pdf", PDFRouter)
register_router(".csv", CSVRouter)
register_router(".xlsx", XLSXRouter)


def parse_any(plugin_manager: ParserRegistry, source: Path | ParseInput) -> ParseResult:
    """Routes the file (on disk or in memory) to the appropriate parser based on its suffix.

    Args:
        plugin_manager: Loaded parser registry.
        source (Path | ParseInput): Statement data to be parsed

    Raises:
        UnsupportedStatementFormatError: Unsupported file suffix.

    Returns:
        ParseResult: Parsed statement and redacted validation diagnostics.
    """
    if isinstance(source, ParseInput):
        parse_input = source
        path_hint: Path | None = None
    elif isinstance(source, Path):
        path_hint = source
        parse_input = ParseInput.from_path(source)
    else:
        raise TypeError(f"Unsupported source type: {type(source).__name__}")

    suffix = parse_input.suffix.lower()
    if suffix in ROUTERS:
        router = ROUTERS[suffix](plugin_manager, parse_input, path_hint=path_hint)
        return router.parse()
    raise UnsupportedStatementFormatError(suffix)
