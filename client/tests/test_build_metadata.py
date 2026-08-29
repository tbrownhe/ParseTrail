import json
from pathlib import Path

import pytest
from parsetrail.core import build_metadata


def test_reads_embedded_release_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata_path = tmp_path / "build-metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "client_version": "1.3.0",
                "source_commit": "a" * 40,
                "source_tag": "client-v1.3.0",
                "target_platform": "win64",
                "built_at": "2026-08-29T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(build_metadata, "resource_path", lambda _path: metadata_path)

    metadata = build_metadata.read_build_metadata()

    assert metadata is not None
    assert metadata.source_commit == "a" * 40
    assert build_metadata.build_provenance_label() == f"client-v1.3.0 ({'a' * 12})"


def test_invalid_or_missing_build_metadata_is_development_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing = tmp_path / "missing.json"
    monkeypatch.setattr(build_metadata, "resource_path", lambda _path: missing)

    assert build_metadata.read_build_metadata() is None
    assert build_metadata.build_provenance_label() == "development source"
