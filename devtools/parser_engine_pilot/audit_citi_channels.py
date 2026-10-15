"""Read-only recent-Citi table/text candidate audit; no financial row repair."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from loguru import logger
from parsetrail.core.money import parse_money, to_minor_units
from parsetrail.core.parse import extract_pdf_features
from parsetrail.core.parser_classification import DocumentFeatures, matching_plugins, normalize_pdf_metadata
from parsetrail.core.utils import PDFReader, get_absolute_date
from parsetrail.plugins.pdf_citicc_202506 import Parser as OlderCiti
from parsetrail.plugins.pdf_citicc_202511 import Parser as RecentCiti

from devtools.parser_engine_pilot.bounded_citi import extract_bounded_citi
from devtools.parser_engine_pilot.bounded_pdf_text import decode_pdf
from devtools.parser_engine_pilot.channel_occurrences import Candidate, match_occurrences
from devtools.parser_engine_pilot.citi_channels import CITI_OCCURRENCE_RULE, resolve
from devtools.parser_engine_pilot.citi_source_dispositions import dispose_dated_lines
from devtools.parser_engine_pilot.citi_statement_header import parse_header
from devtools.parser_engine_pilot.citi_table_candidates import candidates_from_table


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


def fee_candidates(parser: RecentCiti, pages: list[str], start_date: datetime, end_date: datetime) -> list[Candidate]:
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
            transaction_date = get_absolute_date(pending[0], start_date, end_date).date()
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
        decoded = decode_pdf(source)
        bounded_text = decoded.pages
        if tuple(reader.pages_simple or []) != bounded_text:
            raise ValueError("bounded_simple_text_changed")
        bounded_pages = list(bounded_text)
        bounded_table = extract_bounded_citi(source)
        bounded_features = DocumentFeatures(
            suffix=".pdf",
            body_text="\n".join(" ".join(line.split()) for page in bounded_text for line in page.splitlines()),
            header_text="\n".join(" ".join(line.split()) for page in bounded_text for line in page.splitlines()[:40]),
            pdf_metadata=normalize_pdf_metadata(dict(decoded.metadata)),
            page_count=len(bounded_text),
        )
        if matching_plugins(bounded_features, metadata) != (RecentCiti.PLUGIN_NAME,):
            raise ValueError("bounded_layout_classification_changed")
        header = parse_header(bounded_table.first_page_chars, bounded_text)
        accepted_account = accepted.accounts[0]
        if (
            header.start_date != accepted.start_date
            or header.end_date != accepted.end_date
            or header.account_suffix != accepted_account.account_num
            or header.previous_balance.ledger_minor != to_minor_units(accepted_account.start_balance)
            or header.new_balance.ledger_minor != to_minor_units(accepted_account.end_balance)
        ):
            raise ValueError("bounded_statement_header_changed")
        statement_start = datetime.combine(header.start_date, datetime.min.time())
        statement_end = datetime.combine(header.end_date, datetime.min.time())
        table_transactions = parser.parse_transaction_array([list(row.raw_cells) for row in bounded_table.rows])
        grouped_table = candidates_from_table(bounded_table, statement_start, statement_end)
        table = list(grouped_table.rows)
        if [
            (row.transaction_date, row.posting_date, to_minor_units(row.amount), " ".join(row.desc.split()))
            for row in table_transactions
        ] != [(row.transaction_date, row.posting_date, row.amount_minor, row.description) for row in table]:
            raise ValueError("shared_table_group_parity")
        text = []
        for page_number, page in enumerate(bounded_pages, 1):
            for line_number, line in enumerate(page.splitlines(), 1):
                match = parser.TEXT_TRANSACTION.match(line)
                if match is None:
                    continue
                transaction_raw = match.group("transaction_date") or match.group("single_date")
                posting_raw = match.group("posting_date") or match.group("single_date")
                text.append(
                    Candidate(
                        get_absolute_date(transaction_raw, statement_start, statement_end).date(),
                        get_absolute_date(posting_raw, statement_start, statement_end).date(),
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
        located_fees = fee_candidates(parser, bounded_pages, statement_start, statement_end)
        source_dispositions = dispose_dated_lines(parser, bounded_pages, table, located_fees)
        source_counts = Counter(item.status for item in source_dispositions)
        resolution = resolve(
            table,
            text,
            located_fees,
            opening_minor=header.previous_balance.ledger_minor,
            closing_minor=header.new_balance.ledger_minor,
        )
        resolved_by_source = {
            (candidate.channel, candidate.page, candidate.line): index
            for index, row in enumerate(resolution.rows)
            for candidate in row.sources
        }
        incomplete_by_location = {
            (candidate.page, candidate.line): candidate for candidate in resolution.incomplete_text_copies
        }
        dated_row_occurrences: Counter[int] = Counter()
        for item in source_dispositions:
            if item.status == "simple_text":
                key = ("text", item.page, item.line)
            elif item.status == "table_copy":
                key = ("table", item.page, item.table_row)
            elif item.status == "fee":
                key = ("fee", item.page, item.line)
            else:
                continue
            row_index = resolved_by_source.get(key)
            if row_index is None and item.status == "simple_text":
                incomplete = incomplete_by_location.get((item.page, item.line))
                if incomplete is not None:
                    peers = [
                        index
                        for index, row in enumerate(resolution.rows)
                        if row.disposition == "table"
                        and row.representative.page == incomplete.page
                        and (
                            row.representative.transaction_date,
                            row.representative.posting_date,
                            row.representative.amount_minor,
                        )
                        == (incomplete.transaction_date, incomplete.posting_date, incomplete.amount_minor)
                    ]
                    if len(peers) == 1:
                        row_index = peers[0]
            if row_index is None:
                raise ValueError("dated_source_without_resolved_row")
            dated_row_occurrences[row_index] += 1
        dated_start_row_bijection = source_counts["unresolved"] == 0 and all(
            dated_row_occurrences[index] == 1 for index in range(len(resolution.rows))
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
        "bounded_raw_table_rows": len(bounded_table.rows),
        "supplemental_table_detail_rows": sum(len(group.detail_rows) for group in grouped_table.groups),
        "bounded_simple_text_pages": len(bounded_text),
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
        "located_fee_count": len(located_fees),
        "dated_source_lines": len(source_dispositions),
        "simple_text_lines": source_counts["simple_text"],
        "table_source_copies": source_counts["table_copy"],
        "fee_source_lines": source_counts["fee"],
        "unresolved_source_lines": source_counts["unresolved"],
        "source_first_character_losses": sum(
            item.description_evidence == "first_character_loss" for item in source_dispositions
        ),
        "dated_start_dispositions_complete": source_counts["unresolved"] == 0,
        "dated_start_row_bijection": dated_start_row_bijection,
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
