"""Explicit 2.0 profile and verified-catalog boundary for local source imports."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path

from parsetrail.core.v2_catalog_admission import admit_pilot_definition
from parsetrail.core.v2_data_catalog import CatalogCache, VerifiedCatalog, load_trusted_catalog_keys
from parsetrail.core.v2_profile_store import MAX_SOURCE_BYTES, SavedImport, V2ProfileStore
from parsetrail.core.v2_source_import import ImportCancelled, SourceImportResult, import_catalog_source


class WorkspaceError(ValueError):
    """A 2.0 workspace cannot import this local source."""


def _read_source(path: Path) -> tuple[bytes, str]:
    path = path.expanduser()
    suffix = path.suffix.lower()
    if suffix not in {".csv", ".pdf"}:
        raise WorkspaceError("unsupported_source_type")
    try:
        if path.is_symlink() or not path.is_file():
            raise WorkspaceError("source_unavailable")
        with path.open("rb") as stream:
            before = path.stat()
            if not 0 < before.st_size <= MAX_SOURCE_BYTES:
                raise WorkspaceError("source_size")
            content = stream.read(MAX_SOURCE_BYTES + 1)
            after = path.stat()
    except OSError:
        raise WorkspaceError("source_unavailable") from None
    if (
        not 0 < len(content) <= MAX_SOURCE_BYTES
        or len(content) != before.st_size
        or after.st_size != before.st_size
        or after.st_mtime_ns != before.st_mtime_ns
    ):
        raise WorkspaceError("source_changed_or_too_large")
    return content, suffix


class V2Workspace:
    """Keep profile creation and source selection away from the 1.x runtime."""

    def __init__(
        self,
        profile_path: Path,
        catalog_cache_path: Path,
        *,
        trusted_keys: Mapping[str, bytes] | None = None,
    ):
        self.profile_path = profile_path.expanduser().resolve()
        self.catalog_cache = CatalogCache(
            catalog_cache_path,
            trusted_keys if trusted_keys is not None else load_trusted_catalog_keys(),
            admit_pilot_definition,
        )

    @classmethod
    def create(
        cls,
        profile_path: Path,
        catalog_cache_path: Path,
        *,
        trusted_keys: Mapping[str, bytes] | None = None,
    ) -> V2Workspace:
        workspace = cls(profile_path, catalog_cache_path, trusted_keys=trusted_keys)
        with V2ProfileStore.create(workspace.profile_path):
            pass
        return workspace

    @classmethod
    def open(
        cls,
        profile_path: Path,
        catalog_cache_path: Path,
        *,
        trusted_keys: Mapping[str, bytes] | None = None,
    ) -> V2Workspace:
        workspace = cls(profile_path, catalog_cache_path, trusted_keys=trusted_keys)
        with V2ProfileStore.open(workspace.profile_path, read_only=True):
            pass
        return workspace

    def source_ids(self) -> tuple[str, ...]:
        with V2ProfileStore.open(self.profile_path, read_only=True) as store:
            return store.source_ids()

    def saved_import(self, source_sha256: str) -> SavedImport:
        with V2ProfileStore.open(self.profile_path, read_only=True) as store:
            return store.load_import(source_sha256)

    def install_catalog_release(self, release_dir: Path) -> VerifiedCatalog:
        """Install only a locally selected, authenticated catalog release."""
        return self.catalog_cache.activate_directory(release_dir)

    def import_file(
        self,
        source_path: Path,
        *,
        cancelled: Callable[[], bool] | None = None,
    ) -> SourceImportResult:
        if cancelled is not None and cancelled():
            raise ImportCancelled("cancelled")
        catalog = self.catalog_cache.load_current()
        if catalog is None:
            raise WorkspaceError("verified_catalog_missing")
        source, suffix = _read_source(source_path)
        with V2ProfileStore.open(self.profile_path) as store:
            return import_catalog_source(store, source, catalog=catalog, suffix=suffix, cancelled=cancelled)
