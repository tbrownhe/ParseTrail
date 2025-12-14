import os
import signal
import sys
from contextlib import suppress
from platform import system

from parsetrail.core.utils import resource_path
from parsetrail.core.logging import logger
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import QApplication

# Set PyQt environment variables
os.environ.setdefault("QT_API", "PyQt5")  # Qt bindings
os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"  # Enable HiDPI scaling

# Platform-specific environment configurations
system_name = system()
if system_name == "Windows":
    os.environ["QT_QPA_PLATFORM"] = "windows"


def handle_signal(signal, frame):
    logger.info("Application interrupted. Exiting...")
    sys.exit(0)


# Client entry point
def main() -> int:
    # Imports that depend on settings
    from parsetrail.gui.bootstrap import configure_ui_hooks
    from parsetrail.gui.main_window import ParseTrail

    # Handle system interrupts (e.g., Ctrl+C)
    signal.signal(signal.SIGINT, handle_signal)

    # Close the splash screen
    with suppress(ModuleNotFoundError):
        import pyi_splash  # type: ignore

        pyi_splash.close()

    # Kick off the GUI
    try:
        app = QApplication(sys.argv)
        icon = resource_path("assets/parsetrail_128px.ico")
        app.setWindowIcon(QIcon(str(icon)))
        configure_ui_hooks()  # bootstrap login ui to AuthManager
        window = ParseTrail()
        window.show()
        sys.exit(app.exec_())
    except Exception:
        logger.exception("An error occurred during application execution")
        sys.exit(1)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
