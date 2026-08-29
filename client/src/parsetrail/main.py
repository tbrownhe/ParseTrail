import os
import signal
import sys
from contextlib import suppress
from platform import system

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

RUNTIME_SMOKE_TEST_ARGUMENT = "--runtime-smoke-test"

# Set Qt environment variables
os.environ.setdefault("QT_API", "PySide6")  # Qt bindings
os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"  # Enable HiDPI scaling

# Platform-specific environment configurations
system_name = system()
if system_name == "Windows":
    os.environ["QT_QPA_PLATFORM"] = "windows"


def handle_signal(_signal, _frame):
    from parsetrail.core.logging import logger

    logger.info("Application interrupted. Exiting...")
    sys.exit(0)


def run_runtime_smoke_test() -> int:
    """Import modules required during frozen application bootstrap."""
    for module_name in (
        "_socket",
        "socket",
        "multiprocessing",
        "parsetrail.core.credentials",
    ):
        __import__(module_name)
    if system() in {"Windows", "Darwin"}:
        from parsetrail.core.credentials import credential_store

        if not credential_store.available:
            raise RuntimeError("No native OS credential backend is bundled")
    return 0


# Client entry point
def main() -> int:
    if RUNTIME_SMOKE_TEST_ARGUMENT in sys.argv:
        return run_runtime_smoke_test()

    # Imports that depend on settings
    from parsetrail.core.logging import logger
    from parsetrail.core.utils import resource_path
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
        sys.exit(app.exec())
    except Exception:
        logger.exception("An error occurred during application execution")
        sys.exit(1)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
