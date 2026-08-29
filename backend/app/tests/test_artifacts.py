from pathlib import Path

import pytest

from app.core.artifacts import InvalidArtifactName, resolve_artifact_path


def test_resolves_plain_artifact_name(tmp_path: Path) -> None:
    artifact = tmp_path / "plugin.pyc"
    artifact.write_bytes(b"plugin")

    assert resolve_artifact_path(tmp_path, "plugin.pyc", allowed_suffixes={".pyc"}) == artifact.resolve()


@pytest.mark.parametrize(
    "untrusted_name",
    [
        "",
        ".",
        "..",
        "../plugin.pyc",
        "subdir/plugin.pyc",
        "subdir\\plugin.pyc",
        "/tmp/plugin.pyc",
        "plugin.py",
    ],
)
def test_rejects_unsafe_artifact_names(tmp_path: Path, untrusted_name: str) -> None:
    with pytest.raises(InvalidArtifactName):
        resolve_artifact_path(tmp_path, untrusted_name, allowed_suffixes={".pyc"})
