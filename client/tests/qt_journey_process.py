"""Process containment for synthetic Qt journeys; a failed child always fails.

No retry, garbage-collection changes or assertion suppression are performed.
Child output and command metadata are retained even after a timeout or crash.
"""

from __future__ import annotations

import json
import os
import re
import signal
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import pytest

TIMEOUT_SECONDS = 180
SCENARIOS = Path("client/tests/qt_journey_scenarios.py")


def _stop_child(process, output):
    """Drain our child and decoder processes on timeout or parent interruption."""
    if process.poll() is not None:
        return process.wait()
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=output,
                stderr=subprocess.STDOUT,
                timeout=15,
                check=False,
            )
        else:
            os.killpg(process.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        # Always fall back to terminating/reaping the direct owned process.
        pass
    finally:
        if process.poll() is None:
            process.kill()
    return process.wait(timeout=15)


def run_journey_case(node, config, tmp_path, *, scenarios=SCENARIOS):
    repo = Path(__file__).resolve().parents[2]
    scenarios = Path(scenarios)
    if not (repo / scenarios).resolve().is_relative_to((repo / "client/tests").resolve()):
        raise pytest.UsageError("Journey scenarios must be beneath client/tests")
    selected = config.getoption("--journey-artifacts")
    artifact_root = Path(selected).resolve() if selected else None
    if artifact_root is not None and not artifact_root.is_relative_to((repo / "scratch").resolve()):
        raise pytest.UsageError("--journey-artifacts must be beneath the repository scratch directory")
    label = re.sub(r"[^A-Za-z0-9_-]", "_", node)
    logs = (artifact_root / "process-logs" if artifact_root else tmp_path / "process-logs") / label / uuid4().hex[:8]
    logs.mkdir(parents=True)
    isolated = tmp_path / "child-profile"
    isolated.mkdir()
    environment = os.environ.copy()
    for key, folder in (
        ("HOME", isolated),
        ("USERPROFILE", isolated),
        ("APPDATA", isolated / "AppData" / "Roaming"),
        ("LOCALAPPDATA", isolated / "AppData" / "Local"),
    ):
        folder.mkdir(parents=True, exist_ok=True)
        environment[key] = str(folder)
    environment["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
    environment["PYTHONPATH"] = os.pathsep.join(str(path) for path in (repo, repo / "client/src", repo / "client"))
    # Explicit child node and temporary area: inherited CLI overrides must not
    # introduce other test nodes or recurse through the wrapper.
    environment.pop("PYTEST_ADDOPTS", None)
    command = [
        sys.executable,
        "-u",
        "-m",
        "pytest",
        "-p",
        "no:cacheprovider",
        f"{scenarios.as_posix()}::{node}",
        "--basetemp",
        str(tmp_path / "child-pytest"),
        "-vv",
    ]
    if config.getoption("--journey-native"):
        command.append("--journey-native")
    if artifact_root is not None:
        command.extend(("--journey-artifacts", str(artifact_root)))
    metadata = {"command": command, "cwd": str(repo), "timeout_seconds": TIMEOUT_SECONDS, "retry": False}
    metadata_path = logs / "process.json"
    output_path = logs / "pytest.log"
    with output_path.open("wb") as output:
        process = subprocess.Popen(
            command,
            cwd=repo,
            env=environment,
            stdout=output,
            stderr=subprocess.STDOUT,
            start_new_session=os.name != "nt",
        )
        metadata["pid"] = process.pid
        try:
            returncode = process.wait(timeout=TIMEOUT_SECONDS)
            metadata.update(returncode=returncode, timed_out=False)
        except subprocess.TimeoutExpired:
            returncode = _stop_child(process, output)
            metadata.update(returncode=returncode, timed_out=True)
        except BaseException as error:
            metadata["interrupted"] = type(error).__name__
            metadata["returncode"] = _stop_child(process, output)
            raise
        finally:
            metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    if metadata["timed_out"] or returncode != 0:
        tail = output_path.read_text(encoding="utf-8", errors="replace")[-12000:]
        pytest.fail(
            f"Journey child {'timed out' if metadata['timed_out'] else f'exited {returncode}'}: {node}\n"
            f"Full output: {output_path}\n{tail}",
            pytrace=False,
        )
