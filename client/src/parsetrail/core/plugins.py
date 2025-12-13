import importlib.util
from pathlib import Path

from loguru import logger
from parsetrail.core.api import api_client
from parsetrail.core.interfaces import IParser, class_variables, validate_parser
from parsetrail.core.settings import settings
from parsetrail.core.utils import is_newer_version
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import QApplication, QProgressDialog


def load_plugin(plugin_file: Path) -> tuple[str, IParser, dict[str, str]]:
    """
    Dynamically load the Parser class from a plugin module, validate it, and retrieve metadata.
    plugin_file.name like 'pdf_citicc_v0.1.0.pyc'
    """
    # Load the module from file
    plugin_name = plugin_file.stem
    spec = importlib.util.spec_from_file_location(plugin_name, plugin_file)
    if not spec or not spec.loader:
        raise ImportError(f"Cannot load module from {plugin_file}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # Ensure this module contains a Parser(IParser)
    ParserClass = getattr(module, "Parser", None)
    if not ParserClass:
        raise ValueError(f"No 'Parser' class found in {plugin_file}")
    if not isinstance(ParserClass, IParser):
        raise TypeError(f"Plugin {plugin_name} must implement IParser")

    # Validate that the plugin overrides required class variables (metadata)
    required_variables = class_variables(IParser)
    validate_parser(ParserClass, required_variables)
    metadata = {var: getattr(ParserClass, var) for var in required_variables}
    metadata["FILENAME"] = plugin_file.name

    return plugin_name, ParserClass, metadata


class PluginManager:
    def __init__(self):
        self.plugins = None
        self.metadata = None

    def load_plugins(self):
        """
        Load all plugins in the specified path.
        """
        self.plugins = {}
        self.metadata = {}

        success = 0
        for plugin_file in settings.plugin_dir.glob("*.pyc"):
            # Retrieve the Parser(Iparser) class from the plugin and store it
            try:
                plugin_id, ParserClass, metadata = load_plugin(plugin_file)
                self.plugins[plugin_id] = ParserClass
                self.metadata[plugin_id] = metadata
                success += 1
            except Exception as e:
                logger.error(f"Failed to load {plugin_file}: {e}")

        if success > 0:
            logger.success(f"Loaded {success} plugins")

        # Build the set of supported file extensions
        self.suffixes = sorted(set(plugin["SUFFIX"] for plugin in self.metadata.values()))

    def get_parser(self, plugin_id: str):
        """
        Retrieve a specific parser class from the preloaded plugins.
        """
        ParserClass = self.plugins.get(plugin_id)
        if not ParserClass:
            raise ImportError(f"Plugin '{plugin_id}' not loaded.")
        return ParserClass


def get_plugin_lists(plugin_manager: PluginManager) -> tuple[list, list]:
    """Silently downloads any new updated plugins to local machine

    Args:
        plugin_manager (PluginManager): PluginManager

    Returns:
        tuple[list, list]: local_plugins, server_plugins
    """
    local_plugins = [plugin for plugin in plugin_manager.metadata.values()]
    server_plugins = api_client.list_plugins()
    return local_plugins, server_plugins


def download_plugin(plugin_fname: str):
    """
    Downloads a specific plugin from the server.
    """
    settings.plugin_dir.mkdir(parents=True, exist_ok=True)
    dpath = settings.plugin_dir / plugin_fname
    try:
        with dpath.open("wb") as f:
            for chunk, _, _ in api_client.stream_plugin(plugin_fname):
                f.write(chunk)
        logger.success(f"Downloaded plugin {plugin_fname}")
    except Exception as e:
        logger.error(f"Error downloading plugin {plugin_fname}: {e}")
        raise


def compare_plugins(local_plugins: list[dict], server_plugins: list[dict]) -> list[dict]:
    new_plugins = []
    for server_plugin in server_plugins:
        plugin_name = server_plugin["PLUGIN_NAME"]
        local_plugin = next(
            (lp for lp in local_plugins if lp["PLUGIN_NAME"] == plugin_name),
            None,
        )
        if local_plugin is None or is_newer_version(local_plugin["VERSION"], server_plugin["VERSION"]):
            new_plugins.append(server_plugin)
    return new_plugins


def sync_plugins(local_plugins: list[dict], server_plugins: list[dict], progress=False, parent=None):
    """For each plugin on the server, downloads plugin if missing from local,
    and updates any obsolete plugins. Ignores plugins on user's machine that
    are not on the server in case something weird happens.

    Args:
        local_plugins (list[dict]): Local plugin metadata
        server_plugins (list[dict]): Remote plugin metadata
    """
    new_plugins = compare_plugins(local_plugins, server_plugins)

    if progress:
        dialog = QProgressDialog(
            "Updating Plugins",
            "Cancel",
            0,
            len(new_plugins),
            parent,
        )
        dialog.setMinimumWidth(400)
        dialog.setWindowTitle("Updating Plugins")
        dialog.setWindowModality(Qt.WindowModal)
        dialog.setMinimumDuration(100)
        dialog.setValue(0)
        dialog.show()
        QApplication.processEvents()

    for plugin in new_plugins:
        plugin_name = plugin["PLUGIN_NAME"]
        dialog.setLabelText(f"Downloading new {plugin_name}")
        try:
            download_plugin(plugin["FILENAME"])
            if progress:
                dialog.setValue(dialog.value() + 1)
                QApplication.processEvents()
        except Exception as e:
            logger.error(f"Failed to download new plugin {plugin_name}: {e}")
            raise

    if progress:
        dialog.close()


def check_for_plugin_updates(plugin_manager: PluginManager, parent=None) -> bool:
    """Silently downloads any new updated plugins to local machine

    Args:
        plugin_manager (PluginManager): PluginManager

    Returns:
        bool: Whether plugins were updated
    """
    local_plugins = [plugin for plugin in plugin_manager.metadata.values()]
    server_plugins = api_client.list_plugins()
    new_plugins = compare_plugins(local_plugins, server_plugins)
    if new_plugins:
        sync_plugins(local_plugins, server_plugins, progress=True, parent=parent)
        plugin_manager.load_plugins()
        return True
    return False


class PluginUpdateThread(QThread):
    """Checks for plugins in a separate thread"""

    update_available = pyqtSignal(list, list)
    update_complete = pyqtSignal(bool, str)

    def __init__(self, plugin_manager: PluginManager):
        super().__init__()
        self.plugin_manager = plugin_manager

    def run(self):
        try:
            local_plugins, server_plugins = get_plugin_lists(self.plugin_manager)
            new_plugins = compare_plugins(local_plugins, server_plugins)
            if new_plugins:
                self.update_available.emit(local_plugins, server_plugins)
            else:
                self.update_complete.emit(True, "Plugins are up to date.")
        except Exception as e:
            self.update_complete.emit(False, f"Plugin update Failed: {e}")
