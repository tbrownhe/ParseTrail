"""Dynamic plugin loading kept separate from download and trust decisions."""

import importlib.util
import re
from pathlib import Path
from typing import Any

from parsetrail.core.interfaces import IParser, class_variables, validate_parser
from parsetrail.core.parser_classification import ROUTING_RULE_FIELD, validate_routing_metadata

PLUGIN_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


def load_plugin(
    plugin_file: Path,
) -> tuple[str, type[IParser], dict[str, Any]]:
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
    routing_rule = getattr(parser_class, ROUTING_RULE_FIELD, None)
    if routing_rule is not None:
        metadata[ROUTING_RULE_FIELD] = routing_rule
    declared_name = metadata["PLUGIN_NAME"]
    if not PLUGIN_NAME_PATTERN.fullmatch(declared_name):
        raise ValueError(f"Plugin declares an unsafe PLUGIN_NAME: {declared_name!r}")
    if declared_name != plugin_file.stem:
        raise ValueError(f"Plugin PLUGIN_NAME {declared_name!r} must match its filename stem {plugin_file.stem!r}")
    validate_routing_metadata(metadata)
    metadata["FILENAME"] = plugin_file.name
    return plugin_name, parser_class, metadata
