from collections.abc import Callable
from pathlib import Path
from threading import Event

from loguru import logger
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import QApplication, QMessageBox, QProgressDialog

from parsetrail.core.api import api_client
from parsetrail.core.client_manifest import ClientInstallerArtifact
from parsetrail.core.client_store import (
    ClientDownloadCancelled,
    download_installer,
    fetch_latest_installer,
)
from parsetrail.core.settings import settings
from parsetrail.core.utils import is_newer_version, open_file_in_os
from parsetrail.version import __version__ as current_version


def get_latest_installer() -> ClientInstallerArtifact | None:
    """Fetch, authenticate, and select the latest installer for this platform."""
    return fetch_latest_installer(api_client, settings.platform)


def download_client_installer(
    installer: ClientInstallerArtifact,
    *,
    cancelled: Callable[[], bool] | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> Path:
    """Download an installer into authenticated atomic storage."""
    try:
        installer_path = download_installer(
            settings.download_dir,
            installer,
            api_client,
            cancelled=cancelled,
            progress=progress,
        )
        logger.success(f"Downloaded and authenticated installer to {installer_path}")
        return installer_path
    except ClientDownloadCancelled:
        raise
    except Exception as e:
        logger.error(f"Failed to download installer: {e}")
        raise RuntimeError(f"Failed to authenticate installer: {e}") from e


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


class InstallerDownloadThread(QThread):
    """Download and authenticate an installer without blocking Qt."""

    progress_changed = Signal(int, int)
    downloaded = Signal(object)
    failed = Signal(str)
    download_cancelled = Signal()

    def __init__(self, installer: ClientInstallerArtifact, parent=None) -> None:
        super().__init__(parent)
        self.installer = installer
        self._cancel_event = Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        try:
            installer_path = download_client_installer(
                self.installer,
                cancelled=self._cancel_event.is_set,
                progress=self.progress_changed.emit,
            )
        except ClientDownloadCancelled:
            self.download_cancelled.emit()
        except Exception as exc:
            self.failed.emit(str(exc))
        else:
            self.downloaded.emit(installer_path)


def install_client(installer: ClientInstallerArtifact, parent=None) -> InstallerDownloadThread | None:
    reply = QMessageBox.question(
        parent,
        "Client Update Available",
        (
            f"A new version of the client is available:\n\n"
            f"Current Version: {current_version}\n"
            f"Latest Version: {installer.version}\n\n"
            f"Do you want to download and install it now?"
        ),
        QMessageBox.Yes | QMessageBox.No,
    )

    if reply != QMessageBox.Yes:
        return None

    progress = QProgressDialog("Downloading and authenticating update...", "Cancel", 0, installer.size, parent)
    progress.setWindowTitle("Update in Progress")
    progress.setWindowModality(Qt.WindowModal)
    progress.setMinimumDuration(0)
    progress.setFixedWidth(400)
    progress.setAutoClose(False)
    progress.setAutoReset(False)

    thread = InstallerDownloadThread(installer, parent=progress)
    progress._download_thread = thread
    progress.canceled.connect(thread.cancel)
    thread.progress_changed.connect(lambda downloaded, total: progress.setRange(0, total))
    thread.progress_changed.connect(lambda downloaded, total: progress.setValue(downloaded))

    def handle_downloaded(installer_path: Path) -> None:
        progress.setValue(progress.maximum())
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

    def handle_failure(message: str) -> None:
        progress.close()
        QMessageBox.critical(
            parent,
            "Update Failed",
            f"An error occurred while preparing the update:\n{message}",
        )

    def handle_cancelled() -> None:
        progress.close()
        QMessageBox.information(parent, "Update Canceled", "The installer download was canceled.")

    thread.downloaded.connect(handle_downloaded)
    thread.failed.connect(handle_failure)
    thread.download_cancelled.connect(handle_cancelled)
    thread.finished.connect(thread.deleteLater)
    thread.start()
    progress.show()
    return thread


class ClientUpdateThread(QThread):
    """Checks for plugins in a separate thread"""

    # Success, latest_installer or None, message
    update_available = Signal(bool, object, str)

    def __init__(self):
        super().__init__()

    def run(self):
        try:
            # Get the list of installers for the user's platform
            latest_installer = get_latest_installer()

            # Return if there are no installers available
            if latest_installer is None:
                self.update_available.emit(False, None, "No client installers available on server")
                return

            if is_newer_version(current_version, latest_installer.version):
                self.update_available.emit(True, latest_installer, "Update Available")
            else:
                self.update_available.emit(True, None, "Client up to date")
        except Exception as e:
            self.update_available.emit(False, None, f"Client update failed: {e}")
