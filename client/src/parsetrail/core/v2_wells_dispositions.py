"""Shared finite non-activity audit of Wells table footer crops.

The extraction grid cuts words and numbers across its six cells. Rejoining is
used only for complete anchored footer grammars, never for dated activity.
Unknown rows and extra monetary tokens retain their unresolved disposition.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from parsetrail.core.source_evidence import PdfTableRow, SourceDisposition
from parsetrail.core.v2_money_operations import usd_or_decimal_2dp_minor_v1
from parsetrail.core.v2_pdf_lines import PDFLineEvidence
from parsetrail.core.v2_wells_table import TableRow

_MONEY = r"\$?(?:0|[1-9][0-9]*|[1-9][0-9]{0,2}(?:,[0-9]{3})+)\.[0-9]{2}"
_FEE_PERIOD = re.compile(
    rf"Feeperiod(?P<start>\d{{1,2}}/\d{{1,2}}/\d{{4}})[-\u2013](?P<end>\d{{1,2}}/\d{{1,2}}/\d{{4}})"
    rf"Standardmonthlyservicefee(?P<standard>{_MONEY})Youpaid(?P<paid>{_MONEY})",
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
_BULLET = r"[\u2022\u00b7\ufffd-]?"
_STATUS = r"(?:34|3|[\u2713\u2714\u221a])"
_MONEY_FIELDS = re.compile(
    rf"{_BULLET}\s*(?P<label>.+?)\s+(?P<required>{_MONEY})\s+"
    rf"(?P<actual>-?{_MONEY})(?:\s+(?P<status>{_STATUS}))?",
    re.I,
)
_MONEY_LABELS = {
    "minimumdailybalance",
    "averageledgerbalance",
    "totalamountofqualifyingelectronicdeposits",
    "totalamountofqualifyingdirectdeposits",
    "asingleautomatictransferfromawellsfargocheckingaccount",
    "amonthlyautomatictransferfromawellsfargocheckingaccount",
    "adailyautomatictransferfromawellsfargocheckingaccount",
    "anautomatictransferfromalinkedwellsfargocheckingaccounteachfeeperiod",
    "saveasyougo\u00aetransferfromawellsfargocheckingaccount",
    "saveasyougotransferfromawellsfargocheckingaccount",
    "totalautomatictransfersfromaneligiblewellsfargobusinesscheckingaccount",
    "totalautomatictransfersfromaneligiblewellsfargobusinesschecking",
}
_AGE_FIELDS = re.compile(
    rf"{_BULLET}\s*(?P<label>.+?)\s+(?P<low>\d{{1,3}})\s*[-\u2013]\s*(?P<high>\d{{1,3}})"
    rf"(?:\s+(?P<actual>\d{{1,3}})(?:\s+(?P<status>{_STATUS}))?)?",
    re.I,
)
_LINK_FIELDS = re.compile(
    rf"{_BULLET}\s*(?P<label>.+?)\s+(?P<required>[01])\s+(?P<actual>[01])"
    rf"(?:\s+(?P<status>{_STATUS}))?",
    re.I,
)
_FEE_HEADERS = {
    "howtoavoidthemonthlyservicefeeminimumrequiredthisfeeperiod",
    "haveanyoneofthefollowingaccountrequirements",
    "haveoneofthefollowingaccountrequirements",
}
_FEE_INTRO = (
    "foracompletelistoffeesanddetailedaccountinformation,seethedisclosuresapplicabletoyouraccount"
    "ortalktoabanker.gotowellsfargo.com/feefaqforalinktothesedocuments,andanswerstocommonmonthlyservicefeequestions."
)
_FEE_PARAGRAPHS = {
    _FEE_INTRO,
    "wewaivedthefeethisfeeperiodtoallowyoutomeettherequirementstoavoidthemonthlyservicefee."
    "yourfeewaiverisabouttoexpire.youwillneedtomeetoneoftherequirementstoavoidthemonthlyservicefee.",
    "wewaivedthefeethisfeeperiodtoallowyoutomeettherequirementstoavoidthemonthlyservicefee."
    "thisisthefinalperiodwiththefeewaived.forthenextfeeperiod,youneedtomeetoneoftherequirementstoavoidthemonthlyservicefee.",
    "themonthlyservicefeesummaryfeeperiodendingdateshownaboveincludesasaturday,sunday,orholidaywhicharenon-businessdays."
    "transactionsoccurringafterthelastbusinessdayofthemonthwillbeincludedinyournextfeeperiod.",
}
_BALANCE_PARAGRAPH = re.compile(
    r"theendingdailybalancedoesnotreflectanypendingwithdrawalsorholdsondepositedfundsthat"
    r"(?:mayhavebeen|were)outstandingonyouraccountwhen(?:your)?transactionsposted\."
    r"ifyou(?:had|have)insufficientavailablefundswhenatransactionposted,feesmayhavebeenassessed\."
)
_CONTACT_PARAGRAPH = re.compile(
    r"newyorkcitycustomersonly--pursuanttonewyorkcityregulations,werequestthatyoucontactusat"
    r"1-[2-9]\d{2}-towells\(1-[2-9]\d{2}-[2-9]\d{2}-\d{4}\)toshareyourlanguagepreference\."
)


def _normal(raw: str) -> str:
    return _compact(raw).casefold()


def _money(raw: str) -> int | None:
    try:
        return usd_or_decimal_2dp_minor_v1(raw)
    except ValueError:
        return None


def _criterion(raw: str) -> bool:
    """Recognize labelled requirements/observations, not financial activity.

    A finite legacy annotation may follow complete typed fields. Both met and
    unmet criteria are auxiliary context. The annotation stays raw/uninterpreted:
    no checkbox state, eligibility decision or new amount is emitted. The opaque
    strings 3/34 are not stripped or converted into another value.
    """
    match = _MONEY_FIELDS.fullmatch(raw)
    if match and _normal(match["label"]) in _MONEY_LABELS:
        required, actual = _money(match["required"]), _money(match["actual"])
        return required is not None and actual is not None and required >= 0
    match = _AGE_FIELDS.fullmatch(raw)
    if match and _normal(match["label"]) in {"ageofaccountowner", "ageofprimaryaccountowner"}:
        low, high = int(match["low"]), int(match["high"])
        actual = int(match["actual"]) if match["actual"] is not None else None
        return 0 <= low <= high <= 130 and (actual is None or 0 <= actual <= 130)
    match = _LINK_FIELDS.fullmatch(raw)
    if match and _normal(match["label"]) == "accountislinkedtoawellsfargocampusatmcardorcampusdebitcard":
        return match["required"] == "1"
    return False


def _crop_matches(raw: str, printed: str) -> bool:
    """Permit short word-edge cropping, never a different label or lost numbers."""
    raw, printed = _normal(raw), _normal(printed)
    if len(re.findall(r"[^\W\d_]", raw)) < 12:
        return False
    offset = printed.find(raw)
    if offset < 0 or offset > 8 or len(printed) - offset - len(raw) > 8:
        return False
    return _numeric_inventory(raw) == _numeric_inventory(printed)


def _numeric_inventory(text):
    """Retain digits, currency and attached sign/decimal/date punctuation."""
    result = []
    for index, char in enumerate(text):
        if char.isdecimal() or char in "$\u20ac\u00a3":
            result.append(char)
        elif char in "+-\u2212.,/()" and any(
            0 <= adjacent < len(text) and (text[adjacent].isdecimal() or text[adjacent] in "$\u20ac\u00a3")
            for adjacent in (index - 1, index + 1)
        ):
            result.append(char)
    return "".join(result)


def _paragraph_lines(lines, known):
    admitted = []
    for index in range(len(lines)):
        for width in range(1, 5):
            group = lines[index : index + width]
            if len(group) == width and known(_normal("".join(group))):
                admitted.extend(group)
                admitted.append("".join(group))
    return admitted


def _heading_like(raw, heading):
    raw, heading = _normal(raw), _normal(heading)
    return any(raw.startswith(heading[cut:]) for cut in range(9) if len(heading) - cut >= 12)


def _section_boundary(raw):
    return any(
        _heading_like(raw, heading)
        for heading in (
            "Monthly service fee summary",
            "Account transaction fees summary",
            "Important account information",
        )
    )


def _fee_line_frames(page_lines, *, end, statement_start):
    """Admit only complete local fee frames; unknown neighbouring lines stay unknown."""
    result = []
    starts = [i for i, line in enumerate(page_lines) if _normal(line) == "monthlyservicefeesummary"]
    for start in starts:
        finish = min(start + 64, len(page_lines))
        for index in range(start + 1, finish):
            if _section_boundary(page_lines[index]):
                finish = index
                break
        frame = page_lines[start:finish]
        normals = {_normal(line) for line in frame}
        periods = [line for line in frame if _valid_period(_compact(line), end, statement_start)]
        criteria = [line for line in frame if _criterion(line)]
        if (
            not periods
            or not criteria
            or not (
                "howtoavoidthemonthlyservicefeeminimumrequiredthisfeeperiod" in normals
                and any(
                    value in normals
                    for value in _FEE_HEADERS - {"howtoavoidthemonthlyservicefeeminimumrequiredthisfeeperiod"}
                )
            )
        ):
            result.append(())
            continue
        admitted = [frame[0], *periods, *criteria]
        admitted.extend(line for line in frame if _normal(line) in _FEE_HEADERS)
        for index, line in enumerate(frame):
            if (
                _normal(line) == "account"
                and index
                and _criterion(frame[index - 1])
                and ("totalautomatictransfersfromaneligiblewellsfargobusinesschecking" in _normal(frame[index - 1]))
            ):
                admitted.append(line)
        admitted.extend(_paragraph_lines(frame, lambda value: value in _FEE_PARAGRAPHS))
        result.append(tuple(admitted))
    return result


def _fee_segments(rows):
    result, current = [], None
    for row in rows:
        text = "".join(row.raw_cells)
        if _section_boundary(text):
            if current is not None:
                result.append(tuple(current))
            current = [row] if _crop_matches(text, "Monthly service fee summary") else None
        elif current is not None:
            current.append(row)
    if current is not None:
        result.append(tuple(current))
    return result


def _threshold(text):
    match = re.fullmatch(
        rf"[\u2022\u00b7\ufffd](?:Averageledgerbalance|Minimumdailybalance)"
        rf"(?P<required>{_MONEY})(?P<actual>{_MONEY})",
        text,
        re.I,
    )
    return match is not None and _money(match["required"]) is not None and _money(match["actual"]) is not None


def _compact(raw: str) -> str:
    return "".join(raw.split())


def _valid_period(text: str, end: date, statement_start: date | None = None) -> bool:
    match = _FEE_PERIOD.fullmatch(text)
    if match is None:
        return False
    try:
        start = datetime.strptime(match["start"], "%m/%d/%Y").date()
        finish = datetime.strptime(match["end"], "%m/%d/%Y").date()
    except ValueError:
        return False
    return (
        0 <= (finish - start).days <= 45
        and (statement_start or end) - timedelta(days=45) <= finish <= end
        and _money(match["standard"]) is not None
        and _money(match["paid"]) is not None
    )


def classify_wells_tail(
    rows: tuple[TableRow, ...],
    lines: PDFLineEvidence,
    *,
    closing: int,
    end: date,
    credits: int,
    debits: int,
    statement_start: date | None = None,
) -> tuple[SourceDisposition, ...]:
    """Keep all footer occurrences; require complete source roles for refinement."""
    page_text = {}
    for line in lines.lines:
        page_text.setdefault(line.page, []).append(line.normalized)
    codes = {}
    for row in rows:
        if row.disposition not in {"terminator", "unresolved_after_stop"}:
            continue
        text = _compact("".join(row.raw_cells))
        if not text:
            codes[row.row_id] = "wells_non_activity_blank"
            continue
        ending = re.fullmatch(rf"Endingbalanceon(?P<date>\d{{1,2}}/\d{{1,2}})(?P<amount>-?{_MONEY})", text, re.I)
        totals = re.fullmatch(rf"Totals(?P<credits>{_MONEY})(?P<debits>{_MONEY})", text, re.I)
        if (
            ending
            and ending["date"] in {f"{end.month}/{end.day}", end.strftime("%m/%d")}
            and _money(ending["amount"]) == closing
        ):
            codes[row.row_id] = "wells_statement_summary"
        elif totals and _money(totals["credits"]) == credits and _money(totals["debits"]) == debits:
            codes[row.row_id] = "wells_statement_summary"
        elif text in _PUBLIC_TEXT:
            codes[row.row_id] = "wells_balance_disclosure"

    for page in {row.page for row in rows}:
        tail = [row for row in rows if row.page == page and row.disposition == "unresolved_after_stop"]
        printed = page_text.get(page, [])
        balance_lines = _paragraph_lines(printed, _BALANCE_PARAGRAPH.fullmatch)
        contact_lines = _paragraph_lines(printed, _CONTACT_PARAGRAPH.fullmatch)
        for row in tail:
            if any(_crop_matches("".join(row.raw_cells), line) for line in balance_lines):
                codes[row.row_id] = "wells_balance_disclosure"
            elif any(_crop_matches("".join(row.raw_cells), line) for line in contact_lines):
                codes[row.row_id] = "wells_statement_context"
        # The cropped headings are accepted only with their complete printed
        # source headings and the monetary table's complete finite frame.
        if any(_normal(line) == "monthlyservicefeesummary" for line in printed):
            frames = _fee_line_frames(printed, end=end, statement_start=statement_start)
            segments = _fee_segments(tail)
            if len(frames) == len(segments):
                for frame, segment in zip(frames, segments, strict=True):
                    periods = [
                        row for row in segment if _valid_period(_compact("".join(row.raw_cells)), end, statement_start)
                    ]
                    thresholds = [row for row in segment if _threshold(_compact("".join(row.raw_cells)))]
                    kinds = {_normal("".join(row.raw_cells)).split("balance")[0] for row in thresholds}
                    headers = {_normal("".join(row.raw_cells)) for row in segment}
                    legacy_frame = (
                        len(periods) == 1
                        and len(thresholds) == 2
                        and len(kinds) == 2
                        and (
                            "howtoavoidthemonthlyservicefeeminimumrequiredthisfeeperiod" in headers
                            and any(
                                header in headers
                                for header in _FEE_HEADERS
                                - {"howtoavoidthemonthlyservicefeeminimumrequiredthisfeeperiod"}
                            )
                        )
                    )
                    for row in segment:
                        text = "".join(row.raw_cells)
                        if re.fullmatch(r"\s*\d{1,2}/\d{1,2}\s*", row.raw_cells[0]):
                            continue
                        if legacy_frame and (
                            row in periods
                            or row in thresholds
                            or _compact(text) in _FEE_TEXT
                            or re.fullmatch(r"C\d/C\d", _compact(text))
                        ):
                            codes[row.row_id] = "wells_service_fee_information"
                        elif frame and len({_normal(line) for line in frame if _crop_matches(text, line)}) == 1:
                            codes[row.row_id] = "wells_service_fee_information"
                        elif (
                            frame
                            and re.fullmatch(r"[A-Z]\d{1,2}/[A-Z]\d{1,2}", _compact(text))
                            and (any(_normal(line) == _normal(text) for line in printed))
                        ):
                            codes[row.row_id] = "wells_statement_context"
        if any(_normal(line) == "accounttransactionfeessummary" for line in printed):
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
                and all(_money(row.raw_cells[5].strip()) is not None for row in fee_rows)
                and sum(_money(row.raw_cells[5].strip()) for row in fee_rows) == _money(totals[0][1]["amount"])
            ):
                for row in tail:
                    if row in fee_rows or row == totals[0][0] or _compact("".join(row.raw_cells)) in _TRANSACTION_TEXT:
                        codes[row.row_id] = "wells_transaction_fee_information"
        for row in tail:
            text = _normal("".join(row.raw_cells))
            if text == "importantaccountinformation" and any(_normal(line) == text for line in printed):
                codes[row.row_id] = "wells_statement_context"
    return tuple(
        SourceDisposition(
            code=codes.get(row.row_id, row.disposition),
            location=PdfTableRow(kind="pdf_table_row", page=row.page, row=row.table_row, region=row.region),
            raw_values=row.raw_cells,
        )
        for row in rows
        if row.disposition in {"terminator", "unresolved_after_stop"}
    )


def classify_wells_dispositions(dispositions, lines, **context):
    """Adapt personal table dispositions without changing their raw locations."""
    tail = [item for item in dispositions if item.code in {"table_terminator", "unresolved_after_stop"}]
    rows = tuple(
        TableRow(
            str(index),
            item.location.page,
            item.location.row,
            item.location.region,
            item.raw_values,
            "terminator" if item.code == "table_terminator" else "unresolved_after_stop",
        )
        for index, item in enumerate(tail)
    )
    refined = iter(classify_wells_tail(rows, lines, **context))
    result = []
    for item in dispositions:
        if item.code not in {"table_terminator", "unresolved_after_stop"}:
            result.append(item)
            continue
        refined_item = next(refined)
        result.append(
            item.model_copy(update={"code": refined_item.code}) if refined_item.code != "terminator" else item
        )
    return tuple(result)
