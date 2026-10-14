"""Read-only recent-Citi table/text candidate audit; no financial row repair."""

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
from parsetrail.core.money import parse_money, to_minor_units
from parsetrail.core.parse import extract_pdf_features
from parsetrail.core.parser_classification import matching_plugins
from parsetrail.core.utils import PDFReader, get_absolute_date
from parsetrail.plugins.pdf_citicc_202506 import Parser as OlderCiti
from parsetrail.plugins.pdf_citicc_202511 import Parser as RecentCiti

from devtools.parser_engine_pilot.channel_occurrences import Candidate, match_occurrences
from devtools.parser_engine_pilot.citi_channels import CITI_OCCURRENCE_RULE, resolve


@dataclass(frozen=True, slots=True)
class TextDisposition:
    candidate: Candidate
    status: Literal["exact_table_occurrence", "unresolved_overlap", "text_only_candidate"]


def dispositions(table: list[Candidate], text: list[Candidate]) -> tuple[TextDisposition, ...]:
    """Match exact occurrences; never infer that a coarse-key conflict is a new row."""
    result = []
    for match in match_occurrences(CITI_OCCURRENCE_RULE, table, text):
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


def fee_candidates(parser: RecentCiti, pages: list[str]) -> list[Candidate]:
    """Locate multiline fee rows in the printed fee section."""
    result = []
    for page_number, page in enumerate(pages, 1):
        in_fees = False
        pending: tuple[str, list[str], int] | None = None
        for line_number, raw in enumerate(page.splitlines(), 1):
            line = " ".join(raw.split())
            if line == "Fees Charged":
                in_fees = True
                continue
            if not in_fees:
                continue
            if "TOTAL FEES FOR THIS PERIOD" in line:
                break
            date_match = parser.DATE_PREFIX.match(line)
            if date_match:
                pending = (date_match.group("date"), [date_match.group("description")], line_number)
            elif pending:
                pending[1].append(line)
            if pending is None:
                continue
            amount_match = parser.AMOUNT.search(line)
            if amount_match is None:
                continue
            transaction_date = get_absolute_date(pending[0], parser.start_date, parser.end_date).date()
            description = " ".join(" ".join(pending[1]).replace(amount_match.group(), "").split())
            result.append(
                Candidate(
                    transaction_date,
                    transaction_date,
                    -to_minor_units(parse_money(amount_match.group())),
                    description,
                    "fee",
                    page_number,
                    pending[2],
                    line_number,
                )
            )
            pending = None
    return result


def unmatched_dated_line_counts(parser: RecentCiti, pages: list[str]) -> Counter[str]:
    """Count dated source lines outside the finite text-row matcher."""
    counts: Counter[str] = Counter()
    for page in pages:
        for line in page.splitlines():
            if parser.DATE_PREFIX.match(line) is None or parser.TEXT_TRANSACTION.match(line):
                continue
            kind = "with_money" if parser.AMOUNT.search(line) else "without_money"
            counts[kind] += 1
    return counts


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
                    (page_number, row_number, row)
                    for row_number, row in enumerate(
                        parser.parse_transaction_array(parser.get_transactions_from_page(page)), 1
                    )
                )

        def row_key(row):
            return (row.transaction_date, row.posting_date, row.amount, row.desc)

        if Counter(map(row_key, table_transactions)) != Counter(row_key(row) for _, _, row in page_rows):
            raise ValueError("page_table_rows_changed")
        table = [
            Candidate(
                row.transaction_date,
                row.posting_date,
                to_minor_units(row.amount),
                " ".join(row.desc.split()),
                "table",
                page_number,
                row_number,
            )
            for page_number, row_number, row in page_rows
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
        located_fees = fee_candidates(parser, reader.pages_simple or [])
        dated_auxiliary = unmatched_dated_line_counts(parser, reader.pages_simple or [])
        resolution = resolve(
            table,
            text,
            located_fees,
            opening_minor=to_minor_units(account.start_balance),
            closing_minor=to_minor_units(account.end_balance),
        )
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
        if description_differences > resolution.first_character_corrections + len(located_fees):
            raise ValueError("unexpected_description_difference")
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
        "resolved_row_count": len(resolution.rows),
        "resolved_row_parity": True,
        "resolved_description_differences": description_differences,
        "located_fee_count": len(located_fees),
        "dated_unmatched_with_money": dated_auxiliary["with_money"],
        "dated_unmatched_without_money": dated_auxiliary["without_money"],
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
