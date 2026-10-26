import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from parsetrail import main as main_module


def test_runtime_smoke_test_exits_before_gui_startup(monkeypatch):
    monkeypatch.setattr(main_module, "system", lambda: "Linux")
    monkeypatch.setattr(
        sys,
        "argv",
        ["parsetrail", main_module.RUNTIME_SMOKE_TEST_ARGUMENT],
    )

    assert main_module.main() == 0


@pytest.mark.parametrize("args", [["--unknown"], ["--create-profile"], ["--staging", "https://staging.example/api/v1"]])
def test_unsupported_ordinary_arguments_are_rejected_before_gui_or_configuration_imports(tmp_path, args):
    code = """
import importlib.abc,sys
class Guard(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(("PySide6","parsetrail.core.v2_","parsetrail.core.settings","parsetrail.core.profile","parsetrail.gui")):
            raise AssertionError("Import before argument validation: "+fullname)
sys.meta_path.insert(0,Guard())
from parsetrail.main import main
raise SystemExit(main())
"""
    env = os.environ | {
        "PYTHONPATH": str(Path(__file__).parents[1] / "src"),
        "HOME": str(tmp_path),
        "USERPROFILE": str(tmp_path),
        "APPDATA": str(tmp_path),
    }
    result = subprocess.run(
        [sys.executable, "-c", code, *args],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=15,
    )
    assert result.returncode == 2 and "Import before argument" not in result.stderr
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "name,module",
    [
        ("annotation-period", "v2_pdf_annotation_worker"),
        ("xlsx-evidence", "v2_xlsx_worker"),
        ("anchored-table", "v2_anchored_table_worker"),
        ("wells-table", "v2_wells_table_worker"),
        ("citi-table", "v2_citi_table_worker"),
        ("simple", "v2_pdf_text_worker"),
    ],
)
def test_every_worker_dispatch_exits_before_gui(monkeypatch, name, module):
    calls = []
    monkeypatch.setitem(
        sys.modules, "parsetrail.core." + module, SimpleNamespace(main=lambda args: calls.append(args) or 23)
    )
    monkeypatch.setattr(main_module, "create_application", lambda *_args: pytest.fail("Worker opened GUI"))
    monkeypatch.setattr(sys, "argv", ["parsetrail", "--v2-parser-worker", name, "limit"])
    assert main_module.main() == 23
    assert calls == [[name, "limit"] if name == "simple" else ["limit"]]


def test_fixture_and_offline_dispatch_do_not_open_ordinary_gui(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(main_module, "create_application", lambda *_args: pytest.fail("Diagnostic opened ordinary GUI"))
    monkeypatch.setitem(
        sys.modules,
        "parsetrail.core.v2_fixture_verification",
        SimpleNamespace(main=lambda args: calls.append(args) or 24),
    )
    monkeypatch.setattr(sys, "argv", ["parsetrail", "--v2-verify-fixtures", "input", "--report", "output"])
    assert main_module.main() == 24 and calls == [["--v2-verify-fixtures", "input", "--report", "output"]]

    def offline(mode, entrypoint, *, report_path):
        assert mode == "cached" and entrypoint is main_module.main and report_path == tmp_path / "report.json"
        assert sys.argv == ["parsetrail"]
        return 25

    monkeypatch.setitem(
        sys.modules, "parsetrail.core.v2_offline_smoke", SimpleNamespace(run_offline_session_smoke=offline)
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "parsetrail",
            "--offline-session-smoke-test",
            "cached",
            "--offline-smoke-report",
            str(tmp_path / "report.json"),
        ],
    )
    assert main_module.main() == 25


def test_native_explicit_profile_context_is_isolated_and_restored(monkeypatch, tmp_path):
    original = tmp_path / "owner.db"
    original.write_bytes(b"owner data stays untouched")
    monkeypatch.setenv("DB_PATH", str(original))
    monkeypatch.setenv("PARSETRAIL_PROFILE", "invalid-owner-environment")
    seen = []

    def native():
        assert "DB_PATH" not in os.environ
        assert os.environ["PARSETRAIL_PROFILE"] == "staging"
        assert os.environ["PARSETRAIL_STAGING_SERVER_URL"] == "https://staging.example/api/v1"
        seen.append(Path.home())
        return 0

    monkeypatch.setattr(main_module, "run_runtime_smoke_test", native)
    monkeypatch.setattr(
        sys, "argv", ["parsetrail", "--staging", "https://staging.example/api/v1/", "--runtime-smoke-test"]
    )
    assert main_module.main() == 0 and len(seen) == 1 and not seen[0].exists()
    assert original.read_bytes() == b"owner data stays untouched"
    assert os.environ["DB_PATH"] == str(original) and os.environ["PARSETRAIL_PROFILE"] == "invalid-owner-environment"


def test_default_cancel_ignores_poisoned_legacy_environment_and_imports(tmp_path):
    canary = tmp_path / "owner.db"
    canary.write_bytes(b"preserve owner legacy bytes")
    code = """
import importlib.abc,sys,json
class Guard(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname.startswith(("parsetrail.core.settings","parsetrail.core.profile","parsetrail.core.credentials","parsetrail.core.utils","parsetrail.core.initialize","parsetrail.core.auth","parsetrail.core.logging","parsetrail.gui.bootstrap","parsetrail.gui.main_window","dotenv")):
            raise AssertionError("Forbidden legacy import: "+fullname)
sys.meta_path.insert(0,Guard())
from PySide6.QtWidgets import QDialog
from parsetrail.gui.v2_profile_startup import V2ProfileStartupDialog
V2ProfileStartupDialog.exec=lambda self:QDialog.Rejected
from parsetrail.main import main,handle_signal
result=main()
try:handle_signal(2,None)
except SystemExit as interrupted:assert interrupted.code==0
print(json.dumps({"returncode":result,"legacy_loaded":any(name in sys.modules for name in ("parsetrail.core.settings","parsetrail.gui.main_window"))}))
"""
    env = os.environ | {
        "PYTHONPATH": str(Path(__file__).parents[1] / "src"),
        "QT_QPA_PLATFORM": "offscreen",
        "HOME": str(tmp_path),
        "USERPROFILE": str(tmp_path),
        "APPDATA": str(tmp_path),
        "PARSETRAIL_PROFILE": "invalid",
        "DB_PATH": str(canary),
        "MODEL_PATH": str(canary),
        "PLUGIN_DIR": str(canary),
        "PYTHON_KEYRING_BACKEND": "invalid.backend",
    }
    result = subprocess.run(
        [sys.executable, "-c", code], cwd=tmp_path, env=env, capture_output=True, text=True, check=False, timeout=20
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.splitlines()[-1]) == {"returncode": 0, "legacy_loaded": False}
    assert canary.read_bytes() == b"preserve owner legacy bytes"
    assert {p.name for p in tmp_path.iterdir()} == {"owner.db"}


def test_frozen_icon_lookup_uses_bundle_asset_without_legacy_utilities(tmp_path, monkeypatch):
    import shutil

    from PySide6.QtWidgets import QApplication

    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    assets = tmp_path / "assets"
    assets.mkdir()
    shutil.copyfile(
        Path(main_module.__file__).resolve().parents[2] / "assets/parsetrail_128px.ico", assets / "parsetrail_128px.ico"
    )
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    closed = []
    monkeypatch.setitem(sys.modules, "pyi_splash", SimpleNamespace(close=lambda: closed.append(True)))
    main_module._prepare_application(app)
    assert not app.windowIcon().isNull() and closed == [True]
