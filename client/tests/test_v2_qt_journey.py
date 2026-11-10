"""Run each complete Qt journey in a fresh process, including QApplication teardown.

The unchanged scenarios live in qt_journey_scenarios.py, which pytest does not
discover by filename. This module deliberately has no Qt imports or fixtures.
"""

from __future__ import annotations

import pytest

from .qt_journey_process import run_journey_case


@pytest.mark.parametrize("size", ["1050x700", "1280x800"])
def test_empty_profile_to_reviewed_spending_correction_and_recovery(pytestconfig, tmp_path, size):
    run_journey_case(f"test_empty_profile_to_reviewed_spending_correction_and_recovery[{size}]", pytestconfig, tmp_path)


def test_refused_import_can_retry_without_losing_source_or_creating_entries(pytestconfig, tmp_path):
    run_journey_case("test_refused_import_can_retry_without_losing_source_or_creating_entries", pytestconfig, tmp_path)


def test_cancel_in_flight_import_restores_recovery_actions(pytestconfig, tmp_path):
    run_journey_case("test_cancel_in_flight_import_restores_recovery_actions", pytestconfig, tmp_path)


def __getattr__(name):
    # Compatibility for existing scratch diagnostics, without importing the Qt
    # scenario fixtures during pytest collection of this lightweight wrapper.
    if name in {"SOURCE", "prepare_close", "ready", "review_ready", "assert_books"}:
        from . import qt_journey_scenarios

        return getattr(qt_journey_scenarios, name)
    raise AttributeError(name)
