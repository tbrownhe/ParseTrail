"""Compare bounded recent-Citi evidence against the accepted legacy reader."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from loguru import logger
from parsetrail.core.money import to_minor_units
from parsetrail.core.parse import extract_pdf_features
from parsetrail.core.parser_classification import matching_plugins
from parsetrail.core.utils import PDFReader
from parsetrail.core.v2_channel_occurrences import Candidate, match_occurrences
from parsetrail.plugins.pdf_citicc_202506 import Parser as OlderCiti
from parsetrail.plugins.pdf_citicc_202511 import Parser as RecentCiti

from devtools.parser_engine_pilot.citi_authoring import DEFINITION, DEFINITION_BYTES
from devtools.parser_engine_pilot.citi_evidence import read_recent_citi


@dataclass(frozen=True, slots=True)
class TextDisposition:
    candidate: Candidate
    status: Literal["exact_table_occurrence", "unresolved_overlap", "text_only_candidate"]


def dispositions(table: list[Candidate], text: list[Candidate]) -> tuple[TextDisposition, ...]:
    """Match exact occurrences; never infer that a coarse-key conflict is a new row."""
    result = []
    for match in match_occurrences(DEFINITION.channel_occurrences, table, text):
        if match.status == "exact_copy":
            status = "exact_table_occurrence"
        elif match.status == "secondary_only":
            status = "text_only_candidate"
        else:
            status = "unresolved_overlap"
        result.append(TextDisposition(match.secondary, status))
    return tuple(result)


def overlap_shape(candidate: Candidate, table: list[Candidate]) -> str:
    """Describe a same-page overlap for investigation, without accepting a row."""
    peers = [
        row
        for row in table
        if row.page == candidate.page
        and (row.transaction_date, row.posting_date, row.amount_minor)
        == (candidate.transaction_date, candidate.posting_date, candidate.amount_minor)
    ]
    if len(peers) != 1:
        return "unclassified_overlap"
    description = candidate.description
    peer = peers[0].description
    if re.fullmatch(r"\d{2}/\d{2}", description):
        return "date_only_text_copy"
    if description == peer:
        return "additional_exact_occurrence"
    if description[1:] == peer or peer[1:] == description:
        return "one_character_description_difference"
    return "unclassified_overlap"


def audit(source: bytes) -> dict[str, int | bool]:
    """Compare a bounded candidate path with the current reader, without writes."""
    logger.remove()
    evidence = read_recent_citi(source, DEFINITION_BYTES)
    table = list(evidence.table_candidates.rows)
    text = list(evidence.text_candidates)
    classified = dispositions(table, text)
    counts = Counter(item.status for item in classified)
    shapes = Counter(overlap_shape(item.candidate, table) for item in classified if item.status == "unresolved_overlap")
    source_counts = Counter(item.status for item in evidence.dated_lines)
    money_counts = Counter(item.status for item in evidence.money_lines)
    resolution = evidence.resolution
    with PDFReader(source, "in-memory.pdf") as reader:
        metadata = {
            parser.PLUGIN_NAME: {
                "SUFFIX": parser.SUFFIX,
                "SEARCH_STRING": parser.SEARCH_STRING,
                "ROUTING_RULE": parser.ROUTING_RULE,
            }
            for parser in (OlderCiti, RecentCiti)
        }
        if matching_plugins(extract_pdf_features(reader), metadata) != (RecentCiti.PLUGIN_NAME,):
            raise ValueError("legacy_layout_classification_changed")
        parser = RecentCiti()
        accepted = parser.parse(reader)
        if tuple(reader.pages_simple or []) != evidence.simple_text_pages:
            raise ValueError("bounded_simple_text_changed")
        if len(accepted.accounts) != 1:
            raise ValueError("accepted_account_count_changed")
        account = accepted.accounts[0]
        header = evidence.header
        if (
            header.start_date != accepted.start_date
            or header.end_date != accepted.end_date
            or header.account_suffix != account.account_num
            or header.previous_balance.ledger_minor != to_minor_units(account.start_balance)
            or header.new_balance.ledger_minor != to_minor_units(account.end_balance)
        ):
            raise ValueError("bounded_statement_header_changed")
        legacy_table = parser.parse_transaction_array([list(row.raw_cells) for row in evidence.table_evidence.rows])
        if [
            (row.transaction_date, row.posting_date, to_minor_units(row.amount), " ".join(row.desc.split()))
            for row in legacy_table
        ] != [(row.transaction_date, row.posting_date, row.amount_minor, row.description) for row in table]:
            raise ValueError("shared_table_group_parity")
        recovered = parser.extract_missing_text_transactions(legacy_table)
        fees = parser.extract_missing_fees([*legacy_table, *recovered])
        if len(table) + len(recovered) + len(fees) != len(account.transactions):
            raise ValueError("accepted_row_count_changed")
        reconciles = account.start_balance + sum(row.amount for row in account.transactions) == account.end_balance
        resolved_rows = Counter(
            (row.representative.transaction_date, row.representative.posting_date, row.representative.amount_minor)
            for row in resolution.rows
        )
        accepted_rows = Counter(
            (row.transaction_date, row.posting_date, to_minor_units(row.amount)) for row in account.transactions
        )
        if resolved_rows != accepted_rows:
            raise ValueError("resolved_row_parity")
        resolved_descriptions = Counter(
            (
                row.representative.transaction_date,
                row.representative.posting_date,
                row.representative.amount_minor,
                row.representative.description,
            )
            for row in resolution.rows
        )
        accepted_descriptions = Counter(
            (
                row.transaction_date,
                row.posting_date,
                to_minor_units(row.amount),
                " ".join(row.desc.split()),
            )
            for row in account.transactions
        )
        description_differences = sum((resolved_descriptions - accepted_descriptions).values())
        if description_differences > resolution.first_character_corrections + len(evidence.fee_candidates):
            raise ValueError("unexpected_description_difference")
    return {
        "table_candidates": len(table),
        "bounded_raw_table_rows": len(evidence.table_evidence.rows),
        "supplemental_table_detail_rows": sum(len(group.detail_rows) for group in evidence.table_candidates.groups),
        "bounded_simple_text_pages": len(evidence.simple_text_pages),
        "bounded_statement_header_parity": True,
        "bounded_layout_parity": True,
        "text_candidates": len(text),
        "exact_table_occurrences": counts["exact_table_occurrence"],
        "unresolved_overlaps": counts["unresolved_overlap"],
        "text_only_candidates": counts["text_only_candidate"],
        "accepted_text_recoveries": len(recovered),
        "accepted_fee_recoveries": len(fees),
        "date_only_text_copies": shapes["date_only_text_copy"],
        "one_character_description_differences": shapes["one_character_description_difference"],
        "additional_exact_occurrences": shapes["additional_exact_occurrence"],
        "unclassified_overlaps": shapes["unclassified_overlap"],
        "accepted_balance_reconciles": reconciles,
        "resolved_row_count": len(resolution.rows),
        "resolved_row_parity": True,
        "resolved_description_differences": description_differences,
        "located_fee_count": len(evidence.fee_candidates),
        "dated_source_lines": len(evidence.dated_lines),
        "simple_text_lines": source_counts["simple_text"],
        "table_source_copies": source_counts["table_copy"],
        "fee_source_lines": source_counts["fee"],
        "unresolved_source_lines": source_counts["unresolved"],
        "source_first_character_losses": sum(
            item.description_evidence == "first_character_loss" for item in evidence.dated_lines
        ),
        "dated_start_dispositions_complete": source_counts["unresolved"] == 0,
        "dated_start_row_bijection": evidence.dated_start_row_bijection,
        "nontransaction_money_lines": len(evidence.money_lines),
        "first_page_money_lines": sum(item.page == 1 for item in evidence.money_lines),
        "summary_extraction_artifacts": money_counts["summary_extraction_artifact"],
        "unresolved_money_lines": money_counts["unresolved"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="Recent Citi PDF; read-only")
    args = parser.parse_args()
    source = args.source.read_bytes()
    before = hashlib.sha256(source).hexdigest()
    try:
        result = audit(source)
    except Exception as exc:
        print(json.dumps({"audit_error_type": type(exc).__name__}))
        return 1
    result["source_file_unchanged"] = before == hashlib.sha256(args.source.read_bytes()).hexdigest()
    print(json.dumps(result, sort_keys=True))
    return 0 if result["source_file_unchanged"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
