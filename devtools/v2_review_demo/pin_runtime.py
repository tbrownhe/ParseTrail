"""Preserve public runtime files and startup diagnostics for a disposable review."""

from __future__ import annotations

import ast
import hashlib
import json
import sqlite3
import stat
from pathlib import Path


def launcher_text(python_executable: Path) -> str:
    executable = str(python_executable.resolve()).replace("%", "%%")
    return (
        "@echo off\r\nsetlocal DisableDelayedExpansion\r\nchcp 65001 >nul\r\n"
        'set "DEMO_ROOT=%~dp0."\r\n'
        'set "DEMO_LOG=%DEMO_ROOT%\\last-launch.log"\r\n'
        'cd /d "%DEMO_ROOT%\\runtime"\r\n'
        "if errorlevel 1 exit /b 3\r\n"
        '"'
        + executable
        + '" -B -X utf8 "%DEMO_ROOT%\\runtime\\devtools\\v2_review_demo\\prepare_demo.py" --open "%DEMO_ROOT%" >"%DEMO_LOG%" 2>&1\r\n'
        'set "DEMO_EXIT=%ERRORLEVEL%"\r\n'
        'if not "%DEMO_EXIT%"=="0" (\r\n'
        '  type "%DEMO_LOG%"\r\n'
        "  echo.\r\n"
        '  echo Demo did not start. Details: "%DEMO_LOG%"\r\n'
        "  pause\r\n"
        ")\r\n"
        "exit /b %DEMO_EXIT%\r\n"
    )


def pin_runtime(source_repository: Path, demo_directory: Path, python_executable: Path, helper_source: Path) -> dict:
    """Create once; refuse schema mismatch before copying; retain only public code/resources.

    The caller supplies an already-created disposable synthetic profile, catalog,
    public demo trust and preferences. No production trust or private key is copied.
    This function never builds, releases, migrates or overwrites a runtime.
    """
    repository, demo = source_repository.resolve(), demo_directory.resolve()
    if not demo.is_dir() or not (demo / "review.db").is_file():
        raise ValueError("demo_profile_missing")
    runtime = demo / "runtime"
    if runtime.exists() or runtime.is_symlink():
        raise ValueError("demo_runtime_already_exists")
    if not runtime.resolve().is_relative_to(demo):
        raise ValueError("demo_runtime_path")
    store_source = repository / "client/src/parsetrail/core/v2_profile_store.py"
    module = ast.parse(store_source.read_bytes())
    schemas = [
        node.value.value
        for node in module.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "SCHEMA_VERSION" for target in node.targets)
        and isinstance(node.value, ast.Constant)
    ]
    if len(schemas) != 1 or type(schemas[0]) is not int:
        raise ValueError("runtime_schema_unknown")
    with sqlite3.connect((demo / "review.db").as_uri() + "?mode=ro", uri=True) as connection:
        profile_schema = connection.execute("PRAGMA user_version").fetchone()[0]
    if schemas[0] != profile_schema:
        raise ValueError("demo_runtime_schema_mismatch")
    records = []
    for relative in ("client/src/parsetrail", "client/scripts", "client/assets"):
        base = repository / relative
        if not base.is_dir():
            raise ValueError("runtime_resource_directory_missing")
        for source in sorted(base.rglob("*")):
            if "__pycache__" in source.parts or source.suffix in {".pyc", ".pyo"}:
                continue
            if source.is_symlink():
                raise ValueError("runtime_source_symlink")
            if not source.is_file():
                continue
            path = source.relative_to(repository)
            target = runtime / path
            target.parent.mkdir(parents=True, exist_ok=True)
            content = source.read_bytes()
            target.write_bytes(content)
            digest = hashlib.sha256(content).hexdigest()
            if hashlib.sha256(source.read_bytes()).hexdigest() != digest:
                raise ValueError("runtime_source_changed")
            records.append({"path": path.as_posix(), "sha256": digest, "size": len(content)})
    helper = runtime / "devtools/v2_review_demo/prepare_demo.py"
    helper.parent.mkdir(parents=True)
    code = helper_source.read_text(encoding="utf-8-sig")
    if "SNAPSHOT_PATHS =" not in code or 'os.environ["PYTHONPATH"]' not in code:
        raise ValueError("demo_helper_path_bootstrap_unknown")
    helper.write_text(code, encoding="utf-8", newline="")
    compile(helper.read_bytes(), str(helper), "exec")
    records.append(
        {
            "path": helper.relative_to(runtime).as_posix(),
            "sha256": hashlib.sha256(helper.read_bytes()).hexdigest(),
            "size": helper.stat().st_size,
        }
    )
    records.sort(key=lambda row: row["path"])
    manifest = {
        "schema_version": profile_schema,
        "purpose": "Pinned public synthetic review runtime, not release acceptance",
        "files": records,
    }
    for record in records:
        path = runtime / record["path"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
            raise ValueError("runtime_copy_integrity")
        source = helper_source if path == helper else repository / record["path"]
        if hashlib.sha256(source.read_bytes()).hexdigest() != record["sha256"]:
            raise ValueError("runtime_source_changed")
        path.chmod(stat.S_IREAD)
    (demo / "runtime-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (demo / "Open-review-demo.cmd").write_text(launcher_text(python_executable), encoding="utf-8", newline="")
    return manifest
