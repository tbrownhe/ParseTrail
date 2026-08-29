"""Interactive local plugin-development launcher; this is not an automated test."""

import sys

from PySide6.QtWidgets import QApplication

from parsetrail.build_plugins import DEFAULT_PLUGINS_DIR, compile_plugins
from parsetrail.core.initialize import initialize_db
from parsetrail.core.plugin_manager import PluginManager
from parsetrail.core.settings import settings
from parsetrail.gui.plugins import ParseTestDialog


def main() -> None:
    compile_plugins()
    settings.plugin_dir = DEFAULT_PLUGINS_DIR

    session_maker = initialize_db()
    plugin_manager = PluginManager(
        plugin_dir=DEFAULT_PLUGINS_DIR,
        allow_unsigned=True,
    )
    plugin_manager.load_plugins()

    app = QApplication(sys.argv)
    window = ParseTestDialog(session_maker, plugin_manager)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
