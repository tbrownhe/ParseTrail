"""Locate dollar-bearing PDF lines not already represented in source evidence."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from parsetrail.core.source_evidence import PdfLine, SourceDisposition
from parsetrail.core.v2_pdf_lines import PDFLineEvidence


class MonetaryLineRule(BaseModel):
    """A finite, literal label rule; no regex or accounting action is supplied."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    code: Literal["fee_period_total", "interest_period_total", "annual_fee_total", "annual_interest_total"]
    all_of: tuple[str, ...] = Field(min_length=1, max_length=3)
    none_of: tuple[str, ...] = Field(default=(), max_length=3)

    @model_validator(mode="after")
    def valid_fragments(self) -> MonetaryLineRule:
        fragments = self.all_of + self.none_of
        if any(not 0 < len(value.strip()) <= 80 for value in fragments):
            raise ValueError("invalid_monetary_line_fragment")
        if len({value.casefold() for value in fragments}) != len(fragments):
            raise ValueError("duplicate_monetary_line_fragment")
        return self

    def matches(self, raw: str) -> bool:
        line = " ".join(raw.casefold().split())
        return all(fragment.casefold() in line for fragment in self.all_of) and not any(
            fragment.casefold() in line for fragment in self.none_of
        )


def inventory_monetary_lines(
    lines: PDFLineEvidence,
    *,
    money_token: re.Pattern[str],
    covered_locations: Iterable[PdfLine],
    rules: tuple[MonetaryLineRule, ...] = (),
) -> tuple[SourceDisposition, ...]:
    """Retain uncovered money; label it only when exactly one literal rule fits."""
    covered = {
        (location.page, number)
        for location in covered_locations
        for number in range(location.line, (location.end_line or location.line) + 1)
    }
    dispositions = []
    for line in lines.lines:
        if not money_token.search(line.raw) or (line.page, line.line) in covered:
            continue
        matches = [rule.code for rule in rules if rule.matches(line.raw)]
        dispositions.append(
            SourceDisposition(
                code=matches[0] if len(matches) == 1 else "unclassified_monetary_line",
                location=PdfLine(kind="pdf_line", page=line.page, line=line.line),
                raw_values=(line.raw,),
            )
        )
    return tuple(dispositions)
