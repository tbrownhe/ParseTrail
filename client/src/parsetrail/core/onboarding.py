"""State and presentation data for the local first-run guide."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from parsetrail.core.settings import AppSettings, save_settings

CURRENT_ONBOARDING_VERSION = 1


def onboarding_needed(current: AppSettings) -> bool:
    return current.onboarding_version < CURRENT_ONBOARDING_VERSION


def mark_onboarding_complete(
    current: AppSettings,
    *,
    saver: Callable[[AppSettings], None] = save_settings,
) -> None:
    previous = current.onboarding_version
    current.onboarding_version = CURRENT_ONBOARDING_VERSION
    try:
        saver(current)
    except Exception:
        current.onboarding_version = previous
        raise


def installed_support_summary(metadata: Mapping[str, Mapping[str, object]]) -> str:
    supported: set[str] = set()
    for plugin in metadata.values():
        company = str(plugin.get("COMPANY") or "Unknown institution").strip()
        statement_type = str(plugin.get("STATEMENT_TYPE") or "Statement").strip()
        supported.add(f"{company} — {statement_type}")
    if not supported:
        return "No parser plugins are installed yet."
    return "\n".join(f"• {item}" for item in sorted(supported, key=str.casefold))
