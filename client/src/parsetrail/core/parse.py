import csv
import re
from dataclasses import dataclass
from io import BytesIO, StringIO
from pathlib import Path
from typing import Generic, TypeVar

import openpyxl
from loguru import logger
from sqlalchemy.orm import sessionmaker

from parsetrail.core.interfaces import IParser
from parsetrail.core.plugins import PluginManager
from parsetrail.core.utils import PDFReader
from parsetrail.core.validation import Statement, ValidationError, validate_statement
from parsetrail.gui.statements import ValidationErrorDialog


@dataclass
class ParseInput:
    """Canonical in-memory representation of a statement."""

    name: str
    suffix: str
    data: bytes

    @classmethod
    def from_path(cls, fpath: Path) -> "ParseInput":
        return cls(name=fpath.name, suffix=fpath.suffix.lower(), data=fpath.read_bytes())

    @property
    def path_hint(self) -> Path:
        """Synthetic path used for metadata/logging without touching disk."""
        return Path(self.name)


def parse_search_string(search_string: str):
    """
    Parses the SEARCH_STRING into a logical tree structure.

    Args:
        search_string (str): The SEARCH_STRING from the plugin metadata.

    Returns:
        tuple: A tree-like structure representing the parsed logical expression.
    """

    def tokenize(expr: str) -> list[str]:
        return re.findall(r'&&|\|\||\(|\)|"[^"]*"|[^()&|]+', expr.lower())

    def build_tree(tokens: list[str]):
        stack = []
        current = []

        for token in tokens:
            if token == "(":
                stack.append(current)
                current = []
            elif token == ")":
                if not stack:
                    raise ValueError("Unmatched closing parenthesis")
                last = current
                current = stack.pop()
                current.append(last)
            elif token in ("&&", "||"):
                current.append(token)
            else:
                current.append(token)

        if stack:
            raise ValueError("Unmatched opening parenthesis")
        return current

    tokens = tokenize(search_string)
    return build_tree(tokens)


def evaluate_tree(tokens: list[str], text: str):
    """
    Evaluate a tokenized search string against the input text.

    Args:
        tokens (list): Tokenized search string.
        text (str): Text to evaluate against.

    Returns:
        bool: True if the search string matches the text, False otherwise.

    Raises:
        ValueError: If the expression is malformed or an unknown token is encountered.
    """
    text = text.lower()
    stack = []
    while tokens:
        token = tokens.pop(0)

        if token == "&&":
            # Evaluate both sides of the AND operation
            if len(stack) < 1:
                raise ValueError("Malformed expression: missing left operand for '&&'")
            left = stack.pop()
            right = evaluate_tree(tokens, text)  # Process the right side
            stack.append(left and right)
        elif token == "||":
            # Evaluate both sides of the OR operation
            if len(stack) < 1:
                raise ValueError("Malformed expression: missing left operand for '||'")
            left = stack.pop()
            right = evaluate_tree(tokens, text)  # Process the right side
            stack.append(left or right)
        elif isinstance(token, list):
            # Handle nested expressions
            stack.append(evaluate_tree(token, text))
        else:
            # Treat the token as a literal string
            result = token in text
            stack.append(result)

    if len(stack) != 1:
        raise ValueError(f"Malformed expression. Final Stack: {stack}")
    return stack[0]


def match_search_string(search_string: str, text: str) -> bool:
    """
    Matches the search string logic against the text.

    Args:
        search_string (str): The SEARCH_STRING from the plugin metadata.
        text (str): The plain text of the statement.

    Returns:
        bool: True if the text matches the search string, False otherwise.
    """
    try:
        tree = parse_search_string(search_string)
        return evaluate_tree(tree, text)
    except ValueError as e:
        raise ValueError(f"Error in SEARCH_STRING '{search_string}': {e}")


T = TypeVar("T")


class BaseRouter(Generic[T]):
    """Provides parser routing logic common to all parsers.

    Args:
        Generic (T): T adopts the type passed to it when a child class inherits this class
    """

    def __init__(
        self,
        Session: sessionmaker,
        plugin_manager: PluginManager,
        parse_input: ParseInput,
        path_hint: Path | None = None,
        hard_fail=True,
    ):
        self.Session = Session
        self.plugin_manager = plugin_manager
        self.parse_input = parse_input
        # Use the provided hint for metadata/logging; otherwise default to the ParseInput name.
        self.fpath = path_hint or parse_input.path_hint
        self.hard_fail = hard_fail

    def select_parser(self, text: str, suffix="") -> list[str]:
        """Uses plugin metadata to find the parser name for this statement.

        Args:
            text (str): Plaintext contents of statement
            suffix (str, optional): suffix of statement file. Defaults to "".

        Raises:
            ValueError: Statement is not recognized. A parser likely needs to be built.

        Returns:
            str: Plugin name (e.g., 'pdf_citibank')
        """
        plugins = []
        for plugin_name, metadata in self.plugin_manager.metadata.items():
            if suffix and metadata["SUFFIX"] != suffix:
                continue
            search_string = metadata["SEARCH_STRING"]
            if match_search_string(search_string, text):
                plugins.append(plugin_name)
        if not plugins:
            raise ValueError("Statement type not recognized.")
        if len(plugins) > 1:
            logger.debug(f"Found {len(plugins)} matching plugins.")
        return plugins

    def extract_statement(self, plugin_name: str, input_data: T) -> Statement:
        """Dynamically loads and runs the parser to extract the statement data."""
        ParserClass = self.plugin_manager.get_parser(plugin_name)
        statement = self.run_parser(ParserClass, input_data)

        # Make sure all balances are populated
        for account in statement.accounts:
            account.sort_and_compute_balances()

        # Attach parser metadata
        statement.add_metadata(self.fpath, plugin_name)

        # Validate and return statement data
        errors = validate_statement(statement)
        if errors:
            err = "\n".join(errors)
            logger.error(f"Validation failed for statement imported using parser '{plugin_name}':\n{err}")

            # Show validation error dialog
            dialog = ValidationErrorDialog(statement, errors)
            dialog.exec_()

            raise ValidationError(err)
        return statement

    def run_parser(self, parser: IParser, input_data: T) -> Statement:
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
            raise TypeError(f"{parser.__name__} did not return a Statement. Check its parse() method.")
        return result


class PDFRouter(BaseRouter[PDFReader]):
    """_summary_

    Args:
        BaseRouter (PDFReader): _description_
    """

    def __init__(
        self,
        Session: sessionmaker,
        plugin_manager: PluginManager,
        parse_input: ParseInput,
        path_hint: Path | None = None,
        **kwargs,
    ):
        super().__init__(Session, plugin_manager, parse_input, path_hint=path_hint, **kwargs)

    def parse(self) -> Statement:
        """Opens the PDF file, determines its type, and routes its reader
        to the appropriate parsing module.

        Returns:
            Statement: Statement contents in the dataclass
        """
        with PDFReader(self.parse_input.data, self.fpath) as reader:
            text = reader.extract_text_simple()
            plugins = self.select_parser(text, suffix=".pdf")

            errs = []
            for i, plugin in enumerate(plugins):
                try:
                    return self.extract_statement(plugin, reader)
                except Exception as e:
                    errs.append(f"{plugin}: {e}")
                    if i < len(plugins) - 1:
                        continue
                    else:
                        err = "; ".join(errs)
                        logger.debug(f"Failed to parse {self.fpath}: {err}")
                        raise ValueError(f"Failed to parse {self.fpath}: {err}")


class CSVRouter(BaseRouter[list[list[str]]]):
    ENCODING = "utf-8-sig"

    def __init__(
        self,
        Session: sessionmaker,
        plugin_manager: PluginManager,
        parse_input: ParseInput,
        path_hint: Path | None = None,
        **kwargs,
    ):
        super().__init__(Session, plugin_manager, parse_input, path_hint=path_hint, **kwargs)

    def parse(self) -> Statement:
        """Opens the CSV file, determines its type, and routes its contents
        to the appropriate parsing script.

        Returns:
            Statement: Statement contents in the dataclass
        """
        # Get the raw data from the csv
        text = self.read_csv_as_text()
        array = self.read_csv_as_array()

        # Extract the statement data
        plugin_name = self.select_parser(text, suffix=".csv")
        statement = self.extract_statement(plugin_name, array)
        return statement

    def read_csv_as_text(self) -> str:
        """Reads the CSV file and returns its contents as plain text."""
        return self.parse_input.data.decode(self.ENCODING)

    def read_csv_as_array(self) -> list[list[str]]:
        """Reads the CSV file and returns its contents as a list of rows."""
        reader = csv.reader(StringIO(self.read_csv_as_text()))
        return [row for row in reader]


class XLSXRouter(BaseRouter):
    def __init__(
        self,
        Session: sessionmaker,
        plugin_manager: PluginManager,
        parse_input: ParseInput,
        path_hint: Path | None = None,
        **kwargs,
    ):
        super().__init__(Session, plugin_manager, parse_input, path_hint=path_hint, **kwargs)

    def parse(self) -> Statement:
        """Opens the XLSX file, determines its type, and routes its contents
        to the appropriate parsing script.

        Returns:
            Statement: Statement contents in the dataclass
        """
        sheets = self.read_xlsx()
        text = self.plain_text(sheets)
        plugin_name = self.select_parser(text, suffix=".xlsx")
        statement = self.extract_statement(plugin_name, sheets)
        return statement

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


def parse_any(Session: sessionmaker, plugin_manager: PluginManager, source: Path | ParseInput, **kwargs) -> Statement:
    """Routes the file (on disk or in memory) to the appropriate parser based on its suffix.

    Args:
        db_path (Path): Path to database file
        source (Path | ParseInput): Statement data to be parsed

    Raises:
        ValueError: Unsupported file suffix

    Returns:
        tuple[dict[str, Any], dict[str, list[tuple]]]: metadata and data dicts
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
        router = ROUTERS[suffix](Session, plugin_manager, parse_input, path_hint=path_hint, **kwargs)
        return router.parse()
    raise ValueError(f"Unsupported file suffix: {suffix}")
