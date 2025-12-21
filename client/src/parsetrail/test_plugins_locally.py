"""`cd client` before running as __main__"""

import sys

from parsetrail.build_plugins import PLUGINS_DIR, compile_plugins
from parsetrail.core.initialize import initialize_db
from parsetrail.core.plugins import PluginManager
from parsetrail.core.settings import settings
from parsetrail.gui.plugins import ParseTestDialog
from PyQt5.QtWidgets import QApplication

# Compile plugins into dist/plugins
compile_plugins()

# Manually set the plugin dir to the local plugin dist dir
settings.plugin_dir = PLUGINS_DIR

# Initialze db and plugin manager
Session = initialize_db()
plugin_manager = PluginManager()
plugin_manager.load_plugins()

# Start the application
app = QApplication(sys.argv)
window = ParseTestDialog(Session, plugin_manager)
window.show()
sys.exit(app.exec_())
