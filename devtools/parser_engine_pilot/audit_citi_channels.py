"""Read-only recent-Citi table/text candidate audit; no financial row repair."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

from loguru import logger
from parsetrail.core.money import parse_money, to_minor_units
from parsetrail.core.parse import extract_pdf_features
from parsetrail.core.parser_classification import matching_plugins
from parsetrail.core.utils import PDFReader, get_absolute_date
from parsetrail.plugins.pdf_citicc_202506 import Parser as OlderCiti
from parsetrail.plugins.pdf_citicc_202511 import Parser as RecentCiti


@dataclass(frozen=True, slots=True)
class Candidate:
    transaction_date: date
    posting_date: date
    amount_minor: int
    description: str
    channel: Literal["table", "text"]
    page: int | None = None
    line: int | None = None


@dataclass(frozen=True, slots=True)
class TextDisposition:
    candidate: Candidate
    status: Literal["exact_table_occurrence", "unresolved_overlap", "text_only_candidate"]


def dispositions(table: list[Candidate], text: list[Candidate]) -> tuple[TextDisposition, ...]:
    """Match exact occurrences; never infer that a coarse-key conflict is a new row."""
    available = Counter((row.transaction_date, row.posting_date, row.amount_minor, row.description) for row in table)
    coarse = {(row.transaction_date, row.posting_date, row.amount_minor) for row in table}
    result = []
    for row in text:
        exact = (row.transaction_date, row.posting_date, row.amount_minor, row.description)
        broad = exact[:3]
        if available[exact]:
            available[exact] -= 1
            status = "exact_table_occurrence"
        elif broad in coarse:
            status = "unresolved_overlap"
        else:
            status = "text_only_candidate"
        result.append(TextDisposition(row, status))
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
    """Audit only the recognized 2025-11 layout and report aggregate counts."""
    logger.remove()
    with PDFReader(source, "in-memory.pdf") as reader:
        classes = (OlderCiti, RecentCiti)
        metadata = {
            parser.PLUGIN_NAME: {
                "SUFFIX": parser.SUFFIX,
                "SEARCH_STRING": parser.SEARCH_STRING,
                "ROUTING_RULE": parser.ROUTING_RULE,
            }
            for parser in classes
        }
        if matching_plugins(extract_pdf_features(reader), metadata) != (RecentCiti.PLUGIN_NAME,):
            raise ValueError("wrong_or_ambiguous_citi_layout")
        parser = RecentCiti()
        accepted = parser.parse(reader)
        parser.vertical_lines = None
        parser.crop_settings = None
        parser.stop = False
        table_transactions = parser.parse_transaction_array(parser.get_transaction_array())
        parser.vertical_lines = None
        parser.crop_settings = None
        parser.stop = False
        page_rows = []
        for page_number, page in enumerate(reader.PDF.pages, 1):
            if parser.stop:
                break
            if not parser.vertical_lines:
                parser.get_vertical_lines(page)
            if parser.vertical_lines:
                page_rows.extend(
                    (page_number, row)
                    for row in parser.parse_transaction_array(parser.get_transactions_from_page(page))
                )

        def row_key(row):
            return (row.transaction_date, row.posting_date, row.amount, row.desc)

        if Counter(map(row_key, table_transactions)) != Counter(row_key(row) for _, row in page_rows):
            raise ValueError("page_table_rows_changed")
        table = [
            Candidate(
                row.transaction_date,
                row.posting_date,
                to_minor_units(row.amount),
                " ".join(row.desc.split()),
                "table",
                page_number,
            )
            for page_number, row in page_rows
        ]
        text = []
        for page_number, page in enumerate(reader.pages_simple or [], 1):
            for line_number, line in enumerate(page.splitlines(), 1):
                match = parser.TEXT_TRANSACTION.match(line)
                if match is None:
                    continue
                transaction_raw = match.group("transaction_date") or match.group("single_date")
                posting_raw = match.group("posting_date") or match.group("single_date")
                text.append(
                    Candidate(
                        get_absolute_date(transaction_raw, parser.start_date, parser.end_date).date(),
                        get_absolute_date(posting_raw, parser.start_date, parser.end_date).date(),
                        -to_minor_units(parse_money(match.group("amount"))),
                        " ".join(match.group("description").split()),
                        "text",
                        page_number,
                        line_number,
                    )
                )
        classified = dispositions(table, text)
        counts = Counter(item.status for item in classified)
        shapes = Counter(
            overlap_shape(item.candidate, table) for item in classified if item.status == "unresolved_overlap"
        )
        recovered = parser.extract_missing_text_transactions(table_transactions)
        fees = parser.extract_missing_fees([*table_transactions, *recovered])
        if len(accepted.accounts) != 1 or len(table) + len(recovered) + len(fees) != len(
            accepted.accounts[0].transactions
        ):
            raise ValueError("accepted_row_count_changed")
        account = accepted.accounts[0]
        reconciles = account.start_balance + sum(row.amount for row in account.transactions) == account.end_balance
    return {
        "table_candidates": len(table),
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
