"""Filesystem boundary checks for server-hosted download artifacts."""

from pathlib import Path


class InvalidArtifactName(ValueError):
    """Raised when an untrusted artifact name can escape its configured root."""


def resolve_artifact_path(root: Path, untrusted_name: str, *, allowed_suffixes: set[str]) -> Path:
    """Resolve one plain filename below ``root`` and enforce its artifact type."""
    supplied_path = Path(untrusted_name)
    if (
        not untrusted_name
        or "/" in untrusted_name
        or "\\" in untrusted_name
        or supplied_path.name != untrusted_name
        or untrusted_name in {".", ".."}
        or supplied_path.is_absolute()
    ):
        raise InvalidArtifactName("Artifact name must be a plain filename")

    normalized_suffixes = {suffix.lower() for suffix in allowed_suffixes}
    if supplied_path.suffix.lower() not in normalized_suffixes:
        raise InvalidArtifactName("Artifact has an unsupported file type")

    resolved_root = root.resolve()
    resolved_path = (root / supplied_path).resolve()
    try:
        resolved_path.relative_to(resolved_root)
    except ValueError as exc:
        raise InvalidArtifactName("Artifact path escapes its configured root") from exc
    return resolved_path
