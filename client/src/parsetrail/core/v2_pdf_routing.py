"""Strict, signed PDF recognition rules and bounded unique catalog routing."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from parsetrail.core.parser_classification import (
    DocumentFeatures,
    matching_plugins,
    normalize_pdf_metadata,
    validate_routing_metadata,
)
from parsetrail.core.v2_bounded_pdf_text import DecodedPDFText, decode_pdf
from parsetrail.core.v2_data_catalog import VerifiedCatalog


class PDFRoutingError(ValueError):
    """No unique signed route admitted this PDF."""


class PDFRouting(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    body: str = Field(min_length=1, max_length=300)
    header: str | None = Field(default=None, max_length=400)
    pdf_metadata: dict[str, str] = Field(default_factory=dict, max_length=8)

    @model_validator(mode="after")
    def valid_expressions(self) -> PDFRouting:
        if any(not key or len(key) > 80 or not value or len(value) > 300 for key, value in self.pdf_metadata.items()):
            raise ValueError("invalid_pdf_routing_metadata")
        rule: dict[str, Any] = {}
        if self.header is not None:
            rule["header"] = self.header
        if self.pdf_metadata:
            rule["pdf_metadata"] = self.pdf_metadata
        validate_routing_metadata({"SEARCH_STRING": self.body, "ROUTING_RULE": rule})
        return self

    def plugin_metadata(self) -> dict[str, Any]:
        rule: dict[str, Any] = {}
        if self.header is not None:
            rule["header"] = self.header
        if self.pdf_metadata:
            rule["pdf_metadata"] = self.pdf_metadata
        return {"SUFFIX": ".pdf", "SEARCH_STRING": self.body, "ROUTING_RULE": rule}


def _features(decoded: DecodedPDFText) -> DocumentFeatures:
    return DocumentFeatures(
        suffix=".pdf",
        body_text="\n".join(" ".join(line.split()) for page in decoded.pages for line in page.splitlines()),
        header_text="\n".join(" ".join(line.split()) for page in decoded.pages for line in page.splitlines()[:40]),
        pdf_metadata=normalize_pdf_metadata(dict(decoded.metadata)),
        page_count=len(decoded.pages),
    )


def select_pdf_definition(
    source: bytes,
    catalog: VerifiedCatalog,
    *,
    cancelled: Callable[[], bool] | None = None,
) -> str:
    """Decode once through the bounded worker and require one declared route."""
    routes = {}
    for item in catalog.definitions:
        if item.identity.suffix != ".pdf":
            continue
        try:
            raw = json.loads(item.content)
            route = PDFRouting.model_validate(raw["routing"])
        except (KeyError, TypeError, ValueError):
            raise PDFRoutingError("pdf_routing_definition_unavailable") from None
        routes[item.identity.parser_id] = route.plugin_metadata()
    if not routes:
        raise PDFRoutingError("catalog_no_match")
    if cancelled is not None and cancelled():
        raise PDFRoutingError("cancelled")
    decoded = decode_pdf(source, cancelled=cancelled)
    if cancelled is not None and cancelled():
        raise PDFRoutingError("cancelled")
    matches = matching_plugins(_features(decoded), routes)
    if len(matches) != 1:
        raise PDFRoutingError("catalog_ambiguous_match" if matches else "catalog_no_match")
    return matches[0]
