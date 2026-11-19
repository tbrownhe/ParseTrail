"""Explicit 2.0 profile and verified-catalog boundary for local source imports."""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from parsetrail.core.source_evidence import StatementPayload
from parsetrail.core.v2_account_matching import LedgerAccountCandidate, match_verified_source_account
from parsetrail.core.v2_catalog_admission import admit_pilot_definition
from parsetrail.core.v2_data_catalog import CatalogCache, VerifiedCatalog, load_trusted_catalog_keys
from parsetrail.core.v2_format_recognition import FormatRecognition, FormatSelection
from parsetrail.core.v2_import_accounts import (
    ImportAccountPlan,
    ImportAccountReview,
    automatic_import_plan,
    commit_import_accounts,
)
from parsetrail.core.v2_institutions import Institution, catalog_institutions, merge_institutions
from parsetrail.core.v2_loan_automation import LoanAutomationResult, post_imported_loan_payment
from parsetrail.core.v2_preferences import V2Preferences, default_preferences_path, load_preferences, save_preferences
from parsetrail.core.v2_prepared_import import PreparedImportSession
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
    import_prepared_catalog_source,
)
from parsetrail.core.v2_source_pipeline import SourcePipelineError
from parsetrail.core.v2_statement_summary_review import SUMMARY_VALUE_PARSERS
from parsetrail.core.v2_statement_value_automation import (
    StatementValueAutomationResult,
    record_imported_statement_value,
)


class WorkspaceError(ValueError):
    """A 2.0 workspace cannot import this local source."""


class ImportSkipped(WorkspaceError):
    """An explicit preview decision left this file unimported."""


FormatReview = Callable[[Path, FormatRecognition], FormatSelection | None]
ImportReview = Callable[[Path, ImportAccountReview], ImportAccountPlan | None]


@dataclass(frozen=True)
class CatalogInstallResult:
    """Activation and profile retention have separate, truthful outcomes."""

    catalog: VerifiedCatalog
    institution_error_code: str | None = None


MAX_BATCH_FILES = 2_000


@dataclass(frozen=True)
class BatchFileResult:
    path: Path
    status: Literal["imported", "already_imported", "failed", "skipped", "cancelled", "not_attempted"]
    source_sha256: str | None = None
    error_code: str | None = None
    loan_automation: LoanAutomationResult | None = None
    statement_value_automation: StatementValueAutomationResult | None = None


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

    def set_import_preview_mode(self, mode: str) -> None:
        if type(mode) is not str or mode not in {"always", "when_needed"}:
            raise ValueError("invalid_import_preview_preference")
        save_preferences(self.preferences_path, replace(self.preferences(), import_preview_mode=mode))

    def set_auto_post_loan_payments(self, enabled: bool) -> None:
        if type(enabled) is not bool:
            raise ValueError("invalid_loan_automation_preference")
        save_preferences(self.preferences_path, replace(self.preferences(), auto_post_loan_payments=enabled))

    def set_auto_record_statement_values(self, enabled: bool) -> None:
        if type(enabled) is not bool:
            raise ValueError("invalid_statement_value_automation_preference")
        save_preferences(self.preferences_path, replace(self.preferences(), auto_record_statement_values=enabled))

    def account_bindings(self, source_sha256: str) -> tuple[AccountBinding, ...]:
        """Resolve automatic suggestions at read time; explicit decisions win."""
        catalog = self.catalog_cache.load_current()
        preferences = self.preferences()
        with V2ProfileStore.open(self.profile_path, read_only=True) as store:
            saved = store.load_import(source_sha256)
            bindings = store.account_bindings(source_sha256)
            accounts = store.active_financial_accounts()
            candidates = tuple(
                LedgerAccountCandidate(account.id, account.institution_key, account.kind, number)
                for account in accounts
                for number in store.account_numbers(account.id) or (None,)
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

    def install_catalog_release(self, release_dir: Path) -> CatalogInstallResult:
        """Install only a locally selected, authenticated catalog release."""
        candidate = self.catalog_cache.inspect_directory(release_dir)
        # Refuse predictable identity conflicts before activating formats. The
        # later profile write and filesystem pointer are separate resources:
        # report retention failure honestly instead of claiming install failed.
        with V2ProfileStore.open(self.profile_path, read_only=True) as store:
            registered = store.institutions()
        try:
            merge_institutions(registered, catalog_institutions(candidate))
        except ValueError as exc:
            raise ProfileFormatError(str(exc)) from None
        catalog = self.catalog_cache.activate(candidate.snapshot, candidate.signature)
        try:
            self.sync_catalog_institutions(catalog)
        except (ProfileFormatError, sqlite3.Error, OSError) as exc:
            return CatalogInstallResult(catalog, str(exc))
        return CatalogInstallResult(catalog)

    def institutions(self) -> tuple[Institution, ...]:
        """Offer managed names without writing merely to populate a selector."""
        with V2ProfileStore.open(self.profile_path, read_only=True) as store:
            registered = store.institutions()
        catalog = self.catalog_cache.load_current()
        try:
            return merge_institutions(registered, catalog_institutions(catalog) if catalog is not None else ())
        except ValueError as exc:
            raise ProfileFormatError(str(exc)) from None

    def sync_catalog_institutions(self, catalog: VerifiedCatalog | None = None) -> tuple[Institution, ...]:
        """Explicitly retain verified catalog identities independently of formats."""
        selected = catalog if catalog is not None else self.catalog_cache.load_current()
        if selected is None:
            return ()
        with V2ProfileStore.open(self.profile_path) as store:
            return store.register_catalog_institutions(selected)

    def import_file(
        self,
        source_path: Path,
        *,
        cancelled: Callable[[], bool] | None = None,
        review_format: FormatReview | None = None,
        review_import: ImportReview | None = None,
    ) -> SourceImportResult:
        from parsetrail.core.v2_import_accounts import _profile_identity

        preferences = self.preferences()
        profile_path = self.profile_path
        profile_identity = None
        established_accounts = frozenset()
        if preferences.auto_post_loan_payments or preferences.auto_record_statement_values:
            with V2ProfileStore.open(profile_path, read_only=True) as store:
                profile_identity = _profile_identity(store)
                if preferences.auto_post_loan_payments:
                    established_accounts = frozenset(account.id for account in store.financial_accounts())
        result = self._import_file_evidence(
            source_path, cancelled=cancelled, review_format=review_format, review_import=review_import
        )
        if result.status != "imported":
            return result
        from parsetrail.core.v2_loan_payments import LOAN_PARSERS

        if preferences.auto_post_loan_payments and result.evidence.parser_id in LOAN_PARSERS:

            def authorize_loan():
                if cancelled is not None and cancelled():
                    raise ProfileFormatError("loan_auto_cancelled")
                current = self.preferences()
                if (
                    self.profile_path != profile_path
                    or not current.auto_post_loan_payments
                    or current.allow_assumed_posting_dates != preferences.allow_assumed_posting_dates
                ):
                    raise ProfileFormatError("loan_auto_changed")

            try:
                with V2ProfileStore.open(profile_path) as store:
                    automation = post_imported_loan_payment(
                        store,
                        result.source_sha256,
                        preferences=preferences,
                        established_accounts=established_accounts,
                        expected_profile=profile_identity,
                        authorize=authorize_loan,
                    )
            except Exception as exc:
                code = str(exc) if isinstance(exc, ProfileFormatError) else "loan_auto_failed"
                automation = LoanAutomationResult(
                    "cancelled" if code == "loan_auto_cancelled" else "needs_review", reason_code=code
                )
            result = replace(result, loan_automation=automation)

        if preferences.auto_record_statement_values and result.evidence.parser_id in SUMMARY_VALUE_PARSERS:

            def authorize_statement_value():
                if cancelled is not None and cancelled():
                    raise ProfileFormatError("statement_value_auto_cancelled")
                if self.profile_path != profile_path or not self.preferences().auto_record_statement_values:
                    raise ProfileFormatError("statement_value_auto_changed")

            try:
                with V2ProfileStore.open(profile_path) as store:
                    value_automation = record_imported_statement_value(
                        store,
                        result.source_sha256,
                        preferences=preferences,
                        expected_profile=profile_identity,
                        authorize=authorize_statement_value,
                    )
            except Exception as exc:
                code = str(exc) if isinstance(exc, ProfileFormatError) else "statement_value_auto_failed"
                value_automation = StatementValueAutomationResult(
                    "cancelled" if code == "statement_value_auto_cancelled" else "needs_review", reason_code=code
                )
            result = replace(result, statement_value_automation=value_automation)
        return result

    def _import_file_evidence(
        self,
        source_path: Path,
        *,
        cancelled: Callable[[], bool] | None = None,
        review_format: FormatReview | None = None,
        review_import: ImportReview | None = None,
    ) -> SourceImportResult:
        if review_format is not None and review_import is not None:
            raise WorkspaceError("import_review_conflict")
        if cancelled is not None and cancelled():
            raise ImportCancelled("cancelled")
        if review_import is not None:
            return self._import_with_accounts(source_path, review_import, cancelled=cancelled)
        catalog = self.catalog_cache.load_current()
        if catalog is None:
            raise WorkspaceError("verified_catalog_missing")
        source, suffix = _read_source(source_path)
        if review_format is not None and suffix == ".csv":
            # An exact retry needs no new interpretation or preview. This read
            # also verifies the existing profile before any review is requested.
            with V2ProfileStore.open(self.profile_path, read_only=True) as store:
                if store.source_imported(source):
                    source_hash = hashlib.sha256(source).hexdigest()
                    saved = store.load_import(source_hash)
                    return SourceImportResult("already_imported", source_hash, saved.evidence)
            with PreparedImportSession(source, catalog=catalog, suffix=suffix, cancelled=cancelled) as prepared:
                with V2ProfileStore.open(self.profile_path, read_only=True) as store:
                    recognition = prepared.format_review(store)
                selection = review_format(source_path, recognition)
                if cancelled is not None and cancelled():
                    raise ImportCancelled("cancelled")
                if selection is None:
                    raise ImportSkipped("import_skipped")
                prepared.select_format(selection, cancelled=cancelled)
                # User review and JSON reconstruction hold no profile connection.
                source, current_suffix = _read_source(source_path)
                if current_suffix != suffix or hashlib.sha256(source).hexdigest() != recognition.source_sha256:
                    raise WorkspaceError("source_changed_since_preview")
                catalog = self.catalog_cache.load_current()
                if catalog is None:
                    raise WorkspaceError("verified_catalog_missing")

                def check_format_inputs():
                    final_source, final_suffix = _read_source(source_path)
                    if final_suffix != suffix or hashlib.sha256(final_source).hexdigest() != recognition.source_sha256:
                        raise WorkspaceError("source_changed_since_preview")
                    final_catalog = self.catalog_cache.load_current()
                    if final_catalog is None:
                        raise WorkspaceError("verified_catalog_missing")
                    if final_catalog.snapshot != catalog.snapshot:
                        raise CatalogImportError("catalog_selection_catalog_changed")

                with V2ProfileStore.open(self.profile_path) as store:
                    return import_prepared_catalog_source(
                        store,
                        prepared,
                        catalog=catalog,
                        selection=selection,
                        cancelled=cancelled,
                        before_write=check_format_inputs,
                    )
        if cancelled is not None and cancelled():
            raise ImportCancelled("cancelled")
        with V2ProfileStore.open(self.profile_path) as store:
            return import_catalog_source(store, source, catalog=catalog, suffix=suffix, cancelled=cancelled)

    def _import_with_accounts(self, source_path, review_import, *, cancelled=None):
        notice = ""
        while True:
            if cancelled is not None and cancelled():
                raise ImportCancelled("cancelled")
            source, suffix = _read_source(source_path)
            catalog = self.catalog_cache.load_current()
            if catalog is None:
                raise WorkspaceError("verified_catalog_missing")
            with V2ProfileStore.open(self.profile_path, read_only=True) as store:
                if store.source_imported(source):
                    source_hash = hashlib.sha256(source).hexdigest()
                    saved = store.load_import(source_hash)
                    return SourceImportResult("already_imported", source_hash, saved.evidence)
            with PreparedImportSession(source, catalog=catalog, suffix=suffix, cancelled=cancelled) as prepared:
                with V2ProfileStore.open(self.profile_path, read_only=True) as store:
                    review = prepared.review(store, preferences=self.preferences(), recovery_notice=notice)
                decision = automatic_import_plan(review)
                automatic = decision is not None
                if not automatic:
                    decision = review_import(source_path, review)
                if cancelled is not None and cancelled():
                    raise ImportCancelled("cancelled")
                if decision is None:
                    raise ImportSkipped("import_skipped")
                current_source, current_suffix = _read_source(source_path)
                if (
                    current_suffix != suffix
                    or hashlib.sha256(current_source).hexdigest() != review.recognition.source_sha256
                ):
                    notice = "The file changed after the preview. Check the refreshed account choices and interpretation before importing. Nothing from the earlier preview was saved."
                    continue
                current_catalog = self.catalog_cache.load_current()
                if current_catalog is None:
                    raise WorkspaceError("verified_catalog_missing")
                if current_catalog.snapshot != catalog.snapshot:
                    notice = "Statement formats changed after the preview. Check the refreshed choices before importing. Nothing from the earlier preview was saved."
                    continue
                prepared.select(decision, cancelled=cancelled)
                try:

                    def check_current_inputs(
                        expected_suffix=suffix,
                        expected_hash=review.recognition.source_sha256,
                        expected_catalog=current_catalog.snapshot,
                    ):
                        final_source, final_suffix = _read_source(source_path)
                        if final_suffix != expected_suffix or hashlib.sha256(final_source).hexdigest() != expected_hash:
                            raise WorkspaceError("import_source_changed_during_validation")
                        final_catalog = self.catalog_cache.load_current()
                        if final_catalog is None:
                            raise WorkspaceError("verified_catalog_missing")
                        if final_catalog.snapshot != expected_catalog:
                            raise WorkspaceError("import_catalog_changed_during_validation")

                    with V2ProfileStore.open(self.profile_path) as store:
                        return commit_import_accounts(
                            store,
                            prepared,
                            current_catalog,
                            decision,
                            cancelled=cancelled,
                            before_write=check_current_inputs,
                            automatic_preferences=self.preferences if automatic else None,
                        )
                except (ProfileFormatError, WorkspaceError) as exc:
                    notices = {
                        "import_automatic_review_required": "Automatic import needs attention. Review the current accounts, format and warnings before importing. Nothing was saved.",
                        "import_account_review_stale": "Accounts or saved document assignments changed after the preview. Check the refreshed choices and confirm again. Nothing from the earlier preview was saved.",
                        "import_source_changed_during_validation": "The file changed while its supported formats were being checked. Review the refreshed document before confirming again. Nothing from the earlier preview was saved.",
                        "import_catalog_changed_during_validation": "Statement formats changed while the import was being checked. Review the refreshed document before confirming again. Nothing from the earlier preview was saved.",
                    }
                    if str(exc) not in notices:
                        raise
                    notice = notices[str(exc)]

    def import_files(
        self,
        paths: tuple[Path, ...],
        *,
        cancelled: Callable[[], bool] | None = None,
        progress: Callable[[int, BatchFileResult], None] | None = None,
        review_format: FormatReview | None = None,
        review_import: ImportReview | None = None,
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
                imported = self.import_file(
                    path, cancelled=cancelled, review_format=review_format, review_import=review_import
                )
                result = BatchFileResult(
                    path,
                    imported.status,
                    imported.source_sha256,
                    loan_automation=imported.loan_automation,
                    statement_value_automation=imported.statement_value_automation,
                )
                if any(
                    outcome is not None and outcome.status == "cancelled"
                    for outcome in (imported.loan_automation, imported.statement_value_automation)
                ):
                    was_cancelled = True
            except ImportSkipped:
                result = BatchFileResult(path, "skipped")
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
