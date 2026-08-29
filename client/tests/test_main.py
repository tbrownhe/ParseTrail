import sys

from parsetrail import main as main_module


def test_runtime_smoke_test_exits_before_gui_startup(monkeypatch):
    monkeypatch.setattr(main_module, "system", lambda: "Linux")
    monkeypatch.setattr(
        sys,
        "argv",
        ["parsetrail", main_module.RUNTIME_SMOKE_TEST_ARGUMENT],
    )

    assert main_module.main() == 0
