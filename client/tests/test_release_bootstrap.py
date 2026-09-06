"""Early release failures must never reach project dependency installation."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import release_bootstrap as launcher


@pytest.fixture
def builder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    (tmp_path / ".python-version").write_text("3.13.15\n", encoding="utf-8")
    interpreter = tmp_path / "managed python" / "python.exe"
    interpreter.parent.mkdir()
    interpreter.touch()
    state = SimpleNamespace(
        root=tmp_path,
        interpreter=interpreter,
        calls=[],
        uv="uv 0.12.5 (release build)",
        probe={
            "version": "3.13.15",
            "implementation": "CPython",
            "system": "Windows",
            "machine": "AMD64",
            "bits": 64,
            "free_threaded": False,
        },
        failed_phase=None,
    )

    def run(command, *, cwd, phase, timeout=60):
        assert cwd == tmp_path
        assert timeout > 0
        state.calls.append(command)
        if state.failed_phase and state.failed_phase in phase:
            raise launcher.BootstrapError("injected command failure")
        if command[1:] == ["--version"]:
            return state.uv
        if command[1:3] == ["python", "install"]:
            return ""
        if command[1:3] == ["python", "find"]:
            return str(interpreter)
        if command[0] == str(interpreter):
            return json.dumps(state.probe)
        raise AssertionError(f"Unexpected command before bootstrap completed: {command}")

    monkeypatch.setattr(launcher, "_run", run)
    monkeypatch.setattr(launcher.shutil, "which", lambda _name: "uv")
    monkeypatch.setattr(launcher.platform, "system", lambda: "Windows")
    monkeypatch.setattr(launcher.platform, "machine", lambda: "AMD64")
    return state


@pytest.mark.parametrize("target,system,machine", [("win64", "Windows", "AMD64"), ("macos", "Darwin", "x86_64")])
def test_provisions_and_inspects_exact_native_python_before_any_packages(builder, monkeypatch, target, system, machine):
    monkeypatch.setattr(launcher.platform, "system", lambda: system)
    monkeypatch.setattr(launcher.platform, "machine", lambda: machine)
    builder.probe.update(system=system, machine=machine)

    result = launcher.bootstrap(target, client_root=builder.root)

    assert result.interpreter == str(builder.interpreter)
    assert result.python_version == "3.13.15"
    assert result.target == target
    assert builder.calls[1][1:3] == ["python", "install"]
    assert "cpython-3.13.15" in builder.calls[1]
    assert "--no-bin" in builder.calls[1]
    assert ("--no-registry" in builder.calls[1]) == (target == "win64")
    assert {"--no-project", "--managed-python", "--system", "--no-python-downloads"} <= set(builder.calls[2])
    assert builder.calls[3][1:4] == ["-I", "-S", "-c"]
    assert len(builder.calls) == 4


def test_missing_uv_fails_without_provisioning(builder, monkeypatch):
    monkeypatch.setattr(launcher.shutil, "which", lambda _name: None)
    with pytest.raises(launcher.BootstrapError, match="not found"):
        launcher.bootstrap("win64", client_root=builder.root)
    assert builder.calls == []


@pytest.mark.parametrize("version", ["uv 0.12.4", "uv 0.12.5rc1", "uv 0.13.0-dev", "unexpected version"])
def test_old_or_unrecognized_uv_fails_before_provisioning(builder, version):
    builder.uv = version
    with pytest.raises(launcher.BootstrapError, match="stable uv version"):
        launcher.bootstrap("win64", client_root=builder.root)
    assert len(builder.calls) == 1


@pytest.mark.parametrize(
    "target,system,machine",
    [
        ("macos", "Windows", "AMD64"),
        ("win64", "Windows", "ARM64"),
        ("macos", "Darwin", "arm64"),
        (None, "Linux", "x86_64"),
    ],
)
def test_unsupported_host_fails_before_provisioning(builder, monkeypatch, target, system, machine):
    monkeypatch.setattr(launcher.platform, "system", lambda: system)
    monkeypatch.setattr(launcher.platform, "machine", lambda: machine)
    with pytest.raises(launcher.BootstrapError, match="host"):
        launcher.bootstrap(target, client_root=builder.root)
    assert len(builder.calls) == 1


@pytest.mark.parametrize("version", ["", "3.13", "3.13.15\n3.13.16", "3.13.15t", "../python.exe"])
def test_invalid_pin_fails_before_provisioning(builder, version):
    (builder.root / ".python-version").write_text(version, encoding="utf-8")
    with pytest.raises(launcher.BootstrapError, match="exact stable"):
        launcher.bootstrap("win64", client_root=builder.root)
    assert len(builder.calls) == 1


def test_missing_pin_fails_before_provisioning(builder):
    (builder.root / ".python-version").unlink()
    with pytest.raises(launcher.BootstrapError, match="Could not read"):
        launcher.bootstrap("win64", client_root=builder.root)
    assert len(builder.calls) == 1


def test_unavailable_interpreter_stops_at_provisioning(builder):
    builder.failed_phase = "Provisioning"
    with pytest.raises(launcher.BootstrapError, match="injected"):
        launcher.bootstrap("win64", client_root=builder.root)
    assert len(builder.calls) == 2


@pytest.mark.parametrize(
    "field,value",
    [
        ("version", "3.13.14"),
        ("implementation", "PyPy"),
        ("system", "Darwin"),
        ("machine", "ARM64"),
        ("bits", 32),
        ("free_threaded", True),
    ],
)
def test_wrong_interpreter_is_rejected_before_dependency_sync(builder, field, value):
    builder.probe[field] = value
    with pytest.raises(launcher.BootstrapError, match="inspection disagreed"):
        launcher.bootstrap("win64", client_root=builder.root)
    assert len(builder.calls) == 4


def test_failed_bootstrap_never_dispatches_dependency_sync_or_release(monkeypatch, capsys):
    calls = []

    def fail(_target):
        raise launcher.BootstrapError("cannot provision exact interpreter")

    monkeypatch.setattr(launcher, "bootstrap", fail)
    monkeypatch.setattr(launcher, "_run", lambda *args, **kwargs: calls.append(args))
    monkeypatch.setattr(launcher.subprocess, "run", lambda *args, **kwargs: calls.append(args))

    assert launcher.main(["--config", "release.json", "client", "--platform", "win64"]) == 1
    assert "cannot provision" in capsys.readouterr().err
    assert calls == []


def test_successful_launcher_pins_sync_and_preserves_interactive_release(tmp_path, monkeypatch):
    runtime = launcher.ReleaseRuntime("uv", "0.12.5", "3.13.15", str(tmp_path / "managed python.exe"), "win64")
    calls = []
    monkeypatch.setattr(launcher, "bootstrap", lambda _target: runtime)
    monkeypatch.setattr(launcher, "_run", lambda command, **kwargs: calls.append((command, kwargs)))

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=7)

    monkeypatch.setattr(launcher.subprocess, "run", run)
    config = tmp_path / "release config.json"
    assert launcher.main(["--config", str(config), "client", "--platform", "win64", "--publish"]) == 7
    assert len(calls) == 2
    assert calls[0][0][1] == "sync"
    for command, _kwargs in calls:
        assert command[command.index("--python") + 1] == runtime.interpreter
        assert "--no-python-downloads" in command
    command, kwargs = calls[1]
    assert "--no-sync" in command
    assert "--no-env-file" in command
    assert command[-6:] == ["--config", str(config), "client", "--platform", "win64", "--publish"]
    assert "capture_output" not in kwargs
    assert "stdin" not in kwargs


def test_bootstrap_help_needs_no_site_packages():
    result = subprocess.run(
        [sys.executable, "-S", str(Path(launcher.__file__)), "--help"], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_uv_script_ignores_broken_project_dependencies(tmp_path):
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv is needed for the script isolation contract")
    script = tmp_path / "release_bootstrap.py"
    script.write_text(Path(launcher.__file__).read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "broken-project"\nversion = "0.0.0"\ndependencies = ["parsetrail-must-never-resolve==0"]\n',
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            uv,
            "run",
            "--offline",
            "--no-env-file",
            "--cache-dir",
            str(tmp_path / "cache"),
            "--python",
            sys.executable,
            "--script",
            str(script),
            "--help",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert not (tmp_path / ".venv").exists()
    assert not (tmp_path / "uv.lock").exists()


def test_uv_enforces_inline_minimum_before_starting_python(tmp_path):
    uv = shutil.which("uv")
    if uv is None:
        pytest.skip("uv is needed for the script version contract")
    script = tmp_path / "future-bootstrap.py"
    script.write_text(
        '# /// script\n# dependencies = []\n# [tool.uv]\n# required-version = ">=99.0.0"\n# ///\n'
        'raise AssertionError("bootstrap must not execute")\n',
        encoding="utf-8",
    )
    result = subprocess.run(
        [uv, "run", "--offline", "--no-env-file", "--cache-dir", str(tmp_path / "cache"), "--script", str(script)],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode != 0
    assert "99.0.0" in result.stderr
    assert "bootstrap must not execute" not in result.stderr


@pytest.mark.skipif(sys.platform != "win32", reason="Windows builder integration")
def test_windows_builder_stops_before_project_sync_when_bootstrap_fails(tmp_path):
    installer_root = tmp_path / "installers"
    installer_root.mkdir()
    key = tmp_path / "dummy-key.pem"
    key.write_text("not a signing key", encoding="utf-8")
    builder_path = launcher.CLIENT_ROOT / "build_client_win64.ps1"

    def quote(path):
        return "'" + str(path).replace("'", "''") + "'"

    harness = (
        'function uv { Write-Host ("UV_CALL: " + ($args -join " ")); $global:LASTEXITCODE = 9 }\n'
        f"& {quote(builder_path)} -ClientsDir {quote(installer_root)} -SigningKey {quote(key)}\n"
    )
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", harness],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )
    assert result.returncode != 0
    assert "Release bootstrap failed" in result.stderr
    calls = [line for line in result.stdout.splitlines() if line.startswith("UV_CALL:")]
    assert len(calls) == 1
    assert "--script scripts/release_bootstrap.py check --platform win64" in calls[0]
