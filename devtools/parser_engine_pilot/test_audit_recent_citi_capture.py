"""A line-location audit measures gaps without claiming complete page capture."""

from dataclasses import replace

import pytest
from parsetrail.core.source_evidence import PdfLine
from parsetrail.core.v2_citi_source_output import from_citi

from devtools.parser_engine_pilot.audit_recent_citi_capture import line_location_counts
from devtools.parser_engine_pilot.test_citi_source_output import DEFINITION_BYTES, sample


def test_counts_unlocated_text_by_shape_and_refuses_invalid_location() -> None:
    source = replace(
        sample(),
        simple_text_pages=("01/02 01/02 SHOP $10.00\nOffer $2.00\n01/03 OTHER\nFooter",),
    )
    output = from_citi(sample(), DEFINITION_BYTES)
    assert line_location_counts(source, output) == {
        "all_text_lines": 4,
        "line_located": 1,
        "nonblank_text_lines": 4,
        "pages": 1,
        "without_line_location": 3,
        "without_line_location_dated_start": 1,
        "without_line_location_money": 1,
        "without_line_location_other": 1,
    }
    account = output.payload.accounts[0]
    broken = account.model_copy(update={"identity_locations": (PdfLine(kind="pdf_line", page=1, line=5),)})
    payload = output.payload.model_copy(update={"accounts": (broken,)})
    with pytest.raises(ValueError, match="evidence_line_out_of_range"):
        line_location_counts(source, output.model_copy(update={"payload": payload}))
