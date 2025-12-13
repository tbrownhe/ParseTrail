from typing import Any, Protocol, runtime_checkable

from parsetrail.core.validation import Statement, ValidationError


@runtime_checkable
class IParser(Protocol):
    """Enforces consistent design inputs and outputs for all parsers.
    Class variables listed here must all be overridden by individual parsers.
    Validation during plugin import will refuse empty strings.

    Args:
        input_data (Any): The data to parse (PDFReader, CSV array, XLSX sheets, etc.).

    Returns:
        Statement: The parsed statement data.
    """

    # Plugin metadata
    PLUGIN_NAME = ""
    VERSION = ""
    SUFFIX = ""
    COMPANY = ""
    STATEMENT_TYPE = ""
    SEARCH_STRING = ""
    INSTRUCTIONS = ""

    def parse(self, input_data: Any) -> Statement:
        raise ValidationError(
            "All children of IParser must override the parse() method and return type validation.Statement"
        )


def class_variables(cls):
    """
    Retrieve all required class variable names from the interface.
    """
    return [
        name
        for name in dir(cls)
        if not callable(getattr(cls, name)) and not name.startswith("_") and isinstance(name, str)
    ]


def validate_parser(ParserClass, required_variables):
    """
    Validate that all required class variables in the parser are non-empty strings.
    """
    errors = []
    for var_name in required_variables:
        value = getattr(ParserClass, var_name, None)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"Variable '{var_name}' is missing or invalid (value: {value!r})")
    if errors:
        raise ValueError(f"Validation errors in parser '{ParserClass.__name__}':\n" + "\n".join(errors))
