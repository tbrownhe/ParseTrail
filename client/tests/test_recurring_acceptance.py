import importlib.util
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest

LAUNCHER = Path(__file__).resolve().parents[2] / "devtools" / "recurring_acceptance" / "launch.py"


@pytest.mark.parametrize("review", [False, True])
def test_recurring_acceptance_uses_synthetic_profile_despite_environment_overrides(tmp_path, review):
    sentinel = tmp_path / "must-not-open.db"
    sentinel.write_bytes(b"not a sqlite database: must remain untouched")
    env = os.environ.copy()
    env.update(
        QT_QPA_PLATFORM="offscreen",
        DB_PATH=str(sentinel),
        MODEL_PATH=str(sentinel),
        PARSETRAIL_PROFILE="staging",
        PARSETRAIL_STAGING_SERVER_URL="https://must-not-connect.invalid/api/v1",
    )
    command = [sys.executable, str(LAUNCHER), "--smoke-test"]
    if review:
        command.append("--review")
    result = subprocess.run(command, env=env, capture_output=True, text=True, timeout=45, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "C1 synthetic smoke passed." in result.stdout
    assert sentinel.read_bytes() == b"not a sqlite database: must remain untouched"
    assert str(sentinel) not in result.stdout + result.stderr


def test_acceptance_copy_is_independent_of_original_database(tmp_path):
    spec = importlib.util.spec_from_file_location("recurring_acceptance", LAUNCHER)
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    original = tmp_path / "source #1.db"
    snapshot = tmp_path / "snapshot.db"
    with closing(sqlite3.connect(original)) as connection:
        connection.execute("CREATE TABLE sentinel (value INTEGER)")
        connection.execute("INSERT INTO sentinel VALUES (7)")
        connection.commit()
    original_bytes = original.read_bytes()
    launcher._copy_database(original, snapshot)
    with closing(sqlite3.connect(snapshot)) as connection:
        assert connection.execute("SELECT value FROM sentinel").fetchone() == (7,)
        connection.execute("UPDATE sentinel SET value = 9")
        connection.commit()
    assert original.read_bytes() == original_bytes
