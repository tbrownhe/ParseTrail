import os
import py_compile
from pathlib import Path

from loguru import logger

from parsetrail.core.plugin_loader import load_plugin

# Define source and destination directories
SOURCE_DIR = Path(__file__).resolve().parent / "plugins"

PROJECT_ENV_PATH = Path(__file__).resolve().parents[3] / ".env"
DEFAULT_PLUGINS_DIR = Path(__file__).resolve().parents[2] / "dist" / "plugins"


def _load_project_env() -> dict[str, str]:
    if not PROJECT_ENV_PATH.exists():
        return {}

    env_vars: dict[str, str] = {}
    for line in PROJECT_ENV_PATH.read_text().splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        env_vars[key.strip()] = value.strip().strip('"').strip("'")

    return env_vars


PROJECT_ENV = _load_project_env()
PLUGINS_DIR = Path(os.environ.get("PLUGINS_DIR") or PROJECT_ENV.get("PLUGINS_DIR") or DEFAULT_PLUGINS_DIR).expanduser()


def compile_plugins() -> None:
    PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
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
            compiled_path = PLUGINS_DIR / compiled_name
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

    for stale_plugin in PLUGINS_DIR.glob("*.pyc"):
        if stale_plugin.name not in compiled_names:
            stale_plugin.unlink()
            logger.info(f"Removed stale compiled plugin: {stale_plugin}")


def main() -> None:
    compile_plugins()


if __name__ == "__main__":
    main()
