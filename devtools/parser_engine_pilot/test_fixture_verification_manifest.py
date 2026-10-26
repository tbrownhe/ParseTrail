"""All-family source baseline feeds the actual fixed diagnostic entry workflow."""

from __future__ import annotations

import json

from parsetrail.core.v2_fixture_verification import run_fixture_verification, validate_manifest
from scripts.v2_fixture_manifest import build_fixture_manifest


def test_full_public_family_manifest_and_source_diagnostic_are_baseline_equal():
    content = build_fixture_manifest()
    manifest = validate_manifest(content)
    assert len(manifest.fixtures) == 23
    assert sum(fixture.suffix == ".pdf" for fixture in manifest.fixtures) == 21
    assert len({fixture.source_sha256 for fixture in manifest.fixtures}) == 23
    report = run_fixture_verification(content)
    assert report["runtime"] == "source" and report["status"] == "passed"
    assert report["counts"]["fixtures"] == 23 and report["counts"]["pdf"] == 21 and report["counts"]["csv"] == 2
    assert all(result["baseline_equal"] and result["retry_exact"] for result in report["fixtures"])
    assert all(report["checks"].values())
    assert "private_source_parity" in report["limits"] and report["limits"]["private_source_parity"] is False
    assert "source_base64" not in json.dumps(report)
