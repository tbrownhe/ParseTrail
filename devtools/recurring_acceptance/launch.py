"""Exercise the real recurring-analysis windows in a disposable local profile."""

from __future__ import annotations

import argparse
import hashlib
import os
import sqlite3
import sys
import tempfile
import time
from contextlib import ExitStack, closing
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch


def _copy_database(source: Path, destination: Path) -> None:
    source = source.expanduser().resolve(strict=True)
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as original:
        with closing(sqlite3.connect(destination)) as disposable:
            original.backup(disposable)


def _seed(Session) -> None:
    from parsetrail.core.orm import Accounts, AccountTypes, Transactions

    cases = [
        (1, "Streaming subscription", ["-19.99"] * 3),
        (4, "Variable merchant", ["-10", "-100", "-1000"]),
        (7, "the and or", ["-10"] * 3),
        (10, "Variable income", ["10", "100", "1000"]),
    ]
    with Session.begin() as session:
        session.add(AccountTypes(AccountTypeID=1, AccountType="Checking", AssetType="Asset"))
        session.add(Accounts(AccountID=1, AccountName="Synthetic checking", AccountTypeID=1, CurrencyCode="USD"))
        for month, description, amounts in cases:
            for offset, amount in enumerate(amounts):
                posting = date(2026, month + offset, 1)
                session.add(
                    Transactions(
                        AccountID=1,
                        PostingDate=posting,
                        Amount=Decimal(amount),
                        Balance=Decimal("5000"),
                        CurrencyCode="USD",
                        Description=description,
                        Fingerprint=hashlib.sha256(f"synthetic:{month}:{offset}".encode()).hexdigest(),
                        FingerprintVersion=1,
                        Verified=False,
                    )
                )


def _no_network(*_args, **_kwargs):
    raise RuntimeError("Networking is disabled in recurring acceptance.")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database", type=Path, help="Read only this explicit database and test a disposable snapshot."
    )
    parser.add_argument("--review", action="store_true", help="Open Transaction Review instead of Identify Recurring.")
    parser.add_argument(
        "--smoke-test", action="store_true", help="Run synthetic analysis and exit without interaction."
    )
    parser.add_argument("--slow-seconds", type=int, default=0, help="Delay each worker calculation by 0-30 seconds.")
    args = parser.parse_args()
    if args.smoke_test and args.database:
        parser.error("--smoke-test accepts synthetic inputs only")
    if not 0 <= args.slow_seconds <= 30:
        parser.error("--slow-seconds must be between 0 and 30")
    if "parsetrail.core.settings" in sys.modules:
        raise RuntimeError("Launch in a fresh process, before importing client settings.")

    with tempfile.TemporaryDirectory(prefix="parsetrail-recurring-") as directory, ExitStack() as stack:
        root = Path(directory).resolve()
        # Select an isolated profile before settings can read configuration or
        # credentials. Do not change HOME or reuse the owner's staging profile.
        overrides = {
            "PARSETRAIL_PROFILE": "staging",
            "PARSETRAIL_STAGING_SERVER_URL": "https://acceptance.invalid/api/v1",
            "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring",
            "DB_PATH": str(root / "data" / "acceptance.db"),
            "MODEL_DIR": str(root / "models"),
            "MODEL_PATH": str(root / "models" / "unused.mdl"),
            "PLUGIN_DIR": str(root / "plugins"),
            "LOG_FILE": str(root / "acceptance.log"),
            "REPORT_DIR": str(root / "reports"),
            "SERVER_URL": "https://acceptance.invalid/api/v1",
            "AUTOMATIC_UPDATE_CHECKS": "false",
            "ACCESS_TOKEN": "",
            "EMAIL": "",
        }
        environment = {key: value for key, value in os.environ.items() if key.upper() not in overrides}
        environment.update(overrides)
        stack.enter_context(patch.dict(os.environ, environment, clear=True))
        stack.enter_context(patch("parsetrail.core.profile.application_data_dir", return_value=root))
        stack.enter_context(patch("socket.create_connection", _no_network))
        stack.enter_context(patch("socket.socket.connect", _no_network))
        stack.enter_context(patch("socket.socket.connect_ex", _no_network))

        from loguru import logger
        from parsetrail.core.migrate import upgrade_db
        from parsetrail.core.orm import create_database
        from parsetrail.core.settings import settings
        from PySide6.QtCore import QDate, QTimer
        from PySide6.QtTest import QTest
        from PySide6.QtWidgets import QApplication

        logger.remove()
        sink = logger.add(root / "acceptance.log", diagnose=False)
        settings.db_path.parent.mkdir(parents=True, exist_ok=True)
        if args.database:
            _copy_database(args.database, settings.db_path)
        upgrade_db(settings.db_path)
        Session = create_database(settings.db_path)
        stack.callback(Session.kw["bind"].dispose)
        if not args.database:
            _seed(Session)
        if args.slow_seconds:
            from parsetrail.core import cluster
            from parsetrail.core.analysis import check_cancelled

            analyze = cluster.recurring_transactions

            def slow_analysis(frame, *, cancelled=None, **options):
                # Rehearse waiting for a non-interruptible library step while
                # the GUI processes events. Discard after cancellation.
                time.sleep(args.slow_seconds)
                check_cancelled(cancelled)
                return analyze(frame, cancelled=cancelled, **options)

            stack.enter_context(patch.object(cluster, "recurring_transactions", slow_analysis))
        app = QApplication.instance() or QApplication([])
        if args.review:
            from parsetrail.gui.verification import TransactionReviewWindow

            window = TransactionReviewWindow(Session)
            # This rehearsal covers clustering, not training or model loading.
            window.btn_auto_categorize.setEnabled(False)
            window.chk_use_max_variance.setChecked(True)
            window.spin_max_variance.setValue(0.1)
        else:
            from parsetrail.gui.transactions import RecurringTransactionsDialog

            window = RecurringTransactionsDialog(Session)
            if not args.database:
                window.start_date.setDate(QDate(2026, 1, 1))
                window.end_date.setDate(QDate(2026, 3, 31))
            window.variance_slider["slider"].setValue(10)
        title = "RECURRING ACCEPTANCE — DISPOSABLE COPY — " + window.windowTitle()
        window.setWindowTitle(title)
        heartbeat = QTimer(window)
        heartbeat.setInterval(250)
        ticks = 0

        def tick():
            nonlocal ticks
            ticks += 1
            window.setWindowTitle(f"{title} — GUI heartbeat {ticks}")

        heartbeat.timeout.connect(tick)
        heartbeat.start()
        print("Recurring acceptance: disposable profile, network disabled, original database unchanged.", flush=True)
        print("Closing this process removes the temporary database and profile.", flush=True)

        def wait_for_analysis():
            deadline = time.monotonic() + 40
            while window.analysis_job.busy and time.monotonic() < deadline:
                QTest.qWait(5)
            if window.analysis_job.busy:
                raise RuntimeError("Acceptance analysis did not finish within 40 seconds.")

        try:
            if args.smoke_test:
                if args.review:
                    window.cluster_recurring_transactions()
                    wait_for_analysis()
                    assert sum(rec.cluster is not None for rec in window.model._records) == 3
                else:
                    window.analyze_transactions()
                    wait_for_analysis()
                    assert window.model.rowCount() == 3
                    assert window.save_button.isEnabled()
                    window.start_date.setDate(QDate(2026, 4, 1))
                    window.end_date.setDate(QDate(2026, 6, 30))
                    window.analyze_transactions()
                    wait_for_analysis()
                    assert window.model.rowCount() == 0
                    window.start_date.setDate(QDate(2026, 7, 1))
                    window.end_date.setDate(QDate(2026, 9, 30))
                    window.analyze_transactions()
                    wait_for_analysis()
                    assert "No recurring matches" in window.status_label.text()
                    assert not window.save_button.isEnabled()
                print("Recurring synthetic smoke passed.")
                return 0
            window.show()
            return app.exec()
        finally:
            window.analysis_job.cancel()
            # Preserve worker lifetime even if the launcher's own checks fail.
            while window.analysis_job.busy:
                QTest.qWait(5)
            heartbeat.stop()
            window.close()
            window.deleteLater()
            app.processEvents()
            logger.remove(sink)


if __name__ == "__main__":
    raise SystemExit(main())
