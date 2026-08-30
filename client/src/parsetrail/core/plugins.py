"""Authenticated plugin discovery, installation, and dynamic loading."""

from __future__ import annotations

from collections.abc import Callable
from threading import Event

from loguru import logger
from PySide6.QtCore import QThread, Signal

from parsetrail.core.api import ApiClient, api_client
from parsetrail.core.auth import AuthError
from parsetrail.core.plugin_manager import (
    PluginManager,
    _get_min_client_version,
    _is_plugin_compatible,
)
from parsetrail.core.plugin_manifest import (
    PluginDownloadCancelled,
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
    progress: Callable[[int, int, str], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    client: ApiClient = api_client,
) -> InstalledPluginRelease:
    """Download and authenticate the complete catalog before activating it."""
    del local_plugins  # Kept in the API because callers already display this state.
    report_progress = progress or (lambda _completed, _total, _label: None)
    cancellation_requested = cancelled or (lambda: False)
    total = len(remote_release.manifest.artifacts)
    completed = 0

    def stream_plugin_bytes(plugin_name: str):
        nonlocal completed
        report_progress(completed, total, f"Downloading and verifying {plugin_name}")
        for chunk, _, _ in client.stream_plugin(plugin_name):
            yield chunk
        completed += 1
        report_progress(completed, total, f"Downloaded {plugin_name}")

    installed = install_plugin_release(
        plugin_manager.plugin_dir,
        remote_release,
        stream_plugin_bytes,
        current=plugin_manager.active_release,
        cancelled=cancellation_requested,
    )
    report_progress(total, total, "Authenticated plugin catalog")
    logger.success(
        "Installed signed plugin release {sequence} with {count} plugins.",
        sequence=remote_release.manifest.release_sequence,
        count=len(remote_release.manifest.artifacts),
    )
    return installed


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


class PluginSyncThread(QThread):
    """Authenticate and atomically install a plugin catalog off the UI thread."""

    progress_changed = Signal(int, int, str)
    sync_completed = Signal(object)
    authentication_required = Signal(str)
    sync_failed = Signal(str)
    sync_cancelled = Signal()

    def __init__(
        self,
        local_plugins: list[dict[str, str]],
        remote_release: VerifiedPluginRelease,
        *,
        plugin_manager: PluginManager,
        credentials: tuple[str, str] | None = None,
        client: ApiClient = api_client,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.local_plugins = local_plugins
        self.remote_release = remote_release
        self.plugin_manager = plugin_manager
        self.credentials = credentials
        self.client = client
        self._cancel_event = Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        try:
            if self.credentials is not None:
                email, password = self.credentials
                self.credentials = None
                self.client.auth.login(email, password)
            installed = sync_plugins(
                self.local_plugins,
                self.remote_release,
                plugin_manager=self.plugin_manager,
                progress=self.progress_changed.emit,
                cancelled=self._cancel_event.is_set,
                client=self.client,
            )
        except PluginDownloadCancelled:
            self.sync_cancelled.emit()
        except AuthError as exc:
            self.authentication_required.emit(str(exc))
        except Exception as exc:
            self.sync_failed.emit(str(exc))
        else:
            self.sync_completed.emit(installed)
