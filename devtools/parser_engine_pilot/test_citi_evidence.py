"""Standalone recent-Citi evidence path refuses a non-Citi PDF."""

import pytest
from parsetrail.core.runtime_smoke import _sample_pdf

from devtools.parser_engine_pilot.citi_evidence import CitiEvidenceError, read_recent_citi
from devtools.parser_engine_pilot.citi_layout import DEFINITION_BYTES


def test_refuses_wrong_layout_before_citi_table_extraction() -> None:
    with pytest.raises(CitiEvidenceError, match="wrong_or_ambiguous_citi_layout"):
        read_recent_citi(_sample_pdf(), DEFINITION_BYTES)
