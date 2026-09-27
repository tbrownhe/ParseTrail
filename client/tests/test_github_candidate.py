from __future__ import annotations

import copy
import hashlib
import zipfile

import pytest
from scripts.github_candidate import REPOSITORY, WORKFLOW, extract_candidate, validate_run


def run_records():
    run = {
        "id": 42,
        "status": "completed",
        "conclusion": "success",
        "event": "workflow_dispatch",
        "path": WORKFLOW,
        "repository": {"full_name": REPOSITORY},
        "head_repository": {"full_name": REPOSITORY},
    }
    artifacts = {
        "artifacts": [
            {
                "name": f"client-installer-{target}",
                "expired": False,
                "workflow_run": {"id": 42},
                "digest": "sha256:" + "a" * 64,
            }
            for target in ("windows-x86_64", "macos-x86_64")
        ]
    }
    return run, artifacts


@pytest.mark.parametrize(
    "invalid",
    ["failure", "fork", "workflow", "validation-run", "missing", "duplicate", "expired", "digest", "wrong-run"],
)
def test_run_rejects_untrusted_or_incomplete_artifacts(invalid):
    run, artifacts = run_records()
    if invalid == "failure":
        run["conclusion"] = "failure"
    elif invalid == "fork":
        run["head_repository"]["full_name"] = "someone/ParseTrail"
    elif invalid == "workflow":
        run["path"] = ".github/workflows/test-backend.yml"
    elif invalid == "validation-run":
        run["event"] = "push"
    elif invalid == "missing":
        artifacts["artifacts"].pop()
    elif invalid == "duplicate":
        artifacts["artifacts"].append(copy.deepcopy(artifacts["artifacts"][0]))
    elif invalid == "expired":
        artifacts["artifacts"][0]["expired"] = True
    elif invalid == "digest":
        artifacts["artifacts"][0]["digest"] = None
    else:
        artifacts["artifacts"][0]["workflow_run"]["id"] = 77
    with pytest.raises(ValueError):
        validate_run(run, artifacts)


def test_successful_run_requires_both_immutable_targets():
    run, artifacts = run_records()
    assert set(validate_run(run, artifacts)) == {"windows-x86_64", "macos-x86_64"}


@pytest.mark.parametrize("bad_name", ["../payload.exe", "/payload.exe", "subdir/build-record.json"])
def test_archive_rejects_paths_before_extracting(tmp_path, bad_name):
    archive = tmp_path / "candidate.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("build-record.json", "{}")
        output.writestr(bad_name, "bad")
    digest = "sha256:" + hashlib.sha256(archive.read_bytes()).hexdigest()
    with pytest.raises(ValueError, match="exactly one installer"):
        extract_candidate(archive, tmp_path / "output", "windows-x86_64", digest)
    assert not (tmp_path / "output").exists()


def test_archive_digest_and_valid_extraction(tmp_path):
    archive = tmp_path / "candidate.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("build-record.json", "{}")
        output.writestr("parsetrail_1.4.3_windows-x86_64_setup.exe", "synthetic")
    with pytest.raises(ValueError, match="immutable digest"):
        extract_candidate(archive, tmp_path / "bad", "windows-x86_64", "sha256:" + "0" * 64)
    extract_candidate(
        archive, tmp_path / "good", "windows-x86_64", "sha256:" + hashlib.sha256(archive.read_bytes()).hexdigest()
    )
    assert (tmp_path / "good/build-record.json").read_bytes() == b"{}"
