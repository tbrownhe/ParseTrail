"""Checked-in recent Citi example for development comparisons and tests."""

from __future__ import annotations

from pathlib import Path

from parsetrail.core.v2_citi_layout import load_definition

DEFINITION_BYTES = Path(__file__).with_name("recent-citi-pilot-definition.json").read_bytes()
DEFINITION, DEFINITION_SHA256 = load_definition(DEFINITION_BYTES)
