"""Launch ParseTrail against a marked disposable import-acceptance database."""

from __future__ import annotations

import argparse
import importlib
from pathlib import Path

from prepare import MARKER_FILENAME


class AcceptanceLaunchError(RuntimeError):
    """The acceptance GUI cannot be launched without its safety boundaries."""


def _plain_filename(value: str) -> str:
    if Path(value).name != value or value in {"", ".", ".."}:
        raise argparse.ArgumentTypeError("must be one plain filename")
    return value


def _configure_sandbox(database: Path) -> tuple[object, dict[str, object]]:
    import json

    settings_module = importlib.import_module("parsetrail.core.settings")
    app_settings = settings_module.settings
    database = database.expanduser().resolve()
    configured_database = Path(app_settings.db_path).expanduser().resolve()
    if not database.is_file():
        raise AcceptanceLaunchError(f"acceptance database does not exist: {database}")
    if database == configured_database:
        raise AcceptanceLaunchError("refusing to run acceptance injections against the configured database")

    marker_path = database.parent / MARKER_FILENAME
    try:
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AcceptanceLaunchError(f"acceptance marker is missing or invalid: {marker_path}") from exc
    if marker.get("schema_version") != 1 or Path(str(marker.get("database", ""))).resolve() != database:
        raise AcceptanceLaunchError("acceptance marker does not describe the requested database")

    app_settings.db_path = database
    app_settings.automatic_update_checks = False
    app_settings.log_file = database.parent / "acceptance.log"
    app_settings.report_dir = database.parent / "REPORTS"

    def refuse_settings_save(_settings: object) -> None:
        raise AcceptanceLaunchError("the acceptance launcher refuses to save the real client configuration")

    settings_module.save_settings = refuse_settings_save
    return app_settings, marker


def _install_injections(
    *,
    app_settings: object,
    cancel_after: int | None,
    fail_archive_for: str | None,
) -> None:
    from parsetrail.core.statements import StatementProcessor

    if fail_archive_for is not None:
        original_move = StatementProcessor.move_file_safely
        failure_injected = False

        def move_with_one_failure(self, source: Path, destination: Path) -> None:
            nonlocal failure_injected
            is_target_archive = (
                not failure_injected
                and source.name == fail_archive_for
                and destination.parent.resolve() == app_settings.success_dir.resolve()
            )
            if is_target_archive:
                failure_injected = True
                raise OSError("injected acceptance-test archive failure")
            original_move(self, source, destination)

        StatementProcessor.move_file_safely = move_with_one_failure

    if cancel_after is not None:
        original_import = StatementProcessor.import_one
        completed = 0
        cancellation_injected = False

        def import_with_one_cancellation(self, path: Path, parent=None) -> str:
            nonlocal completed, cancellation_injected
            result = original_import(self, path, parent=parent)
            completed += 1
            if completed == cancel_after and not cancellation_injected:
                from PySide6.QtWidgets import QApplication, QProgressDialog

                cancellation_injected = True
                for widget in QApplication.topLevelWidgets():
                    if isinstance(widget, QProgressDialog) and widget.windowTitle() == "Import Progress":
                        widget.cancel()
            return result

        StatementProcessor.import_one = import_with_one_cancellation


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--cancel-after", type=int)
    parser.add_argument("--fail-archive-for", type=_plain_filename)
    return parser


def main() -> int:
    args = _parser().parse_args()
    if args.cancel_after is not None and args.cancel_after <= 0:
        raise SystemExit("ERROR: --cancel-after must be positive")
    try:
        app_settings, marker = _configure_sandbox(args.database)
        _install_injections(
            app_settings=app_settings,
            cancel_after=args.cancel_after,
            fail_archive_for=args.fail_archive_for,
        )
    except AcceptanceLaunchError as exc:
        raise SystemExit(f"ERROR: {exc}") from exc

    print("IMPORT ACCEPTANCE SANDBOX")
    print(f"Database: {app_settings.db_path}")
    print(f"Import directory: {app_settings.import_dir}")
    print("The saved ParseTrail configuration will not be changed.")
    if args.cancel_after is not None:
        print(f"The batch will be canceled after {args.cancel_after} completed file(s).")
    if args.fail_archive_for is not None:
        print(f"The next SUCCESS archive move for {args.fail_archive_for} will fail once.")
    print(f"Prepared fixtures: {marker['mohela']['filename']}, {marker['occu']['filename']}")

    from parsetrail.main import main as client_main

    return client_main()


if __name__ == "__main__":
    raise SystemExit(main())
