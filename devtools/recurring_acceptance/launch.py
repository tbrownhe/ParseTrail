"""Exercise recurring analysis or model training in a disposable local profile."""

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


def _seed_training(Session):
    from parsetrail.core.orm import Accounts, AccountTypes, Categories, Transactions

    with Session.begin() as session:
        session.add(AccountTypes(AccountTypeID=1, AccountType="Checking", AssetType="Asset"))
        session.add(Accounts(AccountID=1, AccountName="Synthetic", Company="Example", AccountTypeID=1))
        for category_id, category, description in [
            (1, "Food", "Grocery market produce"),
            (2, "Utilities", "Electric utility energy"),
        ]:
            session.add(Categories(CategoryID=category_id, Name=category, Type="Expense", Active=True))
            for day in range(1, 21):
                session.add(
                    Transactions(
                        AccountID=1,
                        PostingDate=date(2026, 8, day),
                        Amount=Decimal("-10"),
                        Balance=Decimal("5000"),
                        Description=description,
                        CategoryID=category_id,
                        Verified=True,
                        Fingerprint=hashlib.sha256(f"training:{category_id}:{day}".encode()).hexdigest(),
                        FingerprintVersion=1,
                    )
                )


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
    parser.add_argument("--training", choices=["test", "save"], help="Exercise model training instead of clustering.")
    parser.add_argument("--fail-training-save", action="store_true", help="Inject a model serialization failure.")
    args = parser.parse_args()
    if args.smoke_test and args.database:
        parser.error("--smoke-test accepts synthetic inputs only")
    if not 0 <= args.slow_seconds <= 30:
        parser.error("--slow-seconds must be between 0 and 30")
    if args.training and (args.review or args.database):
        parser.error("training acceptance uses synthetic data only and cannot be combined with --review")
    if args.fail_training_save and args.training != "save":
        parser.error("--fail-training-save requires --training save")
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
            if args.training:
                _seed_training(Session)
            else:
                _seed(Session)
        baseline = None
        if args.training:
            from parsetrail.core import learn
            from parsetrail.core.dashboard import DashboardQueryService
            from parsetrail.core.training import train_from_database

            training_service = DashboardQueryService(Session)
            settings.model_path.parent.mkdir(parents=True, exist_ok=True)
            prepared = train_from_database(training_service, settings.model_path, None)
            try:
                learn.publish_prepared_model(prepared)
            finally:
                learn.discard_prepared_model(prepared)
            baseline = settings.model_path.read_bytes()
            if args.slow_seconds:
                fit = learn.Pipeline.fit

                def slow_fit(pipeline, *fit_args, **fit_kwargs):
                    time.sleep(args.slow_seconds)
                    return fit(pipeline, *fit_args, **fit_kwargs)

                stack.enter_context(patch.object(learn.Pipeline, "fit", slow_fit))
            if args.fail_training_save:

                def partial_write_then_fail(_bundle, stream):
                    stream.write(b"incomplete candidate")
                    raise OSError("Synthetic serialization failure")

                stack.enter_context(patch.object(learn.joblib, "dump", partial_write_then_fail))
        elif args.slow_seconds:
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
        if args.training:
            from parsetrail.gui.training import ModelTrainingDialog

            window = ModelTrainingDialog(training_service, settings.model_path if args.training == "save" else None)
        elif args.review:
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
        title = "LOCAL ANALYSIS ACCEPTANCE — DISPOSABLE COPY — " + window.windowTitle()
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
        print(
            "Local analysis acceptance: disposable profile, network disabled, original database unchanged.", flush=True
        )
        print("Closing this process removes the temporary database and profile.", flush=True)

        def wait_for_analysis():
            deadline = time.monotonic() + 40
            while window.analysis_job.busy and time.monotonic() < deadline:
                QTest.qWait(5)
            if window.analysis_job.busy:
                raise RuntimeError("Acceptance analysis did not finish within 40 seconds.")

        try:
            if args.smoke_test:
                if args.training:
                    window.start_training()
                    wait_for_analysis()
                    if args.fail_training_save:
                        assert window.saved_path is None
                        assert "Training failed" in window.status_label.text()
                        assert settings.model_path.read_bytes() == baseline
                    elif args.training == "save":
                        assert window.saved_path == settings.model_path
                        assert learn.load_model(settings.model_path)["meta"]["n_samples"] == 40
                    else:
                        assert window.evaluation is not None
                        assert window.evaluation.accuracy == 1
                        assert settings.model_path.read_bytes() == baseline
                    assert not list(settings.model_path.parent.glob(".*.partial"))
                    print("Training synthetic smoke passed.")
                    return 0
                elif args.review:
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
            result = app.exec()
            if args.training:
                if window.saved_path is None:
                    assert settings.model_path.read_bytes() == baseline
                    print("Previous model preserved: verified byte-for-byte.", flush=True)
                else:
                    learn.load_model(settings.model_path)
                    print("New model saved and reloaded successfully in the disposable profile.", flush=True)
                assert not list(settings.model_path.parent.glob(".*.partial"))
                if window.evaluation is not None:
                    evaluation = window.evaluation
                    learn.plot_confusion_matrix(
                        evaluation.actual,
                        evaluation.predicted,
                        list(evaluation.categories),
                        title=f"Synthetic validation accuracy: {evaluation.accuracy:.1%}",
                    )
            return result
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
