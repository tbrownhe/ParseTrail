"""Finite recent-Citi recognition and page-header geometry for the 2.0 pilot.

The shipped 1.x parser is an audit baseline, not a dependency of this path.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from statistics import median
from typing import Literal

from parsetrail.core.parser_classification import validate_routing_metadata
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from devtools.parser_engine_pilot.channel_occurrences import OccurrenceRule
from devtools.parser_engine_pilot.money_operations import USD_SYMBOL
from devtools.parser_engine_pilot.table_continuations import ContinuationRule


class CitiLayoutError(ValueError):
    """Redacted refusal of uncertain definition or page geometry."""


class _DefinitionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class RoutingDefinition(_DefinitionModel):
    body: str = Field(min_length=1, max_length=200)
    header: str = Field(min_length=1, max_length=300)
    metadata_author: str = Field(min_length=1, max_length=200)


class CitiDefinition(_DefinitionModel):
    schema_version: Literal[1]
    parser_id: Literal["pdf_citicc_202511"]
    revision: str = Field(min_length=1, max_length=80)
    kind: Literal["statement"]
    suffix: Literal[".pdf"]
    routing: RoutingDefinition
    geometry_operation: Literal["citi_header_geometry_v1"]
    date_operation: Literal["partial_month_day_v1"]
    money_operation: Literal["usd_symbol_minor_v1"]
    account_effect: Literal["negate_printed_amount_v1"]
    table_continuation: ContinuationRule
    channel_occurrences: OccurrenceRule

    @model_validator(mode="after")
    def supported_operations(self) -> CitiDefinition:
        if (
            self.table_continuation.mode != "amount_with_details"
            or self.channel_occurrences.primary_channel != "table"
            or self.channel_occurrences.secondary_channel != "text"
        ):
            raise ValueError("unsupported Citi operation")
        validate_routing_metadata(
            {
                "SEARCH_STRING": self.routing.body,
                "ROUTING_RULE": {
                    "pdf_metadata": {"Author": self.routing.metadata_author},
                    "header": self.routing.header,
                },
            }
        )
        return self


def load_definition(data: bytes) -> tuple[CitiDefinition, str]:
    if not data or len(data) > 64 * 1024:
        raise CitiLayoutError("definition_size")
    try:
        definition = CitiDefinition.model_validate_json(data)
    except (ValidationError, ValueError):
        raise CitiLayoutError("invalid_definition") from None
    return definition, sha256(data).hexdigest()


DEFINITION_BYTES = Path(__file__).with_name("recent-citi-pilot-definition.json").read_bytes()
DEFINITION, DEFINITION_SHA256 = load_definition(DEFINITION_BYTES)
EVIDENCE_ENGINE_VERSION = "recent-citi-evidence-pilot-4"

RECENT_CITI_ID = DEFINITION.parser_id
OTHER_LAYOUT_ROUTING_METADATA = {
    "pdf_citicc_202506": {
        "SUFFIX": ".pdf",
        "SEARCH_STRING": "www.citicards.com",
        "ROUTING_RULE": {
            "pdf_metadata": {"Producer": '"crawfordtech"'},
            "header": '("trans. post description amount" || ("trans. post" && "date date description amount")) && !"sale post"',
        },
    },
}

TRANSACTION_DATE = re.compile(r"\d{2}/\d{2}")
AMOUNT = USD_SYMBOL
TEXT_TRANSACTION = re.compile(
    r"^\s*(?:\d+\s+)*(?:(?P<transaction_date>\d{2}/\d{2})\s+"
    r"(?P<posting_date>\d{2}/\d{2})|(?P<single_date>\d{2}/\d{2}))\s+"
    r"(?P<description>.+?)\s+"
    r"(?P<amount>-?\$\d{1,3}(?:,\d{3})*\.\d{2})\s*$"
)
DATE_PREFIX = re.compile(r"^\s*(?:\d+\s+)*(?P<date>\d{2}/\d{2})\s+(?P<description>.+)$")
INTEREST_LINE = re.compile(r"^\d{2}/\d{2} INTEREST CHARGED TO STANDARD PURCH")
HEADER_COLUMNS = ("Sale", "Post", "Description", "Amount")
MAX_WORDS_PER_PAGE = 30_000


@dataclass(frozen=True, slots=True)
class TableGeometry:
    crop: tuple[float, float, float, float]
    vertical: tuple[float, float, float, float, float]


def locate_table(page) -> TableGeometry | None:
    """Locate four header words and fixed table boundaries on one page."""
    words = page.extract_words()
    if len(words) > MAX_WORDS_PER_PAGE:
        raise CitiLayoutError("word_limit")
    word_set = {word.get("text") for word in words if isinstance(word.get("text"), str)}
    labels = []
    for column in HEADER_COLUMNS:
        if column in word_set:
            labels.append(column)
            continue
        fragments = [word for word in word_set if column.endswith(word) and len(word) >= 3]
        if not fragments:
            return None
        fragments.sort(key=lambda word: (-len(word), word))
        if len(fragments) > 1 and len(fragments[0]) == len(fragments[1]):
            raise CitiLayoutError("ambiguous_header_fragment")
        labels.append(fragments[0])
    candidates = [word for word in words if word.get("text") in labels]
    bottoms = [word.get("bottom") for word in candidates]
    if not bottoms or any(not isinstance(value, (int, float)) or not math.isfinite(value) for value in bottoms):
        raise CitiLayoutError("invalid_header_geometry")
    center = median(bottoms)
    selected = [word for word in candidates if abs(word["bottom"] - center) < 10]
    if len(selected) != len(HEADER_COLUMNS):
        return None
    header = {word["text"]: word for word in selected}
    if len(header) != len(HEADER_COLUMNS) or len(set(labels)) != len(labels):
        raise CitiLayoutError("ambiguous_header_words")
    try:
        sale, post, description, amount = (header[label] for label in labels)
        vertical = (
            sale["x0"] - 3,
            post["x0"] - 2,
            description["x0"] - 2,
            amount["x0"] - 20,
            amount["x1"] + 2,
        )
        crop = (sale["x0"] - 3, 0, amount["x1"] + 2, page.height)
    except (KeyError, TypeError):
        raise CitiLayoutError("invalid_header_geometry") from None
    if (
        not all(isinstance(value, (int, float)) and math.isfinite(value) for value in (*vertical, *crop))
        or any(left >= right for left, right in zip(vertical, vertical[1:], strict=False))
        or not 0 <= crop[0] < crop[2] <= page.width
        or not 0 <= crop[1] < crop[3] <= page.height
    ):
        raise CitiLayoutError("invalid_table_geometry")
    return TableGeometry(crop, vertical)
