"""Authenticated plugin discovery, installation, and dynamic loading."""

from __future__ import annotations

from loguru import logger
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import QApplication, QProgressDialog

from parsetrail.core.api import ApiClient, api_client
from parsetrail.core.plugin_manager import (
    PluginManager,
    _get_min_client_version,
    _is_plugin_compatible,
)
from parsetrail.core.plugin_manifest import (
    VerifiedPluginRelease,
    require_no_rollback,
    verify_manifest,
)
from parsetrail.core.plugin_store import (
    InstalledPluginRelease,
    install_plugin_release,
)
from parsetrail.core.utils import is_newer_version


def fetch_verified_plugin_release(
    plugin_manager: PluginManager,
    *,
    client: ApiClient = api_client,
) -> VerifiedPluginRelease:
    manifest_bytes, signature = client.fetch_plugin_release_bytes()
    release = verify_manifest(
        manifest_bytes,
        signature,
        plugin_manager.trusted_keys(),
    )
    require_no_rollback(
        release,
        (plugin_manager.active_release.verified if plugin_manager.active_release is not None else None),
    )
    return release


def get_plugin_lists(
    plugin_manager: PluginManager,
) -> tuple[list[dict[str, str]], VerifiedPluginRelease]:
    local_plugins = list(plugin_manager.metadata.values())
    remote_release = fetch_verified_plugin_release(plugin_manager)
    return local_plugins, remote_release


def compare_plugins(
    local_plugins: list[dict[str, str]],
    server_plugins: list[dict[str, str]],
) -> list[dict[str, str]]:
    new_plugins = []
    for server_plugin in server_plugins:
        if not _is_plugin_compatible(server_plugin):
            logger.warning(
                "Plugin {name} requires client >= {min_version}; skipping.",
                name=server_plugin.get("PLUGIN_NAME", "unknown"),
                min_version=_get_min_client_version(server_plugin),
            )
            continue
        plugin_name = server_plugin["PLUGIN_NAME"]
        local_plugin = next(
            (plugin for plugin in local_plugins if plugin["PLUGIN_NAME"] == plugin_name),
            None,
        )
        if local_plugin is None or is_newer_version(
            local_plugin["VERSION"],
            server_plugin["VERSION"],
        ):
            new_plugins.append(server_plugin)
    return new_plugins


def release_update_available(
    plugin_manager: PluginManager,
    remote_release: VerifiedPluginRelease,
) -> bool:
    if plugin_manager.active_release is None:
        return True
    return remote_release.manifest.release_sequence > plugin_manager.active_release.manifest.release_sequence


def sync_plugins(
    local_plugins: list[dict[str, str]],
    remote_release: VerifiedPluginRelease,
    *,
    plugin_manager: PluginManager,
    progress: bool = False,
    parent=None,
    client: ApiClient = api_client,
) -> InstalledPluginRelease:
    """Download and authenticate the complete catalog before activating it."""
    del local_plugins  # Kept in the API because callers already display this state.
    dialog: QProgressDialog | None = None
    if progress:
        dialog = QProgressDialog(
            "Updating Plugins",
            "Cancel",
            0,
            len(remote_release.manifest.artifacts),
            parent,
        )
        dialog.setMinimumWidth(400)
        dialog.setWindowTitle("Updating Plugins")
        dialog.setWindowModality(Qt.WindowModal)
        dialog.setMinimumDuration(100)
        dialog.setValue(0)
        dialog.show()
        QApplication.processEvents()

    def cancelled() -> bool:
        QApplication.processEvents()
        return dialog is not None and dialog.wasCanceled()

    def stream_plugin_bytes(plugin_name: str):
        if dialog is not None:
            dialog.setLabelText(f"Downloading and verifying {plugin_name}")
        for chunk, _, _ in client.stream_plugin(plugin_name):
            yield chunk
        if dialog is not None:
            dialog.setValue(dialog.value() + 1)
            QApplication.processEvents()

    try:
        installed = install_plugin_release(
            plugin_manager.plugin_dir,
            remote_release,
            stream_plugin_bytes,
            current=plugin_manager.active_release,
            cancelled=cancelled,
        )
        logger.success(
            "Installed signed plugin release {sequence} with {count} plugins.",
            sequence=remote_release.manifest.release_sequence,
            count=len(remote_release.manifest.artifacts),
        )
        return installed
    finally:
        if dialog is not None:
            dialog.close()


def check_for_plugin_updates(
    plugin_manager: PluginManager,
    parent=None,
) -> bool:
    local_plugins, remote_release = get_plugin_lists(plugin_manager)
    server_plugins = remote_release.legacy_metadata()
    new_plugins = compare_plugins(local_plugins, server_plugins)
    if new_plugins or release_update_available(plugin_manager, remote_release):
        sync_plugins(
            local_plugins,
            remote_release,
            plugin_manager=plugin_manager,
            progress=True,
            parent=parent,
        )
        plugin_manager.load_plugins()
        return True
    return False


class PluginUpdateThread(QThread):
    """Check for a newer authenticated plugin catalog without blocking the UI."""

    update_available = Signal(object, object)
    update_complete = Signal(bool, str)

    def __init__(self, plugin_manager: PluginManager):
        super().__init__()
        self.plugin_manager = plugin_manager

    def run(self) -> None:
        try:
            local_plugins, remote_release = get_plugin_lists(self.plugin_manager)
            new_plugins = compare_plugins(
                local_plugins,
                remote_release.legacy_metadata(),
            )
            if new_plugins or release_update_available(
                self.plugin_manager,
                remote_release,
            ):
                self.update_available.emit(local_plugins, remote_release)
            else:
                self.update_complete.emit(True, "Plugins are up to date.")
        except Exception as exc:
            self.update_complete.emit(False, f"Plugin update failed: {exc}")
