"""Authenticated plugin discovery, installation, and dynamic loading."""

from __future__ import annotations

from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from loguru import logger
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import QApplication, QProgressDialog

from parsetrail.core.api import ApiClient, api_client
from parsetrail.core.plugin_loader import load_plugin
from parsetrail.core.plugin_manifest import (
    PluginTrustError,
    VerifiedPluginRelease,
    load_trusted_plugin_keys,
    require_no_rollback,
    verify_manifest,
)
from parsetrail.core.plugin_store import (
    InstalledPluginRelease,
    install_plugin_release,
    read_active_release,
)
from parsetrail.core.settings import settings
from parsetrail.core.utils import is_newer_version, is_version_compatible
from parsetrail.version import __version__ as current_version


def _get_min_client_version(metadata: dict[str, str]) -> str:
    min_version = metadata.get("MIN_CLIENT_VERSION")
    return min_version.strip() if isinstance(min_version, str) and min_version.strip() else "0.0.0"


def _is_plugin_compatible(metadata: dict[str, str]) -> bool:
    return is_version_compatible(
        current_version,
        _get_min_client_version(metadata),
    )


def _validate_loaded_metadata(
    loaded_metadata: dict[str, str],
    signed_metadata: dict[str, str],
) -> None:
    authenticated_fields = {
        "FILENAME",
        "PLUGIN_NAME",
        "VERSION",
        "MIN_CLIENT_VERSION",
        "COMPANY",
        "SUFFIX",
        "STATEMENT_TYPE",
    }
    mismatches = sorted(
        field for field in authenticated_fields if loaded_metadata.get(field) != signed_metadata.get(field)
    )
    if mismatches:
        raise ValueError("Plugin metadata does not match its signed manifest fields: " + ", ".join(mismatches))


class PluginManager:
    def __init__(
        self,
        *,
        plugin_dir: Path | None = None,
        allow_unsigned: bool = False,
        trusted_keys: dict[str, Ed25519PublicKey] | None = None,
    ):
        self.plugin_dir = plugin_dir or settings.plugin_dir
        self.allow_unsigned = allow_unsigned
        self._trusted_keys = trusted_keys
        self.plugins: dict[str, type] = {}
        self.metadata: dict[str, dict[str, str]] = {}
        self.suffixes: list[str] = []
        self.active_release: InstalledPluginRelease | None = None

    def trusted_keys(self) -> dict[str, Ed25519PublicKey]:
        if self._trusted_keys is None:
            self._trusted_keys = load_trusted_plugin_keys()
        return self._trusted_keys

    def _load_one(
        self,
        plugin_file: Path,
        *,
        signed_metadata: dict[str, str] | None = None,
    ) -> None:
        plugin_id, parser_class, metadata = load_plugin(plugin_file)
        if signed_metadata is not None:
            _validate_loaded_metadata(metadata, signed_metadata)
        if not _is_plugin_compatible(metadata):
            logger.warning(
                "Skipping plugin {name}: requires client >= {min_version} (current {current}).",
                name=metadata.get("PLUGIN_NAME", plugin_id),
                min_version=_get_min_client_version(metadata),
                current=current_version,
            )
            return
        self.plugins[plugin_id] = parser_class
        self.metadata[plugin_id] = metadata

    def load_plugins(self) -> None:
        """Load local-development plugins or one fully authenticated release."""
        self.plugins = {}
        self.metadata = {}
        self.active_release = None

        if self.allow_unsigned:
            logger.warning("Unsigned plugin loading is enabled for the local development tool.")
            for plugin_file in self.plugin_dir.glob("*.pyc"):
                try:
                    self._load_one(plugin_file)
                except Exception as exc:
                    logger.error(f"Failed to load {plugin_file}: {exc}")
        else:
            try:
                self.active_release = read_active_release(
                    self.plugin_dir,
                    self.trusted_keys(),
                )
            except PluginTrustError as exc:
                logger.error(f"Refusing untrusted plugin release: {exc}")
            if self.active_release is None:
                if any(self.plugin_dir.glob("*.pyc")):
                    logger.warning("Ignoring unsigned legacy plugins. Install the signed plugin catalog to use them.")
            else:
                for artifact in self.active_release.manifest.artifacts:
                    signed_metadata = artifact.as_legacy_metadata()
                    if not _is_plugin_compatible(signed_metadata):
                        logger.warning(
                            "Skipping plugin {name}: requires client >= {min_version} (current {current}).",
                            name=artifact.plugin_name,
                            min_version=artifact.minimum_client_version,
                            current=current_version,
                        )
                        continue
                    plugin_file = self.active_release.release_dir / artifact.filename
                    try:
                        self._load_one(
                            plugin_file,
                            signed_metadata=signed_metadata,
                        )
                    except Exception as exc:
                        logger.error(f"Failed to load {plugin_file}: {exc}")

        if self.plugins:
            logger.success(f"Loaded {len(self.plugins)} plugins")
        self.suffixes = sorted({plugin["SUFFIX"] for plugin in self.metadata.values()})

    def get_parser(self, plugin_id: str):
        parser_class = self.plugins.get(plugin_id)
        if not parser_class:
            raise ImportError(f"Plugin '{plugin_id}' not loaded.")
        return parser_class


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
