import json
import py_compile
from pathlib import Path

from loguru import logger

from parsetrail.core.plugins import load_plugin

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
PLUGINS_DIR = Path(PROJECT_ENV.get("PLUGINS_DIR")).expanduser()


def compile_plugins():
    PLUGINS_DIR.mkdir(parents=True, exist_ok=True)
    for plugin_file in SOURCE_DIR.glob("*.py"):
        if plugin_file.stem == "__init__":
            continue
        try:
            # Load metadata from the plugin
            _, _, metadata = load_plugin(plugin_file)

            # Plugin name based on internal metadata to ensure single source of truth
            plugin_name = metadata["PLUGIN_NAME"]
            compiled_name = f"{plugin_name}.pyc"
            compiled_path = PLUGINS_DIR / compiled_name

            # Compile the plugin to a .pyc file
            py_compile.compile(plugin_file, cfile=compiled_path)

            # Copy to the server data/plugins directory for deployment
            logger.success(f"Compiled: {plugin_file} -> {compiled_path}")
        except Exception as e:
            logger.error(f"Failed to compile {plugin_file}: {e}")


def generate_metadata():
    """
    Generate metadata for all .pyc files in server data dir
    Must be done here since .pyc files must be read by the same version of
    Python they were compiled with.
    """
    metadata_file = PLUGINS_DIR / "plugin_metadata.json"
    metadata_list = []
    for plugin_file in PLUGINS_DIR.glob("*.pyc"):
        try:
            # Get the metadata
            _, _, metadata = load_plugin(plugin_file)

            # Remove any secret sauce
            for del_key in ["SEARCH_STRING", "INSTRUCTIONS"]:
                if del_key in metadata:
                    del metadata[del_key]

            # Add the filename
            metadata["FILENAME"] = plugin_file.name

            # Add to the list
            metadata_list.append(metadata)
        except Exception as e:
            logger.exception(f"Failed to extract metadata for {plugin_file}: {e}")

    with metadata_file.open("w") as f:
        json.dump(metadata_list, f, indent=2)

    logger.success(f"Created server metadata file {metadata_file}")


def main():
    compile_plugins()
    generate_metadata()


if __name__ == "__main__":
    main()
