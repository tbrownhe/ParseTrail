from __future__ import annotations

import pytest
from parsetrail.core.onboarding import (
    CURRENT_ONBOARDING_VERSION,
    installed_support_summary,
    mark_onboarding_complete,
    onboarding_needed,
)
from parsetrail.core.settings import AppSettings


def test_onboarding_marker_is_persisted_only_after_completion() -> None:
    current = AppSettings(onboarding_version=0)
    saved_versions: list[int] = []

    assert onboarding_needed(current)
    mark_onboarding_complete(current, saver=lambda value: saved_versions.append(value.onboarding_version))

    assert current.onboarding_version == CURRENT_ONBOARDING_VERSION
    assert saved_versions == [CURRENT_ONBOARDING_VERSION]
    assert not onboarding_needed(current)


def test_failed_completion_save_restores_previous_marker() -> None:
    current = AppSettings(onboarding_version=0)

    def fail_save(_current: AppSettings) -> None:
        raise OSError("disk unavailable")

    with pytest.raises(OSError, match="disk unavailable"):
        mark_onboarding_complete(current, saver=fail_save)

    assert current.onboarding_version == 0
    assert onboarding_needed(current)


def test_installed_support_summary_is_sorted_deduplicated_and_uses_only_display_metadata() -> None:
    summary = installed_support_summary(
        {
            "z": {
                "COMPANY": "Zeta Bank",
                "STATEMENT_TYPE": "Checking",
                "SEARCH_STRING": "confidential routing expression",
            },
            "a": {"COMPANY": "Alpha Credit", "STATEMENT_TYPE": "Credit Card"},
            "a_duplicate": {"COMPANY": "Alpha Credit", "STATEMENT_TYPE": "Credit Card"},
        }
    )

    assert summary.splitlines() == ["• Alpha Credit — Credit Card", "• Zeta Bank — Checking"]
    assert "routing expression" not in summary
