"""Read-only bounded proof of the 2.0 source-to-evidence boundary.

This pilot does not activate a catalog, write a profile or approve accounting.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

from parsetrail.core.source_evidence import SourceEvidence

from devtools.parser_engine_pilot.bounded_anchored_table import extract_bounded_anchored_table
from devtools.parser_engine_pilot.bounded_pdf_annotations import decode_pdf_period_annotations
from devtools.parser_engine_pilot.bounded_pdf_text import decode_pdf, decode_pdf_default_layout, decode_pdf_layout
from devtools.parser_engine_pilot.bounded_wells import extract_bounded_wells
from devtools.parser_engine_pilot.card_lines import parse_card_lines
from devtools.parser_engine_pilot.card_source_output import from_card
from devtools.parser_engine_pilot.citi_evidence import read_recent_citi
from devtools.parser_engine_pilot.citi_layout import DEFINITION_SHA256
from devtools.parser_engine_pilot.citi_layout import load_definition as load_citi_definition
from devtools.parser_engine_pilot.citi_source_output import from_citi
from devtools.parser_engine_pilot.dual_text_card_lines import parse_dual_text_card
from devtools.parser_engine_pilot.engine import parse_csv
from devtools.parser_engine_pilot.investment_summary_lines import parse_investment_summary
from devtools.parser_engine_pilot.legacy_citi_lines import parse_legacy_citi
from devtools.parser_engine_pilot.loan_history_lines import parse_loan_history
from devtools.parser_engine_pilot.occu_bank_lines import OccuBankError, parse_occu_bank
from devtools.parser_engine_pilot.occu_card_lines import parse_occu_card
from devtools.parser_engine_pilot.pdf_lines import page_lines
from devtools.parser_engine_pilot.savings_lines import parse_savings_lines, parse_summary_savings_lines
from devtools.parser_engine_pilot.single_column_summary import parse_plan_label_summary, parse_single_column_summary
from devtools.parser_engine_pilot.table_bank_source_output import from_anchored_bank
from devtools.parser_engine_pilot.table_card_source_output import from_anchored_card
from devtools.parser_engine_pilot.table_source_output import from_table
from devtools.parser_engine_pilot.two_date_card_lines import parse_two_date_card
from devtools.parser_engine_pilot.wells_statement_output import from_wells_business

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
WELLS_DEFINITION_SHA256 = hashlib.sha256(
    Path(__file__).with_name("wells-table-pilot-definition.json").read_bytes()
).hexdigest()
FIDELITY_HSA_DEFINITION_SHA256 = hashlib.sha256(
    Path(__file__).with_name("fidelity-hsa-summary-pilot-definition.json").read_bytes()
).hexdigest()
YAMAHA_DEFINITION_SHA256 = hashlib.sha256(
    Path(__file__).with_name("yamaha-card-pilot-definition.json").read_bytes()
).hexdigest()
CAPITAL_ONE_DEFINITION_SHA256 = hashlib.sha256(
    Path(__file__).with_name("capital-one-loan-pilot-definition.json").read_bytes()
).hexdigest()
USBANK_DEFINITION_SHA256 = hashlib.sha256(
    Path(__file__).with_name("usbank-rei-card-pilot-definition.json").read_bytes()
).hexdigest()
VANGUARD_DEFINITION_SHA256 = hashlib.sha256(
    Path(__file__).with_name("vanguard-summary-pilot-definition.json").read_bytes()
).hexdigest()
FIDELITY_401K_DEFINITION_SHA256 = hashlib.sha256(
    Path(__file__).with_name("fidelity-401k-summary-pilot-definition.json").read_bytes()
).hexdigest()
OCCU_CARD_DEFINITION_SHA256 = hashlib.sha256(
    Path(__file__).with_name("occu-card-pilot-definition.json").read_bytes()
).hexdigest()
OCCU_BANK_DEFINITION_SHA256 = hashlib.sha256(
    Path(__file__).with_name("occu-bank-pilot-definition.json").read_bytes()
).hexdigest()
LEGACY_CITI_DEFINITION_SHA256 = hashlib.sha256(
    Path(__file__).with_name("legacy-citi-pilot-definition.json").read_bytes()
).hexdigest()
MIDDLE_CITI_DEFINITION_SHA256 = hashlib.sha256(
    Path(__file__).with_name("middle-citi-table-pilot-definition.json").read_bytes()
).hexdigest()
LENDINGCLUB_TABLE_DEFINITION_SHA256 = hashlib.sha256(
    Path(__file__).with_name("lendingclub-table-pilot-definition.json").read_bytes()
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
            elif digest in {
                CHASE_DEFINITION_SHA256,
                HAPPEN_DEFINITION_SHA256,
                LENDINGCLUB_DEFINITION_SHA256,
                FIDELITY_HSA_DEFINITION_SHA256,
                YAMAHA_DEFINITION_SHA256,
                CAPITAL_ONE_DEFINITION_SHA256,
                VANGUARD_DEFINITION_SHA256,
                FIDELITY_401K_DEFINITION_SHA256,
            }:
                decoded = decode_pdf(source)
                lines = page_lines(source, decoded.pages, extraction_library="pdfplumber-bounded-simple-v1")
                if digest == CHASE_DEFINITION_SHA256:
                    output = from_card(parse_card_lines(definition, lines), lines)
                elif digest == HAPPEN_DEFINITION_SHA256:
                    output = parse_savings_lines(definition, lines)
                elif digest == FIDELITY_HSA_DEFINITION_SHA256:
                    output = parse_investment_summary(definition, lines)
                elif digest == YAMAHA_DEFINITION_SHA256:
                    output = parse_two_date_card(definition, lines)
                elif digest == CAPITAL_ONE_DEFINITION_SHA256:
                    output = parse_loan_history(definition, lines)
                elif digest == VANGUARD_DEFINITION_SHA256:
                    output = parse_single_column_summary(definition, lines)
                elif digest == FIDELITY_401K_DEFINITION_SHA256:
                    output = parse_plan_label_summary(definition, lines)
                else:
                    output = parse_summary_savings_lines(definition, lines)
            elif digest == WELLS_DEFINITION_SHA256:
                decoded = decode_pdf(source)
                lines = page_lines(source, decoded.pages, extraction_library="pdfplumber-bounded-simple-v1")
                output = from_wells_business(definition, extract_bounded_wells(definition, source), lines)
            elif digest == USBANK_DEFINITION_SHA256:
                simple_pages = decode_pdf(source).pages
                layout_pages = decode_pdf_layout(source).pages
                simple = page_lines(source, simple_pages, extraction_library="pdfplumber-bounded-simple-v1")
                layout = page_lines(source, layout_pages, extraction_library="pdfplumber-bounded-layout-fixed-v1")
                output = parse_dual_text_card(definition, layout, simple)
            elif digest == OCCU_CARD_DEFINITION_SHA256:
                pages = decode_pdf_default_layout(source).pages
                lines = page_lines(source, pages, extraction_library="pdfplumber-bounded-layout-default-v1")
                output = parse_occu_card(definition, lines)
            elif digest == OCCU_BANK_DEFINITION_SHA256:
                pages = decode_pdf(source).pages
                lines = page_lines(source, pages, extraction_library="pdfplumber-bounded-simple-v1")
                try:
                    output = parse_occu_bank(definition, lines)
                except OccuBankError as error:
                    if str(error) != "missing_annotation_period":
                        raise
                    output = parse_occu_bank(definition, lines, decode_pdf_period_annotations(source))
            elif digest == LEGACY_CITI_DEFINITION_SHA256:
                pages = decode_pdf_default_layout(source).pages
                lines = page_lines(source, pages, extraction_library="pdfplumber-bounded-layout-default-v1")
                output = parse_legacy_citi(definition, lines)
            elif digest == MIDDLE_CITI_DEFINITION_SHA256:
                pages = decode_pdf_default_layout(source).pages
                lines = page_lines(source, pages, extraction_library="pdfplumber-bounded-layout-default-v1")
                output = from_anchored_card(definition, extract_bounded_anchored_table(definition, source), lines)
            elif digest == LENDINGCLUB_TABLE_DEFINITION_SHA256:
                pages = decode_pdf(source).pages
                lines = page_lines(source, pages, extraction_library="pdfplumber-bounded-simple-v1")
                output = from_anchored_bank(definition, extract_bounded_anchored_table(definition, source), lines)
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
