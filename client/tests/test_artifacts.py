from pathlib import Path

import pytest
from parsetrail.core.artifacts import InvalidArtifactName, resolve_artifact_destination


def test_resolves_plain_plugin_name(tmp_path: Path) -> None:
    assert (
        resolve_artifact_destination(tmp_path, "pdf_example_202601.pyc", allowed_suffixes={".pyc"})
        == (tmp_path / "pdf_example_202601.pyc").resolve()
    )


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
        resolve_artifact_destination(tmp_path, untrusted_name, allowed_suffixes={".pyc"})
