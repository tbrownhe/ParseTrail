"""Citi's finite pilot declaration refuses unsupported operations."""

import json

import pytest
from parsetrail.core.v2_citi_layout import CitiLayoutError, load_definition

from devtools.parser_engine_pilot.citi_authoring import DEFINITION_BYTES


def test_checked_in_definition_is_strict() -> None:
    definition, digest = load_definition(DEFINITION_BYTES)
    assert definition.table_continuation.mode == "amount_with_details"
    assert len(digest) == 64
    changed = json.loads(DEFINITION_BYTES)
    changed["unknown_hook"] = "run-code"
    with pytest.raises(CitiLayoutError, match="invalid_definition"):
        load_definition(json.dumps(changed).encode())
    changed.pop("unknown_hook")
    changed["geometry_operation"] = "downloaded_python"
    with pytest.raises(CitiLayoutError, match="invalid_definition"):
        load_definition(json.dumps(changed).encode())
