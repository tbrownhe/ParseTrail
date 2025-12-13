from pathlib import Path

from loguru import logger
from packaging import version
from parsetrail.core.api import api_client
from parsetrail.core.settings import settings
from parsetrail.core.utils import is_newer_version, open_file_in_os
from parsetrail.version import __version__ as current_version
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtWidgets import QApplication, QMessageBox, QProgressDialog


def get_latest_installer() -> dict | None:
    """
    Fetch the list of available client installers from the server.

    Returns:
        list[dict]: A list of client installer metadata.
    """
    installers = api_client.list_installers()
    platform_installers = [i for i in installers if i["platform"] == settings.platform]
    if not platform_installers:
        return None
    return max(platform_installers, key=lambda i: version.parse(i["version"]))


def download_client_installer(installer: dict, progress: QProgressDialog | None = None) -> Path:
    """
    Download the specified client installer.

    Args:
        installer_metadata (dict): Metadata of the installer to download.
    """
    dpath = settings.download_dir / installer["file_name"]
    dpath.parent.mkdir(parents=True, exist_ok=True)
    try:
        with dpath.open("wb") as f:
            first_loop = True
            for chunk, downloaded, total in api_client.stream_installer(installer["platform"], installer["version"]):
                f.write(chunk)
                if progress:
                    if progress.wasCanceled():
                        break
                    if first_loop:
                        progress.setMaximum(total)
                    progress.setValue(downloaded)
                first_loop = False
            logger.success(f"Downloaded installer to {dpath}")
            return dpath
    except Exception as e:
        logger.error(f"Failed to download installer: {e}")
        raise RuntimeError("Failed to download installer") from e


def quit_and_update(installer_path: Path):
    """
    Launch the installer and cleanly quit the client app.

    Args:
        installer_path (Path): Path to the installer.
    """
    try:
        open_file_in_os(installer_path)
        logger.info("Installer launched. Closing the application.")
        QApplication.quit()  # Ensure this is called in the main thread
    except Exception as e:
        logger.error(f"Failed to launch installer: {e}")


def install_client(installer, parent=None):
    reply = QMessageBox.question(
        parent,
        "Client Update Available",
        (
            f"A new version of the client is available:\n\n"
            f"Current Version: {current_version}\n"
            f"Latest Version: {installer['version']}\n\n"
            f"Do you want to download and install it now?"
        ),
        QMessageBox.Yes | QMessageBox.No,
    )

    if reply != QMessageBox.Yes:
        return

    try:
        progress = QProgressDialog("Downloading update...", "Cancel", 0, 100, parent)
        progress.setWindowTitle("Update in Progress")
        progress.setWindowModality(Qt.WindowModal)
        progress.setMinimumDuration(0)
        progress.setFixedWidth(400)
        installer_path = download_client_installer(installer, progress=progress)
        progress.close()

        response = QMessageBox.question(
            parent,
            "Update Ready",
            "The installer is ready to launch. The application will close to proceed. Continue?",
            QMessageBox.Yes | QMessageBox.No,
        )
        if response == QMessageBox.Yes:
            quit_and_update(installer_path)
        else:
            QMessageBox.information(
                parent,
                "Update Canceled",
                f"The update process has been canceled.\nInstaller: {installer_path}",
            )
    except Exception as e:
        QMessageBox.critical(
            parent,
            "Update Failed",
            f"An error occurred while preparing the update:\n{e}",
        )


def check_for_client_updates(parent=None) -> bool:
    """
    Check for client updates and prompt the user to update if needed.

    Args:
        manual (bool): Whether this check was triggered manually.
        parent: The parent widget for dialogs.

    Returns:
        bool: True if an update was downloaded and launched, False otherwise.
    """
    try:
        latest_installer = get_latest_installer()
        if latest_installer is None:
            if parent:
                QMessageBox.information(
                    parent,
                    "No Updates Found",
                    f"No installers found for platform: {settings.platform}.",
                )
            return False

        if is_newer_version(current_version, latest_installer["version"]):
            install_client(latest_installer, parent)
            return True  # App may close before this is called

        if parent:
            QMessageBox.information(
                parent,
                "Client Up To Date",
                "You are already using the latest version.",
            )
        return False
    except Exception as e:
        logger.error(f"Error checking for updates: {e}")
        if parent:
            QMessageBox.critical(parent, "Error", f"An error occurred while checking for updates:\n{e}")
        return False


class ClientUpdateThread(QThread):
    """Checks for plugins in a separate thread"""

    # Success, latest_installer or {}, message
    update_available = pyqtSignal(bool, dict, str)

    def __init__(self):
        super().__init__()

    def run(self):
        try:
            # Get the list of installers for the user's platform
            latest_installer = get_latest_installer()

            # Return if there are no installers available
            if latest_installer is None:
                self.update_available.emit(False, {}, "No client installers available on server")
                return

            if is_newer_version(current_version, latest_installer["version"]):
                self.update_available.emit(True, latest_installer, "Update Available")
            else:
                self.update_available.emit(True, {}, "Client up to date")
        except Exception as e:
            self.update_available.emit(False, {}, f"Client update failed: {e}")
