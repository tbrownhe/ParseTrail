from pathlib import Path

from parsetrail import build_plugins
from parsetrail.core.plugin_loader import load_plugin


def test_compiles_complete_source_catalog_and_removes_stale_output(
    tmp_path: Path,
) -> None:
    plugin_output = tmp_path / "plugins"
    plugin_output.mkdir()
    stale_plugin = plugin_output / "removed_plugin.pyc"
    stale_plugin.write_bytes(b"stale")
    build_plugins.compile_plugins(plugin_output)

    source_count = len([path for path in build_plugins.SOURCE_DIR.glob("*.py") if path.stem != "__init__"])
    compiled_plugins = list(plugin_output.glob("*.pyc"))
    assert len(compiled_plugins) == source_count
    assert source_count == 20
    assert not stale_plugin.exists()
    assert {load_plugin(path)[0] for path in compiled_plugins} == {path.stem for path in compiled_plugins}
