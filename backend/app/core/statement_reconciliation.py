"""Read-only reconciliation of encrypted statement files and database rows."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StatementReconciliation:
    orphan_files: tuple[str, ...]
    missing_files: tuple[str, ...]

    @property
    def consistent(self) -> bool:
        return not self.orphan_files and not self.missing_files


def compare_statement_storage(
    statement_dir: Path,
    registered_file_names: set[str],
) -> StatementReconciliation:
    """Compare names only; encrypted file contents are never opened."""
    stored_file_names = {path.name for path in statement_dir.glob("*.enc") if path.is_file()}
    return StatementReconciliation(
        orphan_files=tuple(sorted(stored_file_names - registered_file_names)),
        missing_files=tuple(sorted(registered_file_names - stored_file_names)),
    )


def quarantine_orphan_files(
    statement_dir: Path,
    quarantine_dir: Path,
    orphan_file_names: tuple[str, ...],
) -> None:
    """Move reported encrypted orphans to an explicit recovery directory."""
    statement_root = statement_dir.resolve()
    quarantine_root = quarantine_dir.resolve()
    if statement_root == quarantine_root:
        raise ValueError("Quarantine directory must differ from statement storage")
    quarantine_root.mkdir(parents=True, exist_ok=True)

    for name in orphan_file_names:
        if Path(name).name != name or not name.endswith(".enc"):
            raise ValueError(f"Unsafe encrypted statement filename: {name}")
        source = (statement_root / name).resolve()
        destination = (quarantine_root / name).resolve()
        source.relative_to(statement_root)
        destination.relative_to(quarantine_root)
        if destination.exists():
            raise FileExistsError(f"Quarantine destination already exists: {destination}")
        source.replace(destination)
