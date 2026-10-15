"""Read-only bounded proof of the 2.0 source-to-evidence boundary.

This pilot does not activate a catalog, write a profile or approve accounting.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

from parsetrail.core.source_evidence import SourceEvidence

from devtools.parser_engine_pilot.bounded_pdf_text import decode_pdf
from devtools.parser_engine_pilot.card_lines import parse_card_lines
from devtools.parser_engine_pilot.card_source_output import from_card
from devtools.parser_engine_pilot.citi_evidence import read_recent_citi
from devtools.parser_engine_pilot.citi_layout import DEFINITION_SHA256
from devtools.parser_engine_pilot.citi_layout import load_definition as load_citi_definition
from devtools.parser_engine_pilot.citi_source_output import from_citi
from devtools.parser_engine_pilot.engine import parse_csv
from devtools.parser_engine_pilot.pdf_lines import page_lines
from devtools.parser_engine_pilot.savings_lines import parse_savings_lines, parse_summary_savings_lines
from devtools.parser_engine_pilot.table_source_output import from_table

MAX_SOURCE_BYTES = 16 * 1024 * 1024
MAX_DEFINITION_BYTES = 64 * 1024
MAX_EVIDENCE_BYTES = 32 * 1024 * 1024
CHASE_DEFINITION_SHA256 = hashlib.sha256(
    Path(__file__).with_name("chase-card-pilot-definition.json").read_bytes()
).hexdigest()
HAPPEN_DEFINITION_SHA256 = hashlib.sha256(
    Path(__file__).with_name("happen-savings-pilot-definition.json").read_bytes()
).hexdigest()
LENDINGCLUB_DEFINITION_SHA256 = hashlib.sha256(
    Path(__file__).with_name("lendingclub-savings-pilot-definition.json").read_bytes()
).hexdigest()


class SourcePipelineError(ValueError):
    """Redacted refusal before source evidence can be stored."""


def build_source_evidence(source: bytes, definition: bytes, *, suffix: Literal[".csv", ".pdf"]) -> SourceEvidence:
    """Build strict, hash-bound evidence without source/profile writes."""
    if type(source) is not bytes or not 0 < len(source) <= MAX_SOURCE_BYTES:
        raise SourcePipelineError("source_size")
    if type(definition) is not bytes or not 0 < len(definition) <= MAX_DEFINITION_BYTES:
        raise SourcePipelineError("definition_size")
    if suffix not in {".csv", ".pdf"}:
        raise SourcePipelineError("unsupported_source_kind")
    try:
        if suffix == ".csv":
            output = from_table(parse_csv(definition, source))
        else:
            digest = hashlib.sha256(definition).hexdigest()
            if digest == DEFINITION_SHA256:
                load_citi_definition(definition)
                output = from_citi(read_recent_citi(source))
            elif digest in {CHASE_DEFINITION_SHA256, HAPPEN_DEFINITION_SHA256, LENDINGCLUB_DEFINITION_SHA256}:
                decoded = decode_pdf(source)
                lines = page_lines(source, decoded.pages, extraction_library="pdfplumber-bounded-simple-v1")
                if digest == CHASE_DEFINITION_SHA256:
                    output = from_card(parse_card_lines(definition, lines), lines)
                elif digest == HAPPEN_DEFINITION_SHA256:
                    output = parse_savings_lines(definition, lines)
                else:
                    output = parse_summary_savings_lines(definition, lines)
            else:
                raise SourcePipelineError("unsupported_definition_revision")
        if (
            output.source_sha256 != hashlib.sha256(source).hexdigest()
            or output.definition_sha256 != hashlib.sha256(definition).hexdigest()
        ):
            raise SourcePipelineError("source_or_definition_mismatch")
        saved = output.model_dump_json().encode("utf-8")
        if len(saved) > MAX_EVIDENCE_BYTES:
            raise SourcePipelineError("evidence_size")
        return SourceEvidence.model_validate_json(saved)
    except SourcePipelineError:
        raise
    except Exception:
        raise SourcePipelineError("source_evidence_failed") from None
