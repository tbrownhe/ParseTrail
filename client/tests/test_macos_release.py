"""Portable failure-path checks; actual Mach-O and installed-app acceptance is native."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import macos_release as native
from scripts import release_bootstrap as launcher


@pytest.fixture
def toolchain(tmp_path, monkeypatch):
    prefix = tmp_path / "Homebrew OpenSSL"
    for name in ("lib/libssl.a", "lib/libcrypto.a", "include/openssl/ssl.h", "lib/pkgconfig/openssl.pc", "bin/openssl"):
        path = prefix / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"synthetic build input")
    state = SimpleNamespace(prefix=prefix, calls=[], missing=None, rust="1.83.0", arch="x86_64")
    monkeypatch.setattr(native.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(native.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(native.platform, "mac_ver", lambda: ("13.7.8", ("", "", ""), "x86_64"))
    monkeypatch.setattr(native.shutil, "which", lambda name: None if name == state.missing else name)

    def run(command, *, env=None, timeout=30):
        assert timeout > 0
        state.calls.append((command, env))
        name = Path(command[0]).name
        if command[:2] == ["brew", "--prefix"]:
            return str(prefix)
        if name == "rustc":
            return f"rustc test\nhost: x86_64-apple-darwin\nrelease: {state.rust}"
        if name == "openssl":
            return "OpenSSL 3.5.0 test"
        if command[:2] == ["pkg-config", "--modversion"]:
            assert env["PKG_CONFIG_LIBDIR"] == str(prefix / "lib/pkgconfig")
            return "3.5.0"
        if name == "lipo":
            return state.arch
        if name == "xcrun":
            return "11.3"
        return f"{name} test version"

    monkeypatch.setattr(native, "_run", run)
    return state


def test_preflight_records_inputs_and_overrides_dynamic_and_cross_target_openssl_settings(toolchain, monkeypatch):
    monkeypatch.setenv("OPENSSL_STATIC", "0")
    monkeypatch.setenv("X86_64_APPLE_DARWIN_OPENSSL_LIB_DIR", "/wrong/lib")
    monkeypatch.setenv("CARGO_BUILD_TARGET", "aarch64-apple-darwin")
    env, inputs = native.preflight()
    assert env["OPENSSL_STATIC"] == env["X86_64_APPLE_DARWIN_OPENSSL_STATIC"] == "1"
    assert env["OPENSSL_DIR"] == str(toolchain.prefix)
    assert env["X86_64_APPLE_DARWIN_OPENSSL_LIB_DIR"] == str(toolchain.prefix / "lib")
    assert env["CARGO_BUILD_TARGET"] == "x86_64-apple-darwin"
    assert inputs["openssl_static"] is True
    assert inputs["macos_version"] == "13.7.8"
    assert inputs["macos_sdk"] == "11.3"  # An older SDK does not imply an unsupported running OS.
    assert set(inputs["openssl_archives_sha256"]) == {"libssl.a", "libcrypto.a"}
    assert str(toolchain.prefix) not in json.dumps(inputs)
    assert os.environ["OPENSSL_STATIC"] == "0"  # Only build subprocesses inherit the overrides.


@pytest.mark.parametrize("version", ["11.7.10", "12.7.6", "", "unknown"])
def test_unsupported_or_unknown_running_os_fails_before_native_tools(toolchain, monkeypatch, version):
    monkeypatch.setattr(native.platform, "mac_ver", lambda: (version, ("", "", ""), "x86_64"))
    with pytest.raises(native.MacReleaseError, match="macOS"):
        native.preflight()
    assert toolchain.calls == []


@pytest.mark.parametrize(
    "missing", ["brew", "rustc", "cargo", "pkg-config", "clang", "xcrun", "lipo", "otool", "create-dmg"]
)
def test_missing_tool_cannot_reach_dependency_sync(toolchain, monkeypatch, missing):
    toolchain.missing = missing
    monkeypatch.setattr(native.subprocess, "run", lambda *args, **kwargs: pytest.fail("package sync must not start"))
    with pytest.raises(native.MacReleaseError, match=f"Missing {missing}"):
        native.sync_dependencies(fresh_cryptography=True, output=None)


@pytest.mark.parametrize("version", ["1.82.9", "1.83.0-nightly", "invalid"])
def test_old_or_unstable_rust_is_rejected(toolchain, version):
    toolchain.rust = version
    with pytest.raises(native.MacReleaseError, match="stable Rust"):
        native.preflight()


def test_wrong_static_archive_architecture_is_rejected(toolchain):
    toolchain.arch = "arm64"
    with pytest.raises(native.MacReleaseError, match="no Intel"):
        native.preflight()


def test_missing_static_openssl_archive_is_rejected(toolchain):
    (toolchain.prefix / "lib/libcrypto.a").unlink()
    with pytest.raises(native.MacReleaseError, match="libcrypto.a"):
        native.preflight()


def test_final_sync_cannot_reuse_cryptography_built_with_old_link_settings(toolchain, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(
        native.subprocess,
        "run",
        lambda command, **kwargs: calls.append((command, kwargs)) or SimpleNamespace(returncode=0),
    )
    report = tmp_path / "inputs.json"
    native.sync_dependencies(fresh_cryptography=True, output=report)
    command, options = calls[0]
    assert {"--no-cache", "--reinstall-package", "cryptography", "--frozen", "--no-python-downloads"} <= set(command)
    assert command[command.index("--python") + 1] == sys.executable
    assert options["env"]["OPENSSL_STATIC"] == "1"
    assert options["env"]["OPENSSL_DIR"] == str(toolchain.prefix)
    assert json.loads(report.read_text())["build_inputs"]["openssl_static"] is True


@pytest.mark.parametrize("failed", [True, False])
def test_mac_launcher_uses_native_preflight_sync_before_release_dispatch(monkeypatch, failed):
    runtime = launcher.ReleaseRuntime("uv", "0.12.5", "3.13.15", sys.executable, "macos-x86_64")
    monkeypatch.setattr(launcher, "bootstrap", lambda _target: runtime)
    monkeypatch.setattr(launcher, "_run", lambda *args, **kwargs: pytest.fail("generic sync bypasses native preflight"))
    calls = []

    def run(command, **_kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=3 if failed else 0)

    monkeypatch.setattr(launcher.subprocess, "run", run)
    assert launcher.main(["--config", "release.json", "client", "--platform", "macos-x86_64"]) == (1 if failed else 0)
    assert Path(calls[0][3]).name == "macos_release.py"
    assert calls[0][-1] == "sync"
    assert len(calls) == (1 if failed else 2)
    if not failed:
        assert "--no-sync" in calls[1]


def load_commands(*dependencies, rpaths=()):
    # otool -l structure, including LC_ID_DYLIB which is not a linked dependency.
    records = [("LC_ID_DYLIB", "name", "/old/build/identity.dylib")]
    records += [("LC_LOAD_DYLIB", "name", name) for name in dependencies]
    records += [("LC_RPATH", "path", name) for name in rpaths]
    return "test binary:\n" + "".join(
        f"Load command {index}\n          cmd {kind}\n      cmdsize 72\n         {field} {name} (offset 24)\n"
        for index, (kind, field, name) in enumerate(records)
    )


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    root = tmp_path / "ParseTrail.app"
    executable = root / "Contents/MacOS/ParseTrail"
    library = root / "Contents/Frameworks/library.dylib"
    crypto = root / "Contents/Frameworks/cryptography/hazmat/bindings/_rust.abi3.so"
    for path in (executable, library, crypto):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(bytes.fromhex("cffaedfe") + b"synthetic Mach-O")
    commands = {
        executable: load_commands("@rpath/library.dylib", rpaths=["@executable_path/../Frameworks"]),
        library: load_commands("/usr/lib/libSystem.B.dylib"),
        crypto: load_commands("/System/Library/Frameworks/Security.framework/Versions/A/Security"),
    }
    monkeypatch.setattr(native, "_require_intel_mac", lambda: None)
    monkeypatch.setattr(native, "_require_tool", lambda name: name)
    monkeypatch.setattr(native, "_run", lambda command, **kwargs: commands[Path(command[-1])])
    return SimpleNamespace(root=root, executable=executable, library=library, crypto=crypto, commands=commands)


def test_audit_accepts_resolved_bundle_and_system_libraries_ignores_install_identity(bundle):
    report = native.audit_bundle(bundle.root)
    assert report["macho_files"] == 3
    assert report["cryptography_extensions"] == 1
    assert str(bundle.root) not in json.dumps(report)


@pytest.mark.parametrize(
    "dependency",
    [
        "/usr/local/opt/openssl@3/lib/libssl.3.dylib",
        "/opt/homebrew/lib/libother.dylib",
        "/Users/builder/private/libother.dylib",
        "/usr/lib/../../Users/builder/libother.dylib",
        "librelative.dylib",
        "@rpath/missing.dylib",
        "@loader_path/../../../outside.dylib",
    ],
)
def test_audit_rejects_external_missing_and_nonrelocatable_dependencies(bundle, dependency):
    bundle.commands[bundle.library] = load_commands(dependency)
    with pytest.raises(native.MacReleaseError, match="library|escapes"):
        native.audit_bundle(bundle.root)


def test_audit_rejects_workstation_rpath_even_when_unused(bundle):
    bundle.commands[bundle.library] = load_commands("/usr/lib/libSystem.B.dylib", rpaths=["/usr/local/lib"])
    with pytest.raises(native.MacReleaseError, match="Non-relocatable"):
        native.audit_bundle(bundle.root)


def test_audit_rejects_dynamic_openssl_even_when_bundled(bundle):
    ssl = bundle.library.with_name("libssl.3.dylib")
    ssl.write_bytes(bundle.library.read_bytes())
    bundle.commands[ssl] = load_commands("/usr/lib/libSystem.B.dylib")
    bundle.commands[bundle.crypto] = load_commands("@rpath/libssl.3.dylib")
    with pytest.raises(native.MacReleaseError, match="statically"):
        native.audit_bundle(bundle.root)


def test_audit_cannot_claim_static_crypto_when_extension_is_missing(bundle):
    bundle.crypto.unlink()
    with pytest.raises(native.MacReleaseError, match="missing the cryptography"):
        native.audit_bundle(bundle.root)


def test_audit_follows_loader_relative_libraries_and_rejects_invalid_macho(bundle):
    bundle.commands[bundle.crypto] = load_commands("@loader_path/../../../library.dylib")
    native.audit_bundle(bundle.root)
    bundle.library.write_bytes(b"a text file is not a native library")
    with pytest.raises(native.MacReleaseError, match="Unresolved"):
        native.audit_bundle(bundle.root)


@pytest.mark.parametrize("output", ["", "not Mach-O", "Load command 0\n cmd LC_LOAD_DYLIB\n"])
def test_malformed_otool_output_fails_closed(output):
    with pytest.raises(native.MacReleaseError):
        native._load_commands(output)


def test_smoke_removes_toolchain_environment_and_uses_disposable_profile(bundle, monkeypatch):
    monkeypatch.setenv("DYLD_LIBRARY_PATH", "/usr/local/lib")
    monkeypatch.setenv("OPENSSL_DIR", "/usr/local/opt/openssl@3")
    monkeypatch.setenv("PYTHONPATH", "/source/client")
    calls = []

    def run(command, *, env, timeout):
        calls.append((command, env, timeout))
        assert Path(env["HOME"]).is_dir()
        return ""

    monkeypatch.setattr(native, "_run", run)
    report = native.smoke_test(bundle.root)
    command, env, timeout = calls[0]
    assert command[-1] == "--runtime-smoke-test"
    assert timeout == 30
    assert env["PATH"] == "/usr/bin:/bin:/usr/sbin:/sbin"
    assert not {"DYLD_LIBRARY_PATH", "OPENSSL_DIR", "PYTHONPATH"} & env.keys()
    assert not Path(env["HOME"]).exists()
    assert report["passed"] is True
    assert [command[1:] for command, _env, _timeout in calls] == [
        ["--runtime-smoke-test"],
        ["--offline-session-smoke-test", "fresh"],
        ["--offline-session-smoke-test", "cached"],
        ["--offline-session-smoke-test", "network-failure"],
    ]
    assert [timeout for _command, _env, timeout in calls] == [30, 75, 75, 75]
    assert report["offline_session"]["passed"] is True


def test_process_timeout_and_nonzero_exit_cannot_pass_smoke(monkeypatch):
    def timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired("frozen", 30)

    monkeypatch.setattr(native.subprocess, "run", timeout)
    with pytest.raises(native.MacReleaseError, match="TimeoutExpired"):
        native._run(["frozen"], timeout=30)
    monkeypatch.setattr(native.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=1))
    with pytest.raises(native.MacReleaseError, match="exit 1"):
        native._run(["frozen"])


def test_native_smoke_exercises_real_libraries_without_network(monkeypatch):
    import socket

    from parsetrail.core.runtime_smoke import check_native_operations

    def denied(*_args, **_kwargs):
        pytest.fail("Native library smoke must use only synthetic local data")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    check_native_operations()


def test_macos_gate_help_is_package_free():
    result = subprocess.run(
        [sys.executable, "-I", "-S", native.__file__, "--help"], capture_output=True, text=True, timeout=30
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(sys.platform != "darwin", reason="Native Bash builder integration")
def test_direct_mac_builder_stops_before_project_uv_when_toolchain_is_missing(tmp_path):
    root = tmp_path / "client"
    (root / "scripts").mkdir(parents=True)
    (root / "src/parsetrail").mkdir(parents=True)
    shutil.copyfile(native.__file__, root / "scripts/macos_release.py")
    shutil.copyfile(native.CLIENT_ROOT / "build_client_macos.sh", root / "build_client_macos.sh")
    (root / ".python-version").write_text("3.13.15\n")
    (root / "src/parsetrail/version.py").write_text('__version__ = "1.3.1"\n')
    installers = tmp_path / "installers"
    installers.mkdir()
    key = tmp_path / "dummy-key.pem"
    key.write_text("not a signing key")
    commands = tmp_path / "commands"
    commands.mkdir()
    call_log = tmp_path / "uv-calls.txt"
    import shlex

    uv = commands / "uv"
    uv.write_text(
        f'#!/bin/bash\nprintf "%s\\n" "$*" >> {shlex.quote(str(call_log))}\nprintf "%s\\n" {shlex.quote(sys.executable)}\n'
    )
    uv.chmod(0o755)
    dmg = commands / "create-dmg"
    dmg.write_text('#!/bin/bash\necho "create-dmg test"\n')
    dmg.chmod(0o755)
    env = os.environ | {"PATH": f"{commands}:/usr/bin:/bin"}
    result = subprocess.run(
        ["/bin/bash", str(root / "build_client_macos.sh"), "--clients-dir", str(installers), "--signing-key", str(key)],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode != 0
    assert "Missing brew" in result.stderr
    assert call_log.read_text().splitlines() == [
        "run --no-env-file --script scripts/release_bootstrap.py check --platform macos-x86_64 --print-python"
    ]
