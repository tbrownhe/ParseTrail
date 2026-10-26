"""Windows cross-principal handoff checks for public disposable catalog files."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows inherited catalog permissions")
TOOL = Path(__file__).with_name("prepare_demo.py")
TEST_SID = "S-1-5-21-111111111-222222222-333333333-4242"


def tool_module():
    spec = importlib.util.spec_from_file_location("catalog_handoff_demo", TOOL)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def powershell(tmp_path, script, *args):
    path = tmp_path / "acl-check.ps1"
    path.write_text("$ErrorActionPreference = 'Stop'\n" + script, encoding="utf-8")
    return subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(path), *args],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
        creationflags=subprocess.CREATE_NO_WINDOW,
    ).stdout


def test_inherited_read_access_reaches_catalog_leaves(tmp_path):
    root = tmp_path / "public-demo"
    releases = root / "catalog/releases"
    releases.mkdir(parents=True)
    powershell(
        tmp_path,
        """$parentPath, $testSid = $args
$acl = Get-Acl -LiteralPath $parentPath
$sid = [System.Security.Principal.SecurityIdentifier]::new($testSid)
$rule = [System.Security.AccessControl.FileSystemAccessRule]::new(
    $sid, 'ReadAndExecute', 'ContainerInherit,ObjectInherit', 'None', 'Allow')
$acl.AddAccessRule($rule)
Set-Acl -LiteralPath $parentPath -AclObject $acl
""",
        str(releases),
        TEST_SID,
    )
    # Reproduce the actual protected mode-0700 staging-directory rename.
    release = Path(tempfile.mkdtemp(dir=releases))
    files = (release / "catalog.json", release / "catalog.sig")
    for path, content in zip(files, (b"public fixture", b"fixture signature"), strict=True):
        path.write_bytes(content)
    profile = root / "review.db"
    profile.write_bytes(b"profile must stay untouched")
    before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in (*files, profile)}

    def inspect():
        return json.loads(
            powershell(
                tmp_path,
                """$releasePath, $testSid = $args
$result = foreach ($path in @($releasePath, (Join-Path $releasePath 'catalog.json'), (Join-Path $releasePath 'catalog.sig'))) {
    $acl = Get-Acl -LiteralPath $path
    $inheritedRead = @($acl.GetAccessRules($true, $true, [System.Security.Principal.SecurityIdentifier]) |
        Where-Object { $_.IdentityReference.Value -eq $testSid -and $_.IsInherited -and
            $_.AccessControlType -eq 'Allow' -and ([int]$_.FileSystemRights -band 1) -ne 0 }).Count -gt 0
    @{ protected = $acl.AreAccessRulesProtected; inherited_read = $inheritedRead }
}
ConvertTo-Json -InputObject @($result) -Compress
""",
                str(release),
                TEST_SID,
            )
        )

    original = inspect()
    assert original[0]["protected"] is True
    assert all(row["inherited_read"] is False for row in original)
    tool_module().inherit_public_catalog_access(root)
    repaired = inspect()
    assert all(row == {"protected": False, "inherited_read": True} for row in repaired)
    assert {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in before} == before


def test_unexpected_catalog_contents_refuse_before_acl_mutation(tmp_path, monkeypatch):
    release = tmp_path / "catalog/releases/fixture"
    release.mkdir(parents=True)
    for name in ("catalog.json", "catalog.sig", "unexpected.txt"):
        (release / name).write_bytes(b"keep")
    module = tool_module()

    def forbidden(*_args, **_kwargs):
        pytest.fail("unexpected catalog must not reach an ACL operation")

    monkeypatch.setattr(module.subprocess, "run", forbidden)
    with pytest.raises(ValueError, match="demo_catalog_shape"):
        module.inherit_public_catalog_access(tmp_path)


def test_acl_failure_stops_preparation(tmp_path, monkeypatch):
    release = tmp_path / "catalog/releases/fixture"
    release.mkdir(parents=True)
    for name in ("catalog.json", "catalog.sig"):
        (release / name).write_bytes(b"keep")
    module = tool_module()

    def fail(*args, **_kwargs):
        raise subprocess.CalledProcessError(5, args[0])

    monkeypatch.setattr(module.subprocess, "run", fail)
    with pytest.raises(subprocess.CalledProcessError):
        module.inherit_public_catalog_access(tmp_path)
