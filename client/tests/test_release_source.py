import json
import subprocess
from pathlib import Path

import pytest
from scripts.release_source import (
    ReleaseSourceError,
    validate_client_release,
    write_build_metadata,
)


def _git(repository: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _repository(tmp_path: Path, *, tag: str | None = "client-v1.2.3") -> Path:
    repository = tmp_path / "repository"
    repository.mkdir()
    _git(repository, "init")
    _git(repository, "config", "user.email", "release-test@example.com")
    _git(repository, "config", "user.name", "Release Test")
    (repository / "tracked.txt").write_text("source", encoding="utf-8")
    _git(repository, "add", "tracked.txt")
    _git(repository, "commit", "-m", "release source")
    if tag is not None:
        _git(repository, "tag", tag)
    return repository


def test_accepts_clean_matching_client_tag_and_writes_metadata(tmp_path: Path) -> None:
    repository = _repository(tmp_path)

    source = validate_client_release("1.2.3", repository=repository)
    output = tmp_path / "build-metadata.json"
    write_build_metadata(
        output,
        source=source,
        version="1.2.3",
        target_platform="win64",
    )
    metadata = json.loads(output.read_text(encoding="utf-8"))

    assert metadata["source_commit"] == _git(repository, "rev-parse", "HEAD")
    assert metadata["source_tag"] == "client-v1.2.3"
    assert metadata["client_version"] == "1.2.3"


def test_rejects_dirty_or_mismatched_release_source(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    (repository / "untracked.txt").write_text("dirty", encoding="utf-8")

    with pytest.raises(ReleaseSourceError, match="clean Git worktree"):
        validate_client_release("1.2.3", repository=repository)

    (repository / "untracked.txt").unlink()
    with pytest.raises(ReleaseSourceError, match="client-v1.2.4"):
        validate_client_release("1.2.4", repository=repository)


@pytest.mark.parametrize("version", ["1.2", "01.2.3", "v1.2.3"])
def test_rejects_non_semantic_client_version(tmp_path: Path, version: str) -> None:
    with pytest.raises(ValueError, match="semantic version"):
        validate_client_release(version, repository=tmp_path)
