"""Select source-backed accounting-date candidates without rewriting evidence."""

from __future__ import annotations

from parsetrail.core.source_evidence import DateValue, ObservationEvidence
from parsetrail.core.v2_preferences import V2Preferences


def posting_date_candidate(row: ObservationEvidence) -> DateValue | None:
    if row.row_role != "activity":
        return None
    candidate = row.date if row.date_role == "posting_date" else row.posting_date_guess
    if candidate is None or candidate.iso is None or candidate.provenance == "unknown":
        return None
    return candidate


def permitted_posting_date(row: ObservationEvidence, preferences: V2Preferences) -> DateValue | None:
    """Require a one-time global choice before an assumed date can enter a journal."""
    candidate = posting_date_candidate(row)
    if candidate is not None and (candidate.provenance != "assumed" or preferences.allow_assumed_posting_dates):
        return candidate
    return None
