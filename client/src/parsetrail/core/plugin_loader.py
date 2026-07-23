"""Dynamic plugin loading kept separate from download and trust decisions."""

import importlib.util
from pathlib import Path
from typing import Any

from parsetrail.core.interfaces import IParser, class_variables, validate_parser


def load_plugin(
    plugin_file: Path,
) -> tuple[str, type[IParser], dict[str, str]]:
    """Execute one already-authenticated plugin and return its metadata."""
    plugin_name = plugin_file.stem
    spec = importlib.util.spec_from_file_location(plugin_name, plugin_file)
    if not spec or not spec.loader:
        raise ImportError(f"Cannot load module from {plugin_file}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    parser_class: Any = getattr(module, "Parser", None)
    if not parser_class:
        raise ValueError(f"No 'Parser' class found in {plugin_file}")
    if not isinstance(parser_class, IParser):
        raise TypeError(f"Plugin {plugin_name} must implement IParser")

    required_variables = class_variables(IParser)
    validate_parser(parser_class, required_variables)
    metadata = {var: getattr(parser_class, var) for var in required_variables}
    metadata["FILENAME"] = plugin_file.name
    return plugin_name, parser_class, metadata
