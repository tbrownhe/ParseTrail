from __future__ import annotations

import base64
import os
import subprocess
import sys
from pathlib import Path


def _write_staging_env(path: Path, statements: Path, plugins: Path, master_key: bytes) -> None:
    path.write_text(
        "\n".join(
            (
                "ENVIRONMENT=staging",
                f"MASTER_KEY={base64.b64encode(master_key).decode()}",
                f"STATEMENTS_DIR={statements}",
                f"PLUGINS_DIR={plugins}",
                "POSTGRES_SERVER=127.0.0.1",
                "POSTGRES_PORT=5432",
                "POSTGRES_USER=staging",
                "POSTGRES_PASSWORD=staging-password",
                "POSTGRES_DB=staging",
                "SSH_TUNNEL_ENABLE=false",
                "",
            )
        ),
        encoding="utf-8",
    )


def test_explicit_staging_env_selects_local_ciphertext_and_key(tmp_path: Path) -> None:
    devtool_dir = Path(__file__).parents[2] / "devtools" / "server_statements"
    statements = tmp_path / "statements"
    plugins = tmp_path / "plugins"
    statements.mkdir()
    plugins.mkdir()
    ciphertext = b"ciphertext-only-fixture"
    (statements / "fixture.enc").write_bytes(ciphertext)
    master_key = b"k" * 32
    env_file = tmp_path / "staging.env"
    _write_staging_env(env_file, statements, plugins, master_key)

    script = f"""
import json
import sys
sys.path.insert(0, {str(devtool_dir)!r})
from environment_cli import preselect_environment_file
preselect_environment_file(['--env-file', {str(env_file)!r}])
from settings import require_runtime_settings, target_summary
from ssh import fetch_encrypted_file, load_master_key
require_runtime_settings()
print(json.dumps({{
    'target': target_summary(),
    'ciphertext': fetch_encrypted_file('fixture.enc').decode(),
    'master_key': load_master_key().hex(),
}}))
"""
    environment = os.environ.copy()
    for name in (
        "ENVIRONMENT",
        "MASTER_KEY",
        "STATEMENTS_DIR",
        "PLUGINS_DIR",
        "POSTGRES_SERVER",
        "POSTGRES_PORT",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "POSTGRES_DB",
        "SSH_TUNNEL_ENABLE",
        "PARSETRAIL_ENV_FILE",
    ):
        environment.pop(name, None)
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )

    import json

    result = json.loads(completed.stdout.strip().splitlines()[-1])
    assert result["target"].startswith("STAGING | postgresql://127.0.0.1:5432/staging")
    assert str(env_file.resolve()) in result["target"]
    assert result["ciphertext"] == ciphertext.decode()
    assert result["master_key"] == master_key.hex()


def test_batch_help_accepts_explicit_environment_without_connecting(tmp_path: Path) -> None:
    repository = Path(__file__).parents[2]
    statements = tmp_path / "statements"
    plugins = tmp_path / "plugins"
    statements.mkdir()
    plugins.mkdir()
    env_file = tmp_path / "staging.env"
    _write_staging_env(env_file, statements, plugins, b"m" * 32)
    environment = os.environ.copy()
    environment.pop("PARSETRAIL_ENV_FILE", None)

    completed = subprocess.run(
        [
            sys.executable,
            str(repository / "devtools/server_statements/batch_plugin_tester.py"),
            "--env-file",
            str(env_file),
            "--help",
        ],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )

    assert "--env-file" in completed.stdout
    assert "Optional limit" in completed.stdout
