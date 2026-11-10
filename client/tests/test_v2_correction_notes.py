"""Correction-note scenarios each own a fresh QApplication process."""

import pytest

from .qt_journey_process import run_journey_case

SCENARIOS = "client/tests/qt_correction_note_scenarios.py"


@pytest.mark.parametrize("size", ["1050x700", "1280x800"])
def test_cash_saved_note_context_and_new_reason(pytestconfig, tmp_path, size):
    run_journey_case(
        f"test_cash_saved_note_context_and_new_reason[{size}]", pytestconfig, tmp_path, scenarios=SCENARIOS
    )


@pytest.mark.parametrize(
    "scenario",
    [
        "test_cash_save_withdraw_and_unrelated_row_draft",
        "test_stale_replacement_drops_only_the_old_entry_draft",
        "test_card_date_correction_requires_new_reason_and_preserves_date_policy",
        "test_register_category_correction_keeps_fixed_date_and_new_reason",
        "test_pending_and_multi_selection_keep_separate_notes",
    ],
)
def test_correction_note_scenario(pytestconfig, tmp_path, scenario):
    run_journey_case(scenario, pytestconfig, tmp_path, scenarios=SCENARIOS)
