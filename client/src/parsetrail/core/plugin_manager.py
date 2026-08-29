"""Headless plugin trust, compatibility, and loading state."""

from __future__ import annotations

from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from loguru import logger

from parsetrail.core.plugin_loader import load_plugin
from parsetrail.core.plugin_manifest import PluginTrustError, load_trusted_plugin_keys
from parsetrail.core.plugin_store import InstalledPluginRelease, read_active_release
from parsetrail.core.settings import settings
from parsetrail.core.utils import is_version_compatible
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
