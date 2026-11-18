"""Finite non-activity roles in the business table's over-wide footer crop.

The extraction grid cuts words and numbers across its six cells. Rejoining is
used only for complete anchored footer grammars, never for dated activity.
Unknown rows and extra monetary tokens retain their unresolved disposition.
"""

from __future__ import annotations

import re
from datetime import date, datetime

from parsetrail.core.source_evidence import PdfTableRow, SourceDisposition
from parsetrail.core.v2_money_operations import usd_or_decimal_2dp_minor_v1
from parsetrail.core.v2_pdf_lines import PDFLineEvidence
from parsetrail.core.v2_wells_table import TableRow

_MONEY = r"\$?(?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)\.[0-9]{2}"
_FEE_PERIOD = re.compile(
    rf"Feeperiod(?P<start>\d{{2}}/\d{{2}}/\d{{4}})-(?P<end>\d{{2}}/\d{{2}}/\d{{4}})"
    rf"Standardmonthlyservicefee{_MONEY}Youpaid{_MONEY}",
    re.I,
)
_PUBLIC_TEXT = {
    "TheEndingDailyBalancedoesnotreflectanypendingwithdrawalsorholdsondepositedfundsthatmayhavebeenoutstandingonyouraccountwhen",
    "yourtransactionsposted.Ifyouhadinsufficientavailablefundswhenatransactionposted,feesmayhavebeenassessed.",
}
_FEE_TEXT = {
    "Monthlyservicefeesummary",
    "hlyservicefeesummary",
    "ompletelistoffeesanddetailedaccountinformation,seethedisclosuresapplicabletoyouraccountortalktoabanker.Goto",
    "argo.com/feefaqforalinktothesedocuments,andanswerstocommonmonthlyservicefeequestions.",
    "HowtoavoidthemonthlyservicefeeMinimumrequiredThisfeeperiod",
    "HaveanyONEofthefollowingaccountrequirements",
}
_TRANSACTION_TEXT = {
    "Accounttransactionfeessummary",
    "ounttransactionfeessummary",
    "UnitsExcessServicechargeperTotalservice",
    "ServicechargedescriptionUnitsusedincludedunitsexcessunits($)charge($)",
}


def _compact(raw: str) -> str:
    return "".join(raw.split())


def _valid_period(text: str, end: date) -> bool:
    match = _FEE_PERIOD.fullmatch(text)
    if match is None:
        return False
    try:
        start = datetime.strptime(match["start"], "%m/%d/%Y").date()
        finish = datetime.strptime(match["end"], "%m/%d/%Y").date()
    except ValueError:
        return False
    return finish == end and 0 <= (finish - start).days <= 45


def classify_wells_tail(
    rows: tuple[TableRow, ...],
    lines: PDFLineEvidence,
    *,
    closing: int,
    end: date,
    credits: int,
    debits: int,
) -> tuple[SourceDisposition, ...]:
    """Keep all footer occurrences; require complete source roles for refinement."""
    page_text = {}
    for line in lines.lines:
        page_text.setdefault(line.page, []).append(line.normalized.casefold())
    codes = {}
    for row in rows:
        if row.disposition not in {"terminator", "unresolved_after_stop"}:
            continue
        text = _compact("".join(row.raw_cells))
        if not text:
            codes[row.row_id] = "wells_non_activity_blank"
            continue
        ending = re.fullmatch(rf"Endingbalanceon(?P<date>\d{{1,2}}/\d{{1,2}})(?P<amount>{_MONEY})", text, re.I)
        totals = re.fullmatch(rf"Totals(?P<credits>{_MONEY})(?P<debits>{_MONEY})", text, re.I)
        if (
            ending
            and ending["date"] in {f"{end.month}/{end.day}", end.strftime("%m/%d")}
            and usd_or_decimal_2dp_minor_v1(ending["amount"]) == closing
        ):
            codes[row.row_id] = "wells_statement_summary"
        elif (
            totals
            and usd_or_decimal_2dp_minor_v1(totals["credits"]) == credits
            and usd_or_decimal_2dp_minor_v1(totals["debits"]) == debits
        ):
            codes[row.row_id] = "wells_statement_summary"
        elif text in _PUBLIC_TEXT:
            codes[row.row_id] = "wells_balance_disclosure"

    for page in {row.page for row in rows}:
        tail = [row for row in rows if row.page == page and row.disposition == "unresolved_after_stop"]
        printed = page_text.get(page, [])
        # The cropped headings are accepted only with their complete printed
        # source headings and the monetary table's complete finite frame.
        if "monthly service fee summary" in printed:
            periods = [row for row in tail if _valid_period(_compact("".join(row.raw_cells)), end)]
            thresholds = [
                row
                for row in tail
                if re.fullmatch(
                    rf"[•\ufffd](?:Averageledgerbalance|Minimumdailybalance){_MONEY}{_MONEY}",
                    _compact("".join(row.raw_cells)),
                    re.I,
                )
            ]
            kinds = {_compact("".join(row.raw_cells)).split("balance")[0].casefold() for row in thresholds}
            if len(periods) == 1 and len(thresholds) == 2 and len(kinds) == 2:
                for row in tail:
                    text = _compact("".join(row.raw_cells))
                    if row in periods or row in thresholds or text in _FEE_TEXT or re.fullmatch(r"C\d/C\d", text):
                        codes[row.row_id] = "wells_service_fee_information"
        if "account transaction fees summary" in printed:
            fee_rows = [
                row
                for row in tail
                if (
                    _compact("".join(row.raw_cells[:2])) in {"CashDeposited($)", "Transactions"}
                    and re.fullmatch(r"[0-9,]+ [0-9,]+ [0-9,]+", " ".join(row.raw_cells[2].split()))
                    and not row.raw_cells[3].strip()
                    and re.fullmatch(r"[0-9]+\.[0-9]{2,4}", row.raw_cells[4].strip())
                    and re.fullmatch(_MONEY, row.raw_cells[5].strip())
                )
            ]
            totals = [
                (row, match)
                for row in tail
                if (
                    match := re.fullmatch(
                        rf"Totalservicecharges(?P<amount>{_MONEY})", _compact("".join(row.raw_cells)), re.I
                    )
                )
            ]
            if (
                len(fee_rows) == 2
                and len({_compact("".join(row.raw_cells[:2])) for row in fee_rows}) == 2
                and len(totals) == 1
                and sum(usd_or_decimal_2dp_minor_v1(row.raw_cells[5].strip()) for row in fee_rows)
                == usd_or_decimal_2dp_minor_v1(totals[0][1]["amount"])
            ):
                for row in tail:
                    if row in fee_rows or row == totals[0][0] or _compact("".join(row.raw_cells)) in _TRANSACTION_TEXT:
                        codes[row.row_id] = "wells_transaction_fee_information"
    return tuple(
        SourceDisposition(
            code=codes.get(row.row_id, row.disposition),
            location=PdfTableRow(kind="pdf_table_row", page=row.page, row=row.table_row, region=row.region),
            raw_values=row.raw_cells,
        )
        for row in rows
        if row.disposition in {"terminator", "unresolved_after_stop"}
    )
