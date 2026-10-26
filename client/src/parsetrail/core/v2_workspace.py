"""Explicit 2.0 profile and verified-catalog boundary for local source imports."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from parsetrail.core.source_evidence import StatementPayload
from parsetrail.core.v2_account_matching import LedgerAccountCandidate, match_verified_source_account
from parsetrail.core.v2_catalog_admission import admit_pilot_definition
from parsetrail.core.v2_data_catalog import CatalogCache, VerifiedCatalog, load_trusted_catalog_keys
from parsetrail.core.v2_preferences import V2Preferences, default_preferences_path, load_preferences, save_preferences
from parsetrail.core.v2_profile_store import (
    MAX_SOURCE_BYTES,
    AccountBinding,
    ProfileFormatError,
    SavedImport,
    V2ProfileStore,
)
from parsetrail.core.v2_source_import import (
    CatalogImportError,
    ImportCancelled,
    SourceImportResult,
    import_catalog_source,
)
from parsetrail.core.v2_source_pipeline import SourcePipelineError


class WorkspaceError(ValueError):
    """A 2.0 workspace cannot import this local source."""


MAX_BATCH_FILES = 2_000


@dataclass(frozen=True)
class BatchFileResult:
    path: Path
    status: Literal["imported", "already_imported", "failed", "cancelled", "not_attempted"]
    source_sha256: str | None = None
    error_code: str | None = None


@dataclass(frozen=True)
class BatchImportResult:
    files: tuple[BatchFileResult, ...]
    cancelled: bool


def folder_source_files(folder: Path) -> tuple[Path, ...]:
    """List only immediate CSV/PDF children of a deliberately selected folder."""
    if folder.is_symlink() or not folder.is_dir():
        raise WorkspaceError("source_folder_unavailable")
    try:
        paths = tuple(
            sorted(
                path
                for path in folder.iterdir()
                if path.suffix.lower() in {".csv", ".pdf"} and path.is_file() and not path.is_symlink()
            )
        )
    except OSError:
        raise WorkspaceError("source_folder_unavailable") from None
    if not paths:
        raise WorkspaceError("source_folder_has_no_supported_files")
    if len(paths) > MAX_BATCH_FILES:
        raise WorkspaceError("source_batch_limit")
    return paths


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
        preferences_path: Path | None = None,
    ):
        self.profile_path = profile_path.expanduser().resolve()
        self.preferences_path = preferences_path or default_preferences_path()
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
        preferences_path: Path | None = None,
    ) -> V2Workspace:
        workspace = cls(profile_path, catalog_cache_path, trusted_keys=trusted_keys, preferences_path=preferences_path)
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
        preferences_path: Path | None = None,
    ) -> V2Workspace:
        workspace = cls(profile_path, catalog_cache_path, trusted_keys=trusted_keys, preferences_path=preferences_path)
        with V2ProfileStore.open(workspace.profile_path, read_only=True):
            pass
        return workspace

    def source_ids(self) -> tuple[str, ...]:
        with V2ProfileStore.open(self.profile_path, read_only=True) as store:
            return store.source_ids()

    def saved_import(self, source_sha256: str) -> SavedImport:
        with V2ProfileStore.open(self.profile_path, read_only=True) as store:
            return store.load_import(source_sha256)

    def recover_source_original(self, source_sha256: str, destination: Path) -> Path:
        """Save verified original bytes from this profile at a new destination."""
        from parsetrail.core.v2_source_recovery import recover_source_original

        return recover_source_original(self.profile_path, source_sha256, destination)

    def overlapping_statement_sources(self, source_sha256: str) -> tuple[str, ...]:
        with V2ProfileStore.open(self.profile_path, read_only=True) as store:
            return store.overlapping_statement_sources(source_sha256)

    def preferences(self) -> V2Preferences:
        return load_preferences(self.preferences_path)

    def verify_local_configuration(self) -> None:
        """Validate separate preferences/catalog reads before activating a workspace."""
        self.preferences()
        self.catalog_cache.load_current()

    def set_allow_abbreviated_account_matching(self, enabled: bool) -> None:
        if type(enabled) is not bool:
            raise ValueError("invalid_abbreviated_matching_preference")
        save_preferences(self.preferences_path, replace(self.preferences(), allow_abbreviated_account_matching=enabled))

    def set_allow_assumed_posting_dates(self, enabled: bool) -> None:
        if type(enabled) is not bool:
            raise ValueError("invalid_assumed_posting_date_preference")
        save_preferences(self.preferences_path, replace(self.preferences(), allow_assumed_posting_dates=enabled))

    def account_bindings(self, source_sha256: str) -> tuple[AccountBinding, ...]:
        """Resolve automatic suggestions at read time; explicit decisions win."""
        catalog = self.catalog_cache.load_current()
        preferences = self.preferences()
        with V2ProfileStore.open(self.profile_path, read_only=True) as store:
            saved = store.load_import(source_sha256)
            bindings = store.account_bindings(source_sha256)
            accounts = store.financial_accounts()
        candidates = tuple(
            LedgerAccountCandidate(account.id, account.institution_key, account.kind, account.full_account_number)
            for account in accounts
        )
        payload = saved.evidence.payload
        rows = (
            tuple(row for account in payload.accounts for row in account.rows)
            if isinstance(payload, StatementPayload)
            else payload.rows
        )
        matches = {}
        resolved = []
        for row, binding in zip(rows, bindings, strict=True):
            if binding.ledger_account_id is not None or row.source_account is None:
                resolved.append(binding)
                continue
            key = (row.source_account, row.source_account_form)
            if key not in matches:
                matches[key] = match_verified_source_account(
                    saved.evidence,
                    row.source_account,
                    row.source_account_form,
                    catalog=catalog,
                    candidates=candidates,
                    preferences=preferences,
                )
            match = matches[key]
            resolved.append(
                AccountBinding(row.row_id, match.ledger_account_id, "automatic")
                if match.status == "automatic"
                else binding
            )
        return tuple(resolved)

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

    def import_files(
        self,
        paths: tuple[Path, ...],
        *,
        cancelled: Callable[[], bool] | None = None,
        progress: Callable[[int, BatchFileResult], None] | None = None,
    ) -> BatchImportResult:
        """Continue after per-file failures; cancellation keeps completed imports."""
        if not paths or len(paths) > MAX_BATCH_FILES or any(not isinstance(path, Path) for path in paths):
            raise WorkspaceError("source_batch_selection_invalid")
        if self.catalog_cache.load_current() is None:
            raise WorkspaceError("verified_catalog_missing")
        files = []
        was_cancelled = False
        for index, path in enumerate(paths):
            if cancelled is not None and cancelled():
                was_cancelled = True
                files.extend(BatchFileResult(remaining, "not_attempted") for remaining in paths[index:])
                break
            try:
                imported = self.import_file(path, cancelled=cancelled)
                result = BatchFileResult(path, imported.status, imported.source_sha256)
            except ImportCancelled:
                result = BatchFileResult(path, "cancelled")
                was_cancelled = True
            except Exception as exc:
                code = (
                    str(exc)
                    if isinstance(exc, (WorkspaceError, CatalogImportError, ProfileFormatError, SourcePipelineError))
                    else type(exc).__name__
                )
                result = BatchFileResult(path, "failed", error_code=code)
            files.append(result)
            if progress is not None:
                progress(index + 1, result)
            if was_cancelled:
                files.extend(BatchFileResult(remaining, "not_attempted") for remaining in paths[index + 1 :])
                break
        return BatchImportResult(tuple(files), was_cancelled)
