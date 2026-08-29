import argparse
import py_compile
from pathlib import Path

from loguru import logger

from parsetrail.core.plugin_loader import load_plugin

# Define source and destination directories
SOURCE_DIR = Path(__file__).resolve().parent / "plugins"

DEFAULT_PLUGINS_DIR = Path(__file__).resolve().parents[2] / "dist" / "plugins"


def compile_plugins(output_dir: Path = DEFAULT_PLUGINS_DIR) -> None:
    output_dir = output_dir.expanduser().resolve()
    if not output_dir.parent.is_dir():
        raise FileNotFoundError(f"Plugin output parent directory does not exist: {output_dir.parent}")
    output_dir.mkdir(exist_ok=True)
    compiled_names: set[str] = set()
    failures: list[str] = []
    for plugin_file in sorted(SOURCE_DIR.glob("*.py")):
        if plugin_file.stem == "__init__":
            continue
        partial_path: Path | None = None
        try:
            _, _, metadata = load_plugin(plugin_file)
            plugin_name = metadata["PLUGIN_NAME"]
            compiled_name = f"{plugin_name}.pyc"
            if compiled_name in compiled_names:
                raise ValueError(f"Duplicate PLUGIN_NAME {plugin_name}")
            compiled_names.add(compiled_name)
            compiled_path = output_dir / compiled_name
            partial_path = compiled_path.with_name(f"{compiled_path.name}.part")

            py_compile.compile(
                plugin_file,
                cfile=partial_path,
                doraise=True,
            )
            partial_path.replace(compiled_path)
            logger.success(f"Compiled: {plugin_file} -> {compiled_path}")
        except Exception as e:
            logger.error(f"Failed to compile {plugin_file}: {e}")
            failures.append(f"{plugin_file.name}: {e}")
        finally:
            if partial_path is not None:
                partial_path.unlink(missing_ok=True)

    if failures:
        raise RuntimeError("Plugin compilation failed:\n" + "\n".join(failures))

    for stale_plugin in output_dir.glob("*.pyc"):
        if stale_plugin.name not in compiled_names:
            stale_plugin.unlink()
            logger.info(f"Removed stale compiled plugin: {stale_plugin}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Compile ParseTrail's complete plugin catalog")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_PLUGINS_DIR)
    args = parser.parse_args()
    compile_plugins(args.output_dir)


if __name__ == "__main__":
    main()
