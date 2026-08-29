"""Deterministic feature-tree classification for statement plugins."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from parsetrail.core.search_expression import match_search_string, parse_search_string

ROUTING_RULE_FIELD = "ROUTING_RULE"
ALLOWED_ROUTING_RULE_KEYS = frozenset({"header", "pdf_metadata", "pdf_metadata_keys"})


@dataclass(frozen=True, slots=True)
class DocumentFeatures:
    """In-memory features used for routing; content is intentionally hidden from repr."""

    suffix: str
    body_text: str = field(repr=False)
    header_text: str = field(default="", repr=False)
    pdf_metadata: Mapping[str, str] = field(default_factory=dict, repr=False)
    page_count: int | None = None


@dataclass(frozen=True, slots=True)
class ClassificationTrace:
    """Candidate identifiers at each routing stage; never includes document content."""

    suffix_candidates: tuple[str, ...]
    metadata_candidates: tuple[str, ...]
    header_candidates: tuple[str, ...]
    body_candidates: tuple[str, ...]


def normalize_pdf_metadata(metadata: Mapping[str, Any] | None) -> dict[str, str]:
    if not metadata:
        return {}
    return {
        str(key).strip().casefold(): str(value).strip().casefold()
        for key, value in metadata.items()
        if str(key).strip() and value is not None
    }


def validate_routing_metadata(metadata: Mapping[str, Any]) -> None:
    parse_search_string(metadata["SEARCH_STRING"])
    raw_rule = metadata.get(ROUTING_RULE_FIELD)
    if raw_rule is None:
        return
    if not isinstance(raw_rule, dict):
        raise ValueError(f"{ROUTING_RULE_FIELD} must be a dictionary")
    unknown = sorted(set(raw_rule) - ALLOWED_ROUTING_RULE_KEYS)
    if unknown:
        raise ValueError(f"Unknown {ROUTING_RULE_FIELD} fields: {', '.join(unknown)}")

    header = raw_rule.get("header")
    if header is not None:
        if not isinstance(header, str):
            raise ValueError(f"{ROUTING_RULE_FIELD}.header must be a string")
        parse_search_string(header)

    metadata_rules = raw_rule.get("pdf_metadata")
    if metadata_rules is not None:
        if not isinstance(metadata_rules, dict) or not metadata_rules:
            raise ValueError(f"{ROUTING_RULE_FIELD}.pdf_metadata must be a non-empty dictionary")
        for key, expression in metadata_rules.items():
            if not isinstance(key, str) or not key.strip() or not isinstance(expression, str):
                raise ValueError(f"{ROUTING_RULE_FIELD}.pdf_metadata entries must map strings to strings")
            parse_search_string(expression)

    required_keys = raw_rule.get("pdf_metadata_keys")
    if required_keys is not None and (
        not isinstance(required_keys, (list, tuple))
        or not required_keys
        or not all(isinstance(key, str) and key.strip() for key in required_keys)
    ):
        raise ValueError(f"{ROUTING_RULE_FIELD}.pdf_metadata_keys must be a non-empty string list")


def _matches_pdf_metadata(rule: Mapping[str, Any], features: DocumentFeatures) -> bool:
    required_keys = {key.strip().casefold() for key in rule.get("pdf_metadata_keys", ())}
    if not required_keys.issubset(features.pdf_metadata):
        return False

    for raw_key, expression in rule.get("pdf_metadata", {}).items():
        value = features.pdf_metadata.get(raw_key.strip().casefold())
        if value is None or not match_search_string(expression, value):
            return False
    return True


def classification_trace(
    features: DocumentFeatures,
    plugin_metadata: Mapping[str, Mapping[str, Any]],
) -> ClassificationTrace:
    """Walk suffix, PDF metadata, header, and body nodes in that order."""
    suffix_candidates = [
        (plugin_name, metadata)
        for plugin_name, metadata in plugin_metadata.items()
        if metadata.get("SUFFIX", "").casefold() == features.suffix.casefold()
    ]

    metadata_candidates = [
        (plugin_name, metadata)
        for plugin_name, metadata in suffix_candidates
        if _matches_pdf_metadata(metadata.get(ROUTING_RULE_FIELD, {}), features)
    ]

    header_candidates = []
    for plugin_name, metadata in metadata_candidates:
        header_expression = metadata.get(ROUTING_RULE_FIELD, {}).get("header")
        if header_expression is None or match_search_string(header_expression, features.header_text):
            header_candidates.append((plugin_name, metadata))

    body_candidates = tuple(
        plugin_name
        for plugin_name, metadata in header_candidates
        if match_search_string(metadata["SEARCH_STRING"], features.body_text)
    )
    return ClassificationTrace(
        suffix_candidates=tuple(plugin_name for plugin_name, _metadata in suffix_candidates),
        metadata_candidates=tuple(plugin_name for plugin_name, _metadata in metadata_candidates),
        header_candidates=tuple(plugin_name for plugin_name, _metadata in header_candidates),
        body_candidates=body_candidates,
    )


def matching_plugins(
    features: DocumentFeatures,
    plugin_metadata: Mapping[str, Mapping[str, Any]],
) -> tuple[str, ...]:
    """Return the plugins at the final leaf of the deterministic feature tree."""
    return classification_trace(features, plugin_metadata).body_candidates
