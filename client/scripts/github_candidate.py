"""Retrieve exactly two installer artifacts from a successful trusted workflow run."""

from __future__ import annotations

import json
import re
import shutil
import stat
import subprocess
import zipfile
from pathlib import Path

from scripts.client_candidate import BUILD_RECORD, TARGETS
from scripts.release_inventory import _sha256_file

REPOSITORY = "tbrownhe/ParseTrail"
WORKFLOW = ".github/workflows/client-release.yml"
MAX_INSTALLER_BYTES = 1024 * 1024 * 1024


def gh_json(endpoint: str) -> dict:
    result = subprocess.run(["gh", "api", endpoint], capture_output=True, text=True, check=False, timeout=60)
    if result.returncode:
        raise ValueError("GitHub API request failed. Run 'gh auth login' once, then retry.")
    return json.loads(result.stdout)


def validate_run(run: dict, artifacts: dict) -> dict[str, dict]:
    if (
        run.get("status") != "completed"
        or run.get("conclusion") != "success"
        or run.get("event") != "workflow_dispatch"
        or run.get("path", "").split("@", 1)[0] != WORKFLOW
        or run.get("repository", {}).get("full_name", "").lower() != REPOSITORY.lower()
        or run.get("head_repository", {}).get("full_name", "").lower() != REPOSITORY.lower()
    ):
        raise ValueError("Select a successful ParseTrail desktop-release workflow run, not a fork or test workflow")
    selected = {}
    for target in TARGETS:
        matches = [a for a in artifacts.get("artifacts", []) if a.get("name") == f"client-installer-{target}"]
        if len(matches) != 1 or matches[0].get("expired") is not False:
            raise ValueError(f"Run must contain one unexpired installer artifact for {target}")
        artifact = matches[0]
        if (
            artifact.get("workflow_run", {}).get("id") != run.get("id")
            or not isinstance(artifact.get("digest"), str)
            or not re.fullmatch(r"sha256:[0-9a-f]{64}", artifact["digest"])
        ):
            raise ValueError("GitHub artifact has no matching run identity or immutable digest")
        selected[target] = artifact
    return selected


def extract_candidate(archive: Path, destination: Path, target: str, digest: str) -> None:
    if _sha256_file(archive) != digest.removeprefix("sha256:"):
        raise ValueError("Downloaded artifact differs from GitHub's immutable digest")
    with zipfile.ZipFile(archive) as zipped:
        entries = zipped.infolist()
        names = [item.filename for item in entries]
        suffix = "exe" if target == "windows-x86_64" else "dmg"
        pattern = rf"parsetrail_[0-9]+\.[0-9]+\.[0-9]+_{re.escape(target)}_setup\.{suffix}"
        if len(names) != 2 or names.count(BUILD_RECORD) != 1 or sum(bool(re.fullmatch(pattern, n)) for n in names) != 1:
            raise ValueError("CI artifact must contain exactly one installer and its build record")
        for item in entries:
            limit = 1024 * 1024 if item.filename == BUILD_RECORD else MAX_INSTALLER_BYTES
            if item.is_dir() or stat.S_ISLNK(item.external_attr >> 16) or not 0 < item.file_size <= limit:
                raise ValueError("CI artifact contains an unsupported entry")
        destination.mkdir()
        for item in entries:
            # Names were allowlisted above; never call unrestricted extractall.
            with zipped.open(item) as source, (destination / item.filename).open("xb") as output:
                shutil.copyfileobj(source, output)


def download_run(run_id: int, destination: Path) -> dict:
    if run_id <= 0 or shutil.which("gh") is None:
        raise ValueError("Install GitHub CLI, run 'gh auth login', and supply a positive run ID")
    endpoint = f"repos/{REPOSITORY}/actions/runs/{run_id}"
    run = gh_json(endpoint)
    selected = validate_run(run, gh_json(endpoint + "/artifacts?per_page=100"))
    for target, artifact in selected.items():
        archive = destination / f"{target}.zip"
        with archive.open("xb") as stream:
            result = subprocess.run(
                ["gh", "api", f"repos/{REPOSITORY}/actions/artifacts/{int(artifact['id'])}/zip"],
                stdout=stream,
                stderr=subprocess.PIPE,
                check=False,
                timeout=600,
            )
        if result.returncode:
            raise ValueError(f"Could not download {target} from the selected run")
        extract_candidate(archive, destination / target, target, artifact["digest"])
    return {
        "repository": REPOSITORY,
        "run_id": run_id,
        "run_attempt": run.get("run_attempt"),
        "workflow_commit": run.get("head_sha"),
        "artifacts": {target: {key: value[key] for key in ("id", "digest")} for target, value in selected.items()},
    }
