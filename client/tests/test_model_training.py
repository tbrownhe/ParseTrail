import subprocess
import sys
import threading
import time
from types import SimpleNamespace

import pandas as pd
import pytest
from parsetrail.core import learn
from parsetrail.core.analysis import AnalysisCancelled, AnalysisInputError
from parsetrail.core.settings import SettingsSaveError, settings
from parsetrail.core.training import train_from_database
from parsetrail.gui.main_window import ParseTrail
from parsetrail.gui.training import ModelTrainingDialog
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def frame():
    return pd.DataFrame(
        [
            {"Company": "Synthetic", "AccountType": "Checking", "Description": description, "Category": category}
            for category, description in [("Food", "Grocery market produce"), ("Utilities", "Electric utility energy")]
            for _ in range(20)
        ]
    )


def _service(frame):
    return SimpleNamespace(training_set=lambda: (list(frame.itertuples(index=False, name=None)), list(frame.columns)))


def _wait(predicate):
    deadline = time.monotonic() + 10
    while not predicate() and time.monotonic() < deadline:
        QTest.qWait(2)
    assert predicate(), "training lifecycle timed out"


@pytest.fixture
def prior_model(tmp_path, frame):
    target = tmp_path / "active.mdl"
    learn.train_pipeline_save(frame, target)
    return target, target.read_bytes()


def _unchanged(prior_model):
    target, original = prior_model
    assert target.read_bytes() == original
    assert not list(target.parent.glob(".*.partial"))
    assert learn.load_model(target)["categories"] == ["Food", "Utilities"]


@pytest.mark.parametrize("failure", ["fit", "serialize", "validate", "publish"])
def test_failed_training_never_replaces_previous_model(frame, prior_model, monkeypatch, failure):
    def fail(*_args, **_kwargs):
        raise OSError("injected model failure")

    def partial_dump(_bundle, stream):
        stream.write(b"incomplete candidate")
        raise OSError("injected model failure")

    with monkeypatch.context() as patcher:
        if failure == "fit":
            patcher.setattr(learn.Pipeline, "fit", fail)
        elif failure == "serialize":
            patcher.setattr(learn.joblib, "dump", partial_dump)
        elif failure == "validate":
            patcher.setattr(learn, "load_model", fail)
        else:
            patcher.setattr(learn.os, "replace", fail)
        with pytest.raises(OSError, match="injected"):
            learn.train_pipeline_save(frame, prior_model[0])
    _unchanged(prior_model)


def test_cancel_during_serialization_cleans_candidate_and_preserves_previous_model(frame, prior_model, monkeypatch):
    cancelled = threading.Event()
    original_dump = learn.joblib.dump

    def finish_dump_then_cancel(*args, **kwargs):
        result = original_dump(*args, **kwargs)
        cancelled.set()
        return result

    monkeypatch.setattr(learn.joblib, "dump", finish_dump_then_cancel)
    with pytest.raises(AnalysisCancelled):
        learn.train_pipeline_save(frame, prior_model[0], cancelled=cancelled.is_set)
    _unchanged(prior_model)


def test_prepared_candidate_is_inactive_until_committed_and_predicts_after_reload(frame, prior_model):
    target, original = prior_model
    candidate = train_from_database(_service(frame), target, None)
    assert target.read_bytes() == original
    assert candidate.temporary_path.parent == target.parent
    assert candidate.temporary_path.exists()
    try:
        learn.publish_prepared_model(candidate)
    finally:
        learn.discard_prepared_model(candidate)
    assert not candidate.temporary_path.exists()
    result = learn.predict(target, frame.drop(columns="Category"))
    assert result["Category"].tolist() == frame["Category"].tolist()


@pytest.mark.parametrize("count", [0, 1])
def test_missing_or_single_category_data_gives_actionable_message(frame, prior_model, count):
    subset = frame.iloc[:count]
    with pytest.raises(AnalysisInputError, match="verified|two categories"):
        train_from_database(_service(subset), prior_model[0], None)
    _unchanged(prior_model)


def test_evaluation_stays_headless_and_does_not_save(frame, tmp_path, monkeypatch):
    def no_save(*_args, **_kwargs):
        raise AssertionError("evaluation must not save")

    monkeypatch.setattr(learn, "prepare_model_save", no_save)
    evaluation = train_from_database(_service(frame), None, None)
    assert evaluation.accuracy == 1
    assert len(evaluation.actual) == 12
    assert evaluation.training_count == 28
    assert not list(tmp_path.iterdir())


def test_training_import_has_no_plot_or_qt_dependency():
    code = """
import sys
import parsetrail.core.training
assert 'matplotlib.pyplot' not in sys.modules
assert not any(name.startswith('PySide6') for name in sys.modules)
print('headless training ok')
"""
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode == 0, result.stderr
    assert "headless training ok" in result.stdout


def _dispose(dialog, release=None):
    if release is not None:
        release.set()
    dialog.analysis_job.cancel()
    _wait(lambda: not dialog.analysis_job.busy)
    dialog.close()
    dialog.deleteLater()
    QApplication.processEvents()


@pytest.mark.usefixtures("app")
@pytest.mark.parametrize("action", ["cancel", "escape", "close"])
def test_training_cancel_and_close_keep_gui_responsive_and_previous_model(frame, prior_model, monkeypatch, action):
    entered, release = threading.Event(), threading.Event()
    original_fit = learn.Pipeline.fit
    worker_threads = []

    def blocked_fit(self, *args, **kwargs):
        worker_threads.append(threading.get_ident())
        entered.set()
        assert release.wait(5)
        return original_fit(self, *args, **kwargs)

    monkeypatch.setattr(learn.Pipeline, "fit", blocked_fit)
    dialog = ModelTrainingDialog(_service(frame), prior_model[0])
    ticks = []
    timer = QTimer()
    timer.setInterval(5)
    timer.timeout.connect(lambda: ticks.append(threading.get_ident()))
    try:
        dialog.show()
        _wait(entered.is_set)
        timer.start()
        _wait(lambda: len(ticks) >= 3)
        assert set(ticks) == {threading.get_ident()}
        assert worker_threads[0] != threading.get_ident()
        if action == "cancel":
            dialog.cancel_button.click()
        elif action == "escape":
            QTest.keyClick(dialog, Qt.Key_Escape)
        else:
            dialog.close()
        assert dialog.isVisible()
        assert dialog.analysis_job.busy
        release.set()
        _wait(lambda: not dialog.analysis_job.busy)
        assert dialog.saved_path is None
        assert dialog.isVisible() == (action == "cancel")
        _unchanged(prior_model)
    finally:
        timer.stop()
        _dispose(dialog, release)


@pytest.mark.usefixtures("app")
def test_cancel_after_worker_completion_discards_staged_model(frame, prior_model):
    dialog = ModelTrainingDialog(_service(frame), prior_model[0])
    try:
        dialog.start_training()
        assert dialog.analysis_job._thread.wait(5000)
        assert list(prior_model[0].parent.glob(".*.partial"))
        dialog.cancel_training()  # Completion has not yet been delivered to Qt.
        _wait(lambda: not dialog.analysis_job.busy)
        _unchanged(prior_model)
    finally:
        _dispose(dialog)


@pytest.mark.usefixtures("app")
def test_successful_worker_saves_only_at_gui_commit(frame, prior_model, monkeypatch):
    commits = []
    publish = learn.publish_prepared_model

    def record_commit(candidate):
        commits.append(threading.get_ident())
        assert prior_model[0].read_bytes() == prior_model[1]
        publish(candidate)

    monkeypatch.setattr(learn, "publish_prepared_model", record_commit)
    dialog = ModelTrainingDialog(_service(frame), prior_model[0])
    try:
        dialog.show()
        _wait(lambda: dialog._started and not dialog.analysis_job.busy)
        assert dialog.result() == QDialog.Accepted
        assert dialog.saved_path == prior_model[0]
        assert commits == [threading.get_ident()]
        assert not list(prior_model[0].parent.glob(".*.partial"))
        assert learn.load_model(prior_model[0])["meta"]["n_samples"] == 40
    finally:
        _dispose(dialog)


def test_main_window_evaluation_plot_is_on_gui_thread(app, frame, monkeypatch):
    monkeypatch.setattr(ParseTrail, "initialize_all_elements", lambda self: None)
    monkeypatch.setattr(ParseTrail, "showMaximized", lambda self: None)
    original_hook = sys.excepthook
    window = ParseTrail()
    window.dashboard_service = _service(frame)
    plotted = []
    monkeypatch.setattr(learn, "plot_confusion_matrix", lambda *_args, **_kwargs: plotted.append(threading.get_ident()))
    try:
        window.train_pipeline_test()
        assert plotted == [threading.get_ident()]
    finally:
        sys.excepthook = original_hook
        window.close()
        window.deleteLater()
        app.processEvents()


def test_preference_failure_after_publication_reports_saved_model_and_restores_selection(
    app, frame, tmp_path, monkeypatch
):
    monkeypatch.setattr(ParseTrail, "initialize_all_elements", lambda self: None)
    monkeypatch.setattr(ParseTrail, "showMaximized", lambda self: None)
    original_hook = sys.excepthook
    window = ParseTrail()
    window.dashboard_service = _service(frame)
    target = tmp_path / "new.mdl"
    old_selection = settings.model_path
    warnings = []
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *_args, **_kwargs: (str(target), ""))
    monkeypatch.setattr(QMessageBox, "warning", lambda *_args: warnings.append(_args))

    def fail_preferences(_settings):
        raise SettingsSaveError("injected preference failure")

    monkeypatch.setattr("parsetrail.gui.main_window.save_settings", fail_preferences)
    try:
        window.train_pipeline_save()
        assert settings.model_path == old_selection
        assert learn.load_model(target)["meta"]["n_samples"] == 40
        assert len(warnings) == 1
        assert warnings[0][1] == "Model Saved; Preferences Not Saved"
    finally:
        settings.model_path = old_selection
        sys.excepthook = original_hook
        window.close()
        window.deleteLater()
        app.processEvents()


@pytest.mark.usefixtures("app")
def test_cancel_as_worker_returns_candidate_cleans_it_in_worker(frame, prior_model, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    prepare = learn.prepare_model_save

    def hold_candidate(*args, **kwargs):
        candidate = prepare(*args, **kwargs)
        entered.set()
        assert release.wait(5)
        return candidate

    monkeypatch.setattr(learn, "prepare_model_save", hold_candidate)
    dialog = ModelTrainingDialog(_service(frame), prior_model[0])
    try:
        dialog.show()
        _wait(entered.is_set)
        dialog.cancel_training()
        release.set()
        _wait(lambda: not dialog.analysis_job.busy)
        _unchanged(prior_model)
    finally:
        _dispose(dialog, release)


@pytest.mark.usefixtures("app")
def test_programmatic_shutdown_discards_candidate_waiting_for_gui(frame, prior_model):
    dialog = ModelTrainingDialog(_service(frame), prior_model[0])
    try:
        dialog.start_training()
        assert dialog.analysis_job._thread.wait(5000)
        assert list(prior_model[0].parent.glob(".*.partial"))
        dialog.analysis_job._shutdown()
        _wait(lambda: not dialog.analysis_job.busy)
        _unchanged(prior_model)
    finally:
        _dispose(dialog)


@pytest.mark.usefixtures("app")
def test_gui_commit_failure_cleans_candidate_and_does_not_accept(frame, prior_model, monkeypatch):
    def fail_commit(_candidate):
        raise PermissionError("synthetic rename failure")

    monkeypatch.setattr(learn, "publish_prepared_model", fail_commit)
    dialog = ModelTrainingDialog(_service(frame), prior_model[0])
    try:
        dialog.show()
        _wait(lambda: dialog._started and not dialog.analysis_job.busy)
        assert dialog.saved_path is None
        assert dialog.isVisible()
        assert "previous model is unchanged" in dialog.status_label.text()
        _unchanged(prior_model)
    finally:
        _dispose(dialog)


@pytest.mark.usefixtures("app")
def test_training_query_owns_worker_session_and_uses_only_verified_rows(frame, tmp_path):
    from contextlib import contextmanager
    from datetime import date
    from hashlib import sha256

    from parsetrail.core import orm
    from parsetrail.core.dashboard import DashboardQueryService
    from parsetrail.core.migrate import upgrade_db

    database = tmp_path / "training.db"
    upgrade_db(database)
    Session = orm.create_database(database)
    with Session.begin() as session:
        session.add(orm.AccountTypes(AccountTypeID=1, AccountType="Checking", AssetType="Asset"))
        session.add(orm.Accounts(AccountID=1, AccountName="Synthetic", AccountTypeID=1, Company="Example"))
        session.add_all(
            [
                orm.Categories(CategoryID=1, Name="Food", Type="Expense"),
                orm.Categories(CategoryID=2, Name="Utilities", Type="Expense"),
            ]
        )
        for i, row in enumerate(frame.itertuples(index=False)):
            session.add(
                orm.Transactions(
                    AccountID=1,
                    PostingDate=date(2026, 8, 1),
                    AmountMinor=-1000,
                    BalanceMinor=10000,
                    Description=row.Description,
                    CategoryID=1 if row.Category == "Food" else 2,
                    Verified=i != 0,
                    Fingerprint=sha256(str(i).encode()).hexdigest(),
                    FingerprintVersion=1,
                )
            )
    events = []

    @contextmanager
    def tracked():
        events.append(("open", threading.get_ident()))
        with Session() as session:
            yield session
        events.append(("close", threading.get_ident()))

    target = tmp_path / "trained.mdl"
    dialog = ModelTrainingDialog(DashboardQueryService(tracked), target)
    try:
        dialog.show()
        _wait(lambda: dialog._started and not dialog.analysis_job.busy)
        assert dialog.saved_path == target
        assert learn.load_model(target)["meta"]["n_samples"] == 39
        assert [kind for kind, _thread in events] == ["open", "close"]
        assert events[0][1] == events[1][1] != threading.get_ident()
    finally:
        _dispose(dialog)
        Session.kw["bind"].dispose()
