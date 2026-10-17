"""Read-only bounded proof of the 2.0 source-to-evidence boundary.

This pilot does not activate a catalog, write a profile or approve accounting.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Literal

from parsetrail.core.source_evidence import SourceEvidence

from devtools.parser_engine_pilot.bounded_anchored_table import extract_bounded_anchored_table
from devtools.parser_engine_pilot.bounded_pdf_annotations import decode_pdf_period_annotations
from devtools.parser_engine_pilot.bounded_pdf_text import decode_pdf, decode_pdf_default_layout, decode_pdf_layout
from devtools.parser_engine_pilot.bounded_wells import extract_bounded_wells
from devtools.parser_engine_pilot.card_lines import parse_card_lines
from devtools.parser_engine_pilot.card_source_output import from_card
from devtools.parser_engine_pilot.catalog_admission import admit_pilot_definition
from devtools.parser_engine_pilot.citi_evidence import read_recent_citi
from devtools.parser_engine_pilot.citi_source_output import from_citi
from devtools.parser_engine_pilot.dual_text_card_lines import parse_dual_text_card
from devtools.parser_engine_pilot.engine import EngineError, parse_csv
from devtools.parser_engine_pilot.hsa_cash_lines import parse_cash_section
from devtools.parser_engine_pilot.hsa_cash_source_output import from_hsa_cash
from devtools.parser_engine_pilot.investment_summary_lines import parse_investment_summary
from devtools.parser_engine_pilot.legacy_citi_lines import parse_legacy_citi
from devtools.parser_engine_pilot.loan_history_lines import parse_loan_history
from devtools.parser_engine_pilot.occu_bank_lines import OccuBankError, parse_occu_bank
from devtools.parser_engine_pilot.occu_card_lines import parse_occu_card
from devtools.parser_engine_pilot.pdf_lines import page_lines
from devtools.parser_engine_pilot.savings_lines import parse_savings_lines, parse_summary_savings_lines
from devtools.parser_engine_pilot.single_column_summary import parse_plan_label_summary, parse_single_column_summary
from devtools.parser_engine_pilot.synchrony_source_output import from_synchrony_table
from devtools.parser_engine_pilot.table_bank_source_output import from_anchored_bank
from devtools.parser_engine_pilot.table_card_source_output import from_anchored_card
from devtools.parser_engine_pilot.table_source_output import from_table
from devtools.parser_engine_pilot.transamerica_summary_lines import parse_retirement_summary
from devtools.parser_engine_pilot.two_date_card_lines import parse_two_date_card
from devtools.parser_engine_pilot.wells_loan_lines import parse_wells_loan
from devtools.parser_engine_pilot.wells_personal_source_output import from_wells_personal
from devtools.parser_engine_pilot.wells_statement_output import from_wells_business
from devtools.parser_engine_pilot.worker_limits import WorkerError

MAX_SOURCE_BYTES = 16 * 1024 * 1024
MAX_DEFINITION_BYTES = 64 * 1024
MAX_EVIDENCE_BYTES = 32 * 1024 * 1024
SIMPLE_LINE_PARSERS = {
    "chase_card_line_pilot",
    "happen_savings_line_pilot",
    "lendingclub_savings_line_pilot",
    "pdf_fidelityhsa_202001",
    "pdf_yamahafin_202306",
    "pdf_capitaloneauto_202402",
    "pdf_vanguard_202210",
    "pdf_fidelity401k_201810",
    "pdf_transamerica_202104",
    "pdf_wfloanper_202306",
    "hsa_cash_line_pilot",
    "synchrony_amazon_store_card",
}


class SourcePipelineError(ValueError):
    """Redacted refusal before source evidence can be stored."""


def build_source_evidence(
    source: bytes,
    definition: bytes,
    *,
    suffix: Literal[".csv", ".pdf"],
    cancelled: Callable[[], bool] | None = None,
) -> SourceEvidence:
    """Build strict, hash-bound evidence without source/profile writes."""
    if type(source) is not bytes or not 0 < len(source) <= MAX_SOURCE_BYTES:
        raise SourcePipelineError("source_size")
    if type(definition) is not bytes or not 0 < len(definition) <= MAX_DEFINITION_BYTES:
        raise SourcePipelineError("definition_size")
    if suffix not in {".csv", ".pdf"}:
        raise SourcePipelineError("unsupported_source_kind")
    if cancelled is not None and cancelled():
        raise SourcePipelineError("cancelled")
    try:
        identity = admit_pilot_definition(definition)
        if identity.suffix != suffix:
            raise SourcePipelineError("definition_source_kind_mismatch")
        if suffix == ".csv":
            output = from_table(parse_csv(definition, source, cancelled=cancelled))
        else:
            parser_id = identity.parser_id
            if parser_id == "pdf_citicc_202511":
                output = from_citi(read_recent_citi(source, definition, cancelled=cancelled), definition)
            elif parser_id in SIMPLE_LINE_PARSERS:
                decoded = decode_pdf(source, cancelled=cancelled)
                lines = page_lines(source, decoded.pages, extraction_library="pdfplumber-bounded-simple-v1")
                if parser_id == "chase_card_line_pilot":
                    output = from_card(parse_card_lines(definition, lines), lines)
                elif parser_id == "happen_savings_line_pilot":
                    output = parse_savings_lines(definition, lines)
                elif parser_id == "pdf_fidelityhsa_202001":
                    output = parse_investment_summary(definition, lines)
                elif parser_id == "pdf_yamahafin_202306":
                    output = parse_two_date_card(definition, lines)
                elif parser_id == "pdf_capitaloneauto_202402":
                    output = parse_loan_history(definition, lines)
                elif parser_id == "pdf_vanguard_202210":
                    output = parse_single_column_summary(definition, lines)
                elif parser_id == "pdf_fidelity401k_201810":
                    output = parse_plan_label_summary(definition, lines)
                elif parser_id == "pdf_transamerica_202104":
                    output = parse_retirement_summary(definition, lines)
                elif parser_id == "pdf_wfloanper_202306":
                    output = parse_wells_loan(definition, lines)
                elif parser_id == "hsa_cash_line_pilot":
                    cash = parse_cash_section(definition, lines)
                    if any(item.reason == "cash_window_unclassified" for item in cash.unresolved_section_lines):
                        raise SourcePipelineError("unclassified_cash_window_line")
                    output = from_hsa_cash(cash, lines)
                elif parser_id == "synchrony_amazon_store_card":
                    output = from_synchrony_table(
                        definition, extract_bounded_anchored_table(definition, source, cancelled=cancelled), lines
                    )
                else:
                    output = parse_summary_savings_lines(definition, lines)
            elif parser_id == "wells_business_table_pilot":
                decoded = decode_pdf(source, cancelled=cancelled)
                lines = page_lines(source, decoded.pages, extraction_library="pdfplumber-bounded-simple-v1")
                output = from_wells_business(
                    definition, extract_bounded_wells(definition, source, cancelled=cancelled), lines
                )
            elif parser_id == "pdf_usbankreicc_201405":
                simple_pages = decode_pdf(source, cancelled=cancelled).pages
                layout_pages = decode_pdf_layout(source, cancelled=cancelled).pages
                simple = page_lines(source, simple_pages, extraction_library="pdfplumber-bounded-simple-v1")
                layout = page_lines(source, layout_pages, extraction_library="pdfplumber-bounded-layout-fixed-v1")
                output = parse_dual_text_card(definition, layout, simple)
            elif parser_id == "pdf_occucc_201904":
                pages = decode_pdf_default_layout(source, cancelled=cancelled).pages
                lines = page_lines(source, pages, extraction_library="pdfplumber-bounded-layout-default-v1")
                output = parse_occu_card(definition, lines)
            elif parser_id == "pdf_occubank_201409":
                pages = decode_pdf(source, cancelled=cancelled).pages
                lines = page_lines(source, pages, extraction_library="pdfplumber-bounded-simple-v1")
                try:
                    output = parse_occu_bank(definition, lines)
                except OccuBankError as error:
                    if str(error) != "missing_annotation_period":
                        raise
                    output = parse_occu_bank(
                        definition, lines, decode_pdf_period_annotations(source, cancelled=cancelled)
                    )
            elif parser_id == "pdf_citicc_201505":
                pages = decode_pdf_default_layout(source, cancelled=cancelled).pages
                lines = page_lines(source, pages, extraction_library="pdfplumber-bounded-layout-default-v1")
                output = parse_legacy_citi(definition, lines)
            elif parser_id == "pdf_citicc_202506":
                pages = decode_pdf_default_layout(source, cancelled=cancelled).pages
                lines = page_lines(source, pages, extraction_library="pdfplumber-bounded-layout-default-v1")
                output = from_anchored_card(
                    definition, extract_bounded_anchored_table(definition, source, cancelled=cancelled), lines
                )
            elif parser_id == "pdf_lendingclublus_202506":
                pages = decode_pdf(source, cancelled=cancelled).pages
                lines = page_lines(source, pages, extraction_library="pdfplumber-bounded-simple-v1")
                output = from_anchored_bank(
                    definition, extract_bounded_anchored_table(definition, source, cancelled=cancelled), lines
                )
            elif parser_id == "pdf_wfbankper_202105":
                pages = decode_pdf(source, cancelled=cancelled).pages
                lines = page_lines(source, pages, extraction_library="pdfplumber-bounded-simple-v1")
                output = from_wells_personal(
                    definition, extract_bounded_anchored_table(definition, source, cancelled=cancelled), lines
                )
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
        if cancelled is not None and cancelled():
            raise SourcePipelineError("cancelled")
        return SourceEvidence.model_validate_json(saved)
    except SourcePipelineError:
        raise
    except (EngineError, WorkerError) as error:
        if (isinstance(error, EngineError) and error.code == "cancelled") or str(error) == "cancelled":
            raise SourcePipelineError("cancelled") from None
        raise SourcePipelineError("source_evidence_failed") from None
    except Exception:
        raise SourcePipelineError("source_evidence_failed") from None
