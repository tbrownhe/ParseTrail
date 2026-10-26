"""Ordinary fresh V2 startup and explicitly isolated diagnostics/workers."""

import os
import signal
import sys
from contextlib import suppress
from platform import system

RUNTIME_SMOKE_TEST_ARGUMENT = "--runtime-smoke-test"


def handle_signal(_signal, _frame):
    """Interrupt without importing legacy settings or its file logger."""
    raise SystemExit(0)


def run_runtime_smoke_test() -> int:
    """Native dependency/provenance operations, not V2 financial acceptance."""
    from parsetrail.core.runtime_smoke import check_build_provenance, check_native_operations

    if getattr(sys, "frozen", False):
        check_build_provenance()
    for module_name in ("_socket", "socket", "multiprocessing", "parsetrail.core.credentials"):
        __import__(module_name)
    if system() in {"Windows", "Darwin"}:
        from parsetrail.core.credentials import credential_store

        if not credential_store.available:
            raise RuntimeError("No native OS credential backend is bundled")
    check_native_operations()
    return 0


def _isolated_runtime_smoke(staging_url=None) -> int:
    import tempfile
    from contextlib import ExitStack
    from pathlib import Path
    from unittest.mock import patch

    from parsetrail.core.profile import normalize_staging_server_url
    from parsetrail.core.v2_offline_smoke import _deny_network

    if staging_url is not None:
        staging_url = normalize_staging_server_url(staging_url)
    keep = {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP", "TMPDIR", "LANG", "LC_ALL"}
    env = {key: value for key, value in os.environ.items() if key.upper() in keep or key.startswith(("_PYI", "QT_"))}
    with tempfile.TemporaryDirectory(prefix="parsetrail-native-smoke-") as temporary, ExitStack() as patches:
        root = Path(temporary)
        env.update(
            HOME=temporary,
            USERPROFILE=temporary,
            APPDATA=str(root / "appdata"),
            XDG_CONFIG_HOME=str(root / "config"),
            XDG_DATA_HOME=str(root / "data"),
            XDG_CACHE_HOME=str(root / "cache"),
            PARSETRAIL_PROFILE="staging" if staging_url else "default",
        )
        if staging_url:
            env["PARSETRAIL_STAGING_SERVER_URL"] = staging_url
        patches.enter_context(patch.dict(os.environ, env, clear=True))
        attempts = []
        _deny_network(patches, attempts)
        result = run_runtime_smoke_test()
        if attempts:
            raise RuntimeError("Native dependency diagnostic attempted network access")
        return result


def create_application(argv):
    os.environ.setdefault("QT_API", "PySide6")
    os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
    if system() == "Windows":
        os.environ.setdefault("QT_QPA_PLATFORM", "windows")
    from PySide6.QtWidgets import QApplication

    return QApplication(argv)


def _prepare_application(app):
    """Appearance uses a constant bundled asset, without legacy bootstrap imports."""
    from pathlib import Path

    from PySide6.QtGui import QIcon

    base = Path(sys._MEIPASS) if hasattr(sys, "_MEIPASS") else Path(__file__).resolve().parents[2]
    icon = base / "assets" / "parsetrail_128px.ico"
    if icon.is_file():
        app.setWindowIcon(QIcon(str(icon)))
    with suppress(ImportError, OSError, RuntimeError):
        import pyi_splash  # type: ignore

        pyi_splash.close()


def run_v2_workspace(argv: list[str]) -> int:
    """Default desktop path; parse all options before GUI/configuration imports."""
    import argparse
    import sqlite3
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Open a fresh ParseTrail 2.0 workspace")
    parser.add_argument("--v2", action="store_true", help="Optional explicit selector for the current runtime")
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--catalog-cache", type=Path)
    parser.add_argument("--preferences", type=Path)
    parser.add_argument("--create-profile", action="store_true")
    args = parser.parse_args(argv)
    if args.create_profile and args.profile is None:
        parser.error("--create-profile requires --profile; omit both to use the chooser")
    from parsetrail.core.v2_preferences import default_preferences_path
    from parsetrail.core.v2_workspace import V2Workspace

    catalog = args.catalog_cache or default_preferences_path().parent / "v2-catalog"
    previous_signal = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, handle_signal)
    try:
        app = None
        if args.profile is None:
            from PySide6.QtWidgets import QApplication, QDialog

            from parsetrail.gui.v2_profile_startup import V2ProfileStartupDialog

            app = QApplication.instance() or create_application(sys.argv[:1])
            _prepare_application(app)
            startup = V2ProfileStartupDialog(catalog, preferences_path=args.preferences)
            if startup.exec() != QDialog.Accepted or startup.workspace is None:
                return 0
            workspace = startup.workspace
        else:
            V2Workspace(args.profile, catalog, preferences_path=args.preferences).verify_local_configuration()
            workspace = (
                V2Workspace.create(args.profile, catalog, preferences_path=args.preferences)
                if args.create_profile
                else V2Workspace.open(args.profile, catalog, preferences_path=args.preferences)
            )
        from parsetrail.gui.v2_workspace_window import V2WorkspaceWindow

        if app is None:
            from PySide6.QtWidgets import QApplication

            app = QApplication.instance() or create_application(sys.argv[:1])
            _prepare_application(app)
        window = V2WorkspaceWindow(workspace)
        window.show()
        return app.exec()
    except (OSError, ValueError, sqlite3.Error) as exc:
        if sys.stderr is not None:
            print(f"ParseTrail 2.0 could not start: {exc}", file=sys.stderr)
        return 2
    finally:
        signal.signal(signal.SIGINT, previous_signal)


def main() -> int:
    args = sys.argv[1:]
    if args[:1] == ["--v2-parser-worker"]:
        # Keep imports explicit so frozen analysis includes every worker entry.
        if args[1:2] == ["annotation-period"]:
            from parsetrail.core.v2_pdf_annotation_worker import main as worker_main

            return worker_main(args[2:])
        if args[1:2] == ["xlsx-evidence"]:
            from parsetrail.core.v2_xlsx_worker import main as worker_main

            return worker_main(args[2:])
        if args[1:2] == ["anchored-table"]:
            from parsetrail.core.v2_anchored_table_worker import main as worker_main

            return worker_main(args[2:])
        if args[1:2] == ["wells-table"]:
            from parsetrail.core.v2_wells_table_worker import main as worker_main

            return worker_main(args[2:])
        if args[1:2] == ["citi-table"]:
            from parsetrail.core.v2_citi_table_worker import main as worker_main

            return worker_main(args[2:])
        from parsetrail.core.v2_pdf_text_worker import main as worker_main

        return worker_main(args[1:])
    if "--v2-verify-fixtures" in args:
        from parsetrail.core.v2_fixture_verification import main as fixture_main

        return fixture_main(args)
    if "--offline-session-smoke-test" in args:
        import argparse
        from pathlib import Path

        parser = argparse.ArgumentParser(
            description="Exercise a disposable V2 workspace with every network attempt denied"
        )
        parser.add_argument(
            "--offline-session-smoke-test", choices=("fresh", "cached", "network-failure"), required=True
        )
        parser.add_argument("--offline-smoke-report", type=Path)
        selected = parser.parse_args(args)
        from parsetrail.core.v2_offline_smoke import run_offline_session_smoke

        sys.argv[:] = sys.argv[:1]
        return run_offline_session_smoke(
            selected.offline_session_smoke_test, main, report_path=selected.offline_smoke_report
        )
    if RUNTIME_SMOKE_TEST_ARGUMENT in args:
        import argparse

        parser = argparse.ArgumentParser(description="Isolated native dependency diagnostic; not financial acceptance")
        parser.add_argument(RUNTIME_SMOKE_TEST_ARGUMENT, action="store_true", required=True)
        parser.add_argument(
            "--staging",
            metavar="HTTPS_API_URL",
            help="Explicit native-diagnostic credential-service context only; no network request",
        )
        selected = parser.parse_args(args)
        try:
            return _isolated_runtime_smoke(selected.staging)
        except (OSError, ValueError, RuntimeError) as exc:
            if sys.stderr is not None:
                print(f"Native runtime diagnostic failed: {exc}", file=sys.stderr)
            return 1
    return run_v2_workspace(args)


if __name__ == "__main__":
    raise SystemExit(main())
