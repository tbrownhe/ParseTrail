"""Compile packaging inputs without running an installer or touching installed 1.x."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

CLIENT = Path(__file__).parents[1]


def _compiler():
    candidate = os.environ.get("PARSETRAIL_TEST_NSIS_COMPILER") or shutil.which("makensis")
    if candidate is None:
        pytest.skip("NSIS compiler is an optional native-release prerequisite")
    return candidate


def _arguments(tmp_path):
    payload = tmp_path / "payload with spaces"
    payload.mkdir()
    (payload / "ParseTrail.exe").write_bytes(b"MZ public synthetic packaging fixture; not executable")
    switch = "/" if os.name == "nt" else "-"
    output = tmp_path / "unsigned fixture setup.exe"
    arguments = [
        _compiler(),
        switch + "NOCONFIG",
        switch + "OUTPUTCHARSET",
        "UTF8",
        switch + "DVERSION=0.0.0",
        switch + "DSOURCE_DIR=" + str(payload / "*.*"),
        switch + "DOUTPUT_PATH=" + str(output),
    ]
    return arguments, output


def test_compiler_expands_only_v2_install_upgrade_shortcut_and_uninstall_targets(tmp_path):
    arguments, _output = _arguments(tmp_path)
    switch = "/" if os.name == "nt" else "-"
    result = subprocess.run(
        [*arguments, switch + "SAFEPPO", str(CLIENT / "scripts/win64_installer.nsi")],
        capture_output=True,
        text=True,
        encoding="utf-8-sig",
        timeout=30,
        check=True,
    )
    script = result.stdout
    assert re.search(r'InstallDir\s+"\$PROGRAMFILES64\\ParseTrail 2"', script)
    assert re.search(r'ReadRegStr\s+\$R0\s+HKLM\s+"Software\\ParseTrail 2"', script)
    assert re.search(r'DeleteRegKey\s+HKLM\s+"Software\\ParseTrail 2"', script)
    assert "$DESKTOP\\ParseTrail 2.lnk" in script
    assert '"Software\\ParseTrail"' not in script
    assert '"Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\ParseTrail"' not in script
    assert "$DESKTOP\\ParseTrail.lnk" not in script
    assert "$SMPROGRAMS\\ParseTrail\\" not in script


def test_compiles_unsigned_fixture_with_explicit_source_output_overrides_without_installing(tmp_path):
    arguments, output = _arguments(tmp_path)
    subprocess.run(
        [*arguments, str(CLIENT / "scripts/win64_installer.nsi")],
        capture_output=True,
        text=True,
        encoding="utf-8-sig",
        timeout=60,
        check=True,
    )
    assert output.read_bytes().startswith(b"MZ") and output.stat().st_size > 10000


def test_mac_bundle_identity_is_separate_and_shell_syntax_valid():
    script = (CLIENT / "build_client_macos.sh").read_text()
    (name,) = re.findall(r'^APP_NAME="([^"]+)"$', script, re.M)
    assert name == "ParseTrail 2" and name != "ParseTrail"
    assert '--osx-bundle-identifier "com.parsetrail.client.v2"' in script
    assert '"${APP_PATH}/Contents/MacOS/${APP_NAME}"' in script
    assert '--icon "${APP_NAME}.app"' in script
    git = shutil.which("git")
    git_bash = Path(git).resolve().parents[1] / "bin/bash.exe" if os.name == "nt" and git else None
    shell = str(git_bash) if git_bash and git_bash.is_file() else shutil.which("bash")
    if shell:
        subprocess.run(
            [shell, "-n", str(CLIENT / "build_client_macos.sh")], capture_output=True, timeout=20, check=True
        )
