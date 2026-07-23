from pathlib import Path

import pytest
from parsetrail import build_plugins
from parsetrail.core.plugin_loader import load_plugin


def test_compiles_complete_source_catalog_and_removes_stale_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plugin_output = tmp_path / "plugins"
    plugin_output.mkdir()
    stale_plugin = plugin_output / "removed_plugin.pyc"
    stale_plugin.write_bytes(b"stale")
    monkeypatch.setattr(build_plugins, "PLUGINS_DIR", plugin_output)

    build_plugins.compile_plugins()

    source_count = len([path for path in build_plugins.SOURCE_DIR.glob("*.py") if path.stem != "__init__"])
    compiled_plugins = list(plugin_output.glob("*.pyc"))
    assert len(compiled_plugins) == source_count
    assert source_count == 19
    assert not stale_plugin.exists()
    assert {load_plugin(path)[0] for path in compiled_plugins} == {path.stem for path in compiled_plugins}
