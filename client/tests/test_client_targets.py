import pytest
from parsetrail.core import client_targets
from parsetrail.core.client_store import fetch_latest_installer

from scripts import release_bootstrap


@pytest.mark.parametrize(
    "system,machine,bits,expected",
    [
        ("Windows", "AMD64", 8, "windows-x86_64"),
        ("Windows", "x86_64", 8, "windows-x86_64"),
        ("Darwin", "x86_64", 8, "macos-x86_64"),
        ("Darwin", "arm64", 8, None),
        ("Windows", "ARM64", 8, None),
        ("Windows", "x86", 4, None),
        ("Windows", "AMD64", 4, None),
        ("Linux", "x86_64", 8, None),
        ("Darwin", "unknown", 8, None),
    ],
)
def test_runtime_and_bootstrap_agree_on_supported_process_targets(monkeypatch, system, machine, bits, expected):
    monkeypatch.setattr(client_targets.platform, "system", lambda: system)
    monkeypatch.setattr(client_targets.platform, "machine", lambda: machine)
    monkeypatch.setattr(client_targets.struct, "calcsize", lambda _format: bits)
    assert client_targets.native_installer_target() == expected
    if expected is not None:
        assert release_bootstrap._validate_target(expected) == expected


@pytest.mark.parametrize("platform", ["win64", "macos", "macos-arm64", "windows-arm64", "linux64", "unsupported"])
def test_old_ambiguous_and_unsupported_targets_make_no_network_requests(platform):
    class UnavailableSource:
        def fetch_client_release_bytes(self, _platform):
            pytest.fail("Unsupported target must not request an installer")

    assert fetch_latest_installer(UnavailableSource(), platform) is None
