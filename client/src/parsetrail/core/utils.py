import hashlib
import os
import re
import subprocess
import sys
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Tuple, Union
from packaging import version

import pdfplumber
from loguru import logger


class PDFReader:
    def __init__(self, source: Path | bytes | bytearray, name: Path | str | None = None):
        """
        PDF reader that can be backed by a file on disk or in-memory bytes.

        Args:
            source: Path to a PDF or raw PDF bytes/bytearray.
            name: Optional name used for logging/metadata when reading from bytes.
        """
        if isinstance(source, Path):
            self.data = source.read_bytes()
            self.fpath = Path(name) if name else source
        else:
            self.data = bytes(source)
            self.fpath = Path(name) if name else Path("in-memory.pdf")
        self.PDF = None
        self.pages_simple = None
        self.lines_simple = None
        self.text_simple = None
        self.pages_layout = None
        self.text_layout = None
        self.lines_layout = None
        self.lines_clean = None

    def __enter__(self):
        """
        Open the PDF document using context manager.
        """
        self.PDF = pdfplumber.open(BytesIO(self.data))
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """
        Close the PDF document upon exiting the context.
        """
        if self.PDF:
            self.PDF.close()
            self.PDF = None

    def __del__(self):
        """
        Ensure the PDF document is closed when the object is deleted.
        """
        if self.PDF:
            self.PDF.close()

    def extract_text_simple(self) -> str:
        """Extracts text using a fast algoritm for all pages of the pdf.

        Raises:
            ValueError: Error while reading PDF

        Returns:
            str: Entire pdf extracted with simple algorithm, whitespace normalized

        Notes:
            Text is stored as self.text_simple
        """
        if self.text_simple:
            return self.text_simple
        if self.PDF is None:
            raise ValueError("PDF not opened properly")
        self.pages_simple = [page.extract_text_simple() or "" for page in self.PDF.pages]
        text_simple_raw = "\n".join(self.pages_simple)
        self.lines_simple = [" ".join(word for word in line.split()) for line in text_simple_raw.splitlines()]
        self.text_simple = "\n".join(self.lines_simple)
        return self.text_simple

    def extract_lines_simple(self) -> list[str]:
        """Extracts lines of whitespace-normalized text extracted via simple algoritm.

        Returns:
            list[str]: Lines of text with normalized whitespace

        Notes:
            Text is stored as self.text_simple
            Lines are stored as self.lines_simple
        """
        if self.lines_simple:
            return self.lines_simple
        if self.pages_simple is None:
            self.extract_text_simple()
        return self.lines_simple

    def extract_pages_layout(self, **kwargs) -> list[str]:
        """Extracts all pages of text of the PDF using a slower layout-based algorithm.

        Raises:
            ValueError: Error while reading PDF

        Returns:
            list[str]: Pages of layout formatted text

        Notes:
            Pages of layout format text are stored as self.pages_layout
        """
        if self.pages_layout:
            return self.pages_layout
        if self.PDF is None:
            raise ValueError("PDF not opened properly")
        self.pages_layout = [page.extract_text(layout=True, **kwargs) or "" for page in self.PDF.pages]
        return self.pages_layout

    def extract_text_layout(self, **kwargs) -> str:
        """Extracts pages carefully then joins them into a single string.

        Returns:
            str: Joined text in layout format

        Notes:
            Pages of layout format text are stored as self.pages_layout
            Joined text is stored as self.text_layout
        """
        if self.text_layout:
            return self.text_layout
        if self.pages_layout is None:
            self.extract_pages_layout(**kwargs)
        self.text_layout = "\n".join(self.pages_layout)
        return self.text_layout

    def extract_lines_layout(self, **kwargs) -> list[str]:
        """Extracts non-empty lines of text while maintaining layout format.

        Returns:
            list[str]: Non-empty lines of text in layout format

        Notes:
            Pages of layout format text are stored as self.pages_layout
            Joined text is stored as self.text_layout
            Raw lines are stored as self.lines_layout
        """
        if self.lines_layout:
            return self.lines_layout
        if self.text_layout is None:
            self.extract_text_layout(**kwargs)
        self.lines_layout = [line for line in self.text_layout.splitlines() if line.strip()]
        return self.lines_layout

    def extract_lines_clean(self, **kwargs) -> list[str]:
        """Extracts lines of text with normalized whitespace.

        Returns:
            list[str]: Lines of text with normalized whitespace

        Notes:
            Pages of layout format text are stored as self.pages
            Joined text is stored as self.text_layout
            Raw lines are stored as self.lines_layout
            Whitespace normalized lines are stored as self.lines_clean
        """
        if self.lines_clean:
            return self.lines_clean
        if self.lines_layout is None:
            self.extract_lines_layout(**kwargs)
        self.lines_clean = [" ".join(line.split()) for line in self.lines_layout]
        return self.lines_clean


def resource_path(relative_path: str) -> Path:
    """
    PyInstaller >= 6.0 uses sys._MEIPASS to indicate path to bundled binaries.
    For --onefile=True, this is the _MEI* folder created in AppData temp.
    For --onefile=False, this is the _internal folder next to the .exe.
    PyInstaller --add-data places data relative to _MEIPASS.
    """
    base_dir = getattr(sys, "_MEIPASS", None)
    if base_dir is None:
        # Dev mode: Return path relative to client folder
        return Path(__file__).resolve().parents[3] / relative_path
    else:
        # Frozen. Return path relative to _MEIPASS
        return Path(base_dir).resolve() / relative_path


def is_newer_version(local_version, server_version) -> bool:
    """
    Compare local and server versions.

    Args:
        local_version (str): The current local version.
        server_version (str): The version available on the server.

    Returns:
        bool: True if the server version is newer, False otherwise.
    """
    return version.parse(server_version) > version.parse(local_version)


def open_file_in_os(fpath: Path):
    try:
        if not fpath.exists():
            raise FileNotFoundError(f"File not found: {fpath}")

        name = os.name
        if name == "nt":
            subprocess.run(["start", "", str(fpath)], shell=True, check=True)
        elif name == "posix":
            subprocess.run(["open", str(fpath)], check=True)
        else:
            raise ValueError(f"Unsupported OS type: {name}")
    except Exception as e:
        print(f"Error opening {fpath}: {e}")


def create_directory(folder: Path):
    folder = folder.resolve()
    if folder.exists():
        logger.info(f"Directory exists: {folder}")
        return
    try:
        folder.mkdir(parents=True, exist_ok=True)
        logger.info(f"Directory created: {folder}")
    except OSError as e:
        logger.error(f"Error creating directory {folder}: {e}")
        raise


def find_line_startswith(lines: list[str], pattern: str, start: int = 0) -> tuple[int, str]:
    """
    Finds the first line in the list that starts with the given search string.

    Args:
        lines (list[str]): List of lines to search through.
        pattern (str): String to match at the start of the line.
        start (int, optional): Index to start the search from. Defaults to 0.

    Returns:
        tuple[int, str]: A tuple containing the line index and the line content.

    Raises:
        ValueError: If no line starting with the search string is found.
    """
    if not isinstance(lines, list) or not all(isinstance(line, str) for line in lines):
        raise TypeError("Input 'lines' must be a list of strings.")
    if not isinstance(pattern, str):
        raise TypeError("Input 'pattern' must be a string.")
    if not isinstance(start, int) or start < 0:
        raise ValueError("Input 'start' must be a non-negative integer.")

    for i, line in enumerate(lines[start:], start=start):
        if line.startswith(pattern):
            return i, line

    raise ValueError(f"Search string '{pattern}' not found in lines.")


def find_regex_in_line(lines: list[str], pattern: str | re.Pattern) -> tuple[int, str, re.Match]:
    """
    Finds the first line in the list that matches the given regular expression.

    Args:
        lines (list[str]): List of lines to search through.
        pattern (Union[str, re.Pattern]): Regex pattern (string or compiled) to search for.

    Returns:
        Tuple[int, str, str]: A tuple containing the line index, the line content,
                              and the matched pattern.

    Raises:
        ValueError: If no line matches the search string.
        TypeError: If inputs are of incorrect types.
    """
    # Input validation
    if not isinstance(lines, list) or not all(isinstance(line, str) for line in lines):
        raise TypeError("Input 'lines' must be a list of strings.")
    if isinstance(pattern, str):
        pattern = re.compile(pattern)
    if not isinstance(pattern, re.Pattern):
        raise TypeError("Input 'pattern' must be a string or a compiled regex pattern.")

    for i, line in enumerate(lines):
        match = pattern.search(line)
        if match:
            return i, line, match

    raise ValueError(f"Regex pattern '{pattern}' not found in lines.")


def find_param_in_line(lines: list[str], pattern: str, start: int = 0, case_sensitive: bool = True) -> Tuple[int, str]:
    """
    Finds the first line in the list that contains the search string.

    Args:
        lines (list[str]): List of lines to search through.
        pattern (str): The string to search for.
        start (int, optional): The starting index for the search. Defaults to 0.
        case_sensitive (bool, optional): Whether the search is case-sensitive. Defaults to True.

    Returns:
        Tuple[int, str]: A tuple containing the line index and the matching line.

    Raises:
        ValueError: If the search string is not found in any line.
        TypeError: If inputs are of incorrect types.
    """
    # Input validation
    if not isinstance(lines, list) or not all(isinstance(line, str) for line in lines):
        raise TypeError("Input 'lines' must be a list of strings.")
    if not isinstance(pattern, str):
        raise TypeError("Input 'pattern' must be a string.")
    if not isinstance(start, int) or start < 0:
        raise TypeError("Input 'start' must be a non-negative integer.")
    if not isinstance(case_sensitive, bool):
        raise TypeError("Input 'case_sensitive' must be a boolean.")

    for i, line in enumerate(lines[start:], start=start):
        if pattern in line if case_sensitive else pattern.lower() in line.lower():
            return i, line

    raise ValueError(f"Parameter '{pattern}' not found in lines.")


def find_line_re_search(lines: list[str], pattern: Union[str, re.Pattern]) -> tuple[int, str]:
    """
    Finds the first line matching the given regex pattern.

    Args:
        lines (list[str]): List of lines to search through.
        pattern (Union[str, re.Pattern]): Regex pattern (string or compiled) to search for.

    Returns:
        tuple[int, str]: A tuple containing the line index and the matching line.

    Raises:
        ValueError: If the regex pattern is not found in any line.
        TypeError: If inputs are of incorrect types.
    """
    # Input validation
    if not isinstance(lines, list) or not all(isinstance(line, str) for line in lines):
        raise TypeError("Input 'lines' must be a list of strings.")
    if not isinstance(pattern, (str, re.Pattern)):
        raise TypeError("Input 'pattern' must be a string or a compiled regex pattern.")

    # Compile pattern if it's a string
    regex = pattern if isinstance(pattern, re.Pattern) else re.compile(pattern)

    regex = re.compile(pattern)
    for i, line in enumerate(lines):
        if regex.search(line):
            return i, line
    raise ValueError(f"Regex '{pattern}' not found in lines.")


def get_absolute_date(mmdd: str, start_date: datetime, end_date: datetime) -> datetime:
    """
    Convert MM/DD date string to a full datetime object, accounting for year wraparounds.

    Args:
        mmdd (str): Date string in MM/DD format.
        start_date (datetime): Start date of the statement period.
        end_date (datetime): End date of the statement period.

    Returns:
        datetime: The full datetime object for the given MM/DD.
    """
    # Extract start and end years
    statement_days = (end_date - start_date).days
    possible_years = {
        start_date.year,
        start_date.year + 1,
        end_date.year,
        end_date.year - 1,
    }

    # Generate guesses for MM/DD with each possible year
    guesses = []
    for year in possible_years:
        try:
            guesses.append(datetime.strptime(f"{mmdd}/{year}", r"%m/%d/%Y"))
        except ValueError:
            # Probably guessed a leap day for a non-lear year
            continue

    # Find the guess closest to the statement period
    best_guess = min(
        guesses,
        key=lambda date: min(abs((date - start_date).days), abs((date - end_date).days)),
    )

    # Ensure the guess is within a reasonable range
    if abs((best_guess - start_date).days) <= statement_days or abs((best_guess - end_date).days) <= statement_days:
        return best_guess

    raise ValueError(f"Could not resolve a valid date for MM/DD: {mmdd}")


def remove_stop_words(description: str, stop_words=None) -> str:
    """
    Remove spurious words from a description.

    Args:
        description (str): Input description string.
        stop_words (list[str]): List of words to remove (case-insensitive). Defaults to a predefined list.

    Returns:
        str: The cleaned description with stop words removed.
    """
    if stop_words is None:
        stop_words = {"purchase", "pos", "dbt", "recur-purch"}  # , "return"}

    # Filter out stop words
    clean_words = [word for word in description.split() if word.lower() not in stop_words]
    return " ".join(clean_words)


def convert_amount_to_float(amount_str: str) -> float:
    """
    Parses USD amount strings of various formats into positive or negative float.

    Examples:
        $12.34   -> +12.34
        -$12.34  -> -12.34
        ($12.34) -> -12.34
        $12.34CR -> -12.34
        $12.34-  -> -12.34
    """
    # Remove common characters and normalize string
    normalized_str = amount_str.replace(",", "").replace("$", "").replace(" ", "").upper()

    # Determine negativity from indicators
    negative = (
        normalized_str.startswith("-")
        or normalized_str.endswith("-")
        or normalized_str.endswith("CR")
        or (normalized_str.startswith("(") and normalized_str.endswith(")"))
    )

    # Remove negative indicators
    cleaned_str = normalized_str.replace("-", "").replace("CR", "").replace("(", "").replace(")", "")

    # Convert to float and apply negativity if applicable
    amount = float(cleaned_str)
    return -amount if negative else amount


def hash_file(fpath: Path) -> str:
    """
    Hashes the byte contents of a file to prevent duplicate imports.

    Args:
        fpath (Path): The path to the file.

    Returns:
        str: The MD5 hash of the file contents.
    """
    with fpath.open("rb") as f:
        return hashlib.md5(f.read()).hexdigest()
