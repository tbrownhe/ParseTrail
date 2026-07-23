import py_compile
from pathlib import Path

import pytest
from parsetrail.core.plugin_manifest import (
    PluginArtifactError,
    PluginDownloadCancelled,
)
from parsetrail.core.plugin_store import (
    install_plugin_release,
    read_active_release,
)
from parsetrail.core.plugins import PluginManager

from .plugin_release_helpers import signed_catalog, signed_release


def _chunks(payload: bytes, chunk_size: int = 4):
    for offset in range(0, len(payload), chunk_size):
        yield payload[offset : offset + chunk_size]


def _compile_plugin(
    tmp_path: Path,
    *,
    plugin_name: str,
    marker_path: Path,
) -> bytes:
    source_path = tmp_path / f"{plugin_name}.py"
    compiled_path = tmp_path / f"{plugin_name}.pyc"
    source_path.write_text(
        "\n".join(
            [
                "from pathlib import Path",
                "from parsetrail.core.interfaces import IParser",
                f"Path({str(marker_path)!r}).write_text('executed')",
                "class Parser(IParser):",
                f"    PLUGIN_NAME = {plugin_name!r}",
                "    VERSION = '1.0.0'",
                "    MIN_CLIENT_VERSION = '1.0.0'",
                "    SUFFIX = '.pdf'",
                "    COMPANY = 'Example Bank'",
                "    STATEMENT_TYPE = 'Example Statement'",
                "    SEARCH_STRING = 'example'",
                "    INSTRUCTIONS = 'Download a statement.'",
                "    def parse(self, input_data):",
                "        return input_data",
            ]
        ),
        encoding="utf-8",
    )
    py_compile.compile(source_path, cfile=compiled_path, doraise=True)
    return compiled_path.read_bytes()


def test_installs_complete_release_and_reloads_it(tmp_path: Path) -> None:
    payload = b"complete plugin"
    release, trusted_keys = signed_release(payload, release_sequence=100)
    plugin_root = tmp_path / "plugins"

    installed = install_plugin_release(
        plugin_root,
        release,
        lambda _: _chunks(payload),
    )
    loaded = read_active_release(plugin_root, trusted_keys)

    assert loaded is not None
    assert loaded.manifest.release_sequence == 100
    assert loaded.release_dir == installed.release_dir


def test_installs_every_plugin_before_activating_catalog(tmp_path: Path) -> None:
    payloads = {
        "alpha_plugin": b"alpha plugin bytes",
        "beta_plugin": b"beta plugin bytes",
    }
    release, trusted_keys = signed_catalog(
        payloads,
        release_sequence=101,
    )
    requested: list[str] = []

    def stream_plugin(filename: str):
        requested.append(filename)
        yield from _chunks(payloads[Path(filename).stem])

    plugin_root = tmp_path / "plugins"
    install_plugin_release(plugin_root, release, stream_plugin)
    loaded = read_active_release(plugin_root, trusted_keys)

    assert loaded is not None
    assert requested == ["alpha_plugin.pyc", "beta_plugin.pyc"]
    assert {path.name for path in loaded.release_dir.glob("*.pyc")} == {"alpha_plugin.pyc", "beta_plugin.pyc"}


def test_cancellation_preserves_previous_release(tmp_path: Path) -> None:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    signing_key = Ed25519PrivateKey.generate()
    first_payload = b"first complete plugin"
    second_payload = b"second complete plugin"
    first, trusted_keys = signed_release(
        first_payload,
        release_sequence=200,
        private_key=signing_key,
    )
    plugin_root = tmp_path / "plugins-cancel"
    current = install_plugin_release(
        plugin_root,
        first,
        lambda _: _chunks(first_payload),
    )
    second, _ = signed_release(
        second_payload,
        release_sequence=201,
        private_key=signing_key,
    )

    checks = 0

    def cancelled() -> bool:
        nonlocal checks
        checks += 1
        return checks >= 3

    with pytest.raises(PluginDownloadCancelled):
        install_plugin_release(
            plugin_root,
            second,
            lambda _: _chunks(second_payload),
            current=current,
            cancelled=cancelled,
        )

    still_active = read_active_release(plugin_root, trusted_keys)
    assert still_active is not None
    assert still_active.manifest.release_sequence == 200
    assert not any(path.name.startswith(".staging-") for path in (plugin_root / "releases").iterdir())


def test_truncation_preserves_previous_release(tmp_path: Path) -> None:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    signing_key = Ed25519PrivateKey.generate()
    first_payload = b"first complete plugin"
    first, trusted_keys = signed_release(
        first_payload,
        release_sequence=10,
        private_key=signing_key,
    )
    plugin_root = tmp_path / "plugins"
    current = install_plugin_release(
        plugin_root,
        first,
        lambda _: _chunks(first_payload),
    )
    second_payload = b"second complete plugin"
    second, _ = signed_release(
        second_payload,
        release_sequence=11,
        private_key=signing_key,
    )

    with pytest.raises(PluginArtifactError, match="truncated"):
        install_plugin_release(
            plugin_root,
            second,
            lambda _: [second_payload[:-1]],
            current=current,
        )

    still_active = read_active_release(plugin_root, trusted_keys)
    assert still_active is not None
    assert still_active.manifest.release_sequence == 10


def test_unsigned_legacy_plugin_is_never_executed(tmp_path: Path) -> None:
    marker_path = tmp_path / "marker.txt"
    plugin_bytes = _compile_plugin(
        tmp_path,
        plugin_name="unsigned_plugin",
        marker_path=marker_path,
    )
    plugin_root = tmp_path / "plugins"
    plugin_root.mkdir()
    (plugin_root / "unsigned_plugin.pyc").write_bytes(plugin_bytes)
    _, trusted_keys = signed_release(b"trust anchor")

    manager = PluginManager(
        plugin_dir=plugin_root,
        trusted_keys=trusted_keys,
    )
    manager.load_plugins()

    assert not marker_path.exists()
    assert manager.plugins == {}


def test_plugin_is_verified_before_dynamic_import(tmp_path: Path) -> None:
    marker_path = tmp_path / "marker.txt"
    plugin_bytes = _compile_plugin(
        tmp_path,
        plugin_name="signed_plugin",
        marker_path=marker_path,
    )
    release, trusted_keys = signed_release(
        plugin_bytes,
        release_sequence=300,
        plugin_name="signed_plugin",
    )
    plugin_root = tmp_path / "plugins"
    install_plugin_release(
        plugin_root,
        release,
        lambda _: _chunks(plugin_bytes),
    )

    manager = PluginManager(
        plugin_dir=plugin_root,
        trusted_keys=trusted_keys,
    )
    manager.load_plugins()

    assert marker_path.read_text(encoding="utf-8") == "executed"
    assert "signed_plugin" in manager.plugins


def test_tampered_installed_plugin_is_not_executed(tmp_path: Path) -> None:
    marker_path = tmp_path / "marker.txt"
    plugin_bytes = _compile_plugin(
        tmp_path,
        plugin_name="tampered_plugin",
        marker_path=marker_path,
    )
    release, trusted_keys = signed_release(
        plugin_bytes,
        release_sequence=400,
        plugin_name="tampered_plugin",
    )
    plugin_root = tmp_path / "plugins"
    installed = install_plugin_release(
        plugin_root,
        release,
        lambda _: _chunks(plugin_bytes),
    )
    (installed.release_dir / "tampered_plugin.pyc").write_bytes(b"tampered")

    manager = PluginManager(
        plugin_dir=plugin_root,
        trusted_keys=trusted_keys,
    )
    manager.load_plugins()

    assert not marker_path.exists()
    assert manager.plugins == {}
