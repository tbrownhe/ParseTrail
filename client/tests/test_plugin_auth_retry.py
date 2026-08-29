from __future__ import annotations

from types import SimpleNamespace

from parsetrail.core import plugins as core_plugins
from parsetrail.core.auth import AuthError
from parsetrail.gui import plugins as gui_plugins


class _Signal:
    def __init__(self) -> None:
        self._callbacks = []

    def connect(self, callback) -> None:
        self._callbacks.append(callback)

    def emit(self, *args) -> None:
        for callback in tuple(self._callbacks):
            callback(*args)


class _FakeProgress:
    instances: list[_FakeProgress] = []

    def __init__(self, _label, _cancel, _minimum, maximum, _parent) -> None:
        self._maximum = maximum
        self._cancelled = False
        self.closed = False
        self.shown = False
        self.label = ""
        self.value = 0
        self.canceled = _Signal()
        self.__class__.instances.append(self)

    def setWindowTitle(self, _title) -> None:
        pass

    def setWindowModality(self, _modality) -> None:
        pass

    def setMinimumDuration(self, _duration) -> None:
        pass

    def setMinimumWidth(self, _width) -> None:
        pass

    def setAutoClose(self, _enabled) -> None:
        pass

    def setAutoReset(self, _enabled) -> None:
        pass

    def setRange(self, _minimum, maximum) -> None:
        self._maximum = maximum

    def setLabelText(self, label) -> None:
        self.label = label

    def setValue(self, value) -> None:
        self.value = value

    def maximum(self) -> int:
        return self._maximum

    def wasCanceled(self) -> bool:
        return self._cancelled

    def close(self) -> None:
        self.closed = True

    def show(self) -> None:
        self.shown = True


class _FakeSyncThread:
    instances: list[_FakeSyncThread] = []

    def __init__(
        self,
        local_plugins,
        remote_release,
        *,
        plugin_manager,
        credentials,
        client,
        parent,
    ) -> None:
        self.local_plugins = local_plugins
        self.remote_release = remote_release
        self.plugin_manager = plugin_manager
        self.credentials = credentials
        self.client = client
        self.parent = parent
        self.started = False
        self.cancelled = False
        self.deleted = False
        self.progress_changed = _Signal()
        self.sync_completed = _Signal()
        self.authentication_required = _Signal()
        self.sync_failed = _Signal()
        self.sync_cancelled = _Signal()
        self.finished = _Signal()
        self.__class__.instances.append(self)

    def start(self) -> None:
        self.started = True

    def cancel(self) -> None:
        self.cancelled = True

    def deleteLater(self) -> None:
        self.deleted = True


class _FakeAuth:
    def __init__(self, outcomes) -> None:
        self.outcomes = list(outcomes)
        self.calls = 0

    def credentials_if_needed(self):
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class _FakePluginManager:
    def __init__(self) -> None:
        self.load_calls = 0

    def load_plugins(self) -> None:
        self.load_calls += 1


def _start_sync(monkeypatch, auth_outcomes, *, on_complete=None):
    _FakeProgress.instances.clear()
    _FakeSyncThread.instances.clear()
    information = []
    critical = []
    monkeypatch.setattr(gui_plugins, "QProgressDialog", _FakeProgress)
    monkeypatch.setattr(
        gui_plugins.QMessageBox,
        "information",
        lambda _parent, title, message: information.append((title, message)),
    )
    monkeypatch.setattr(
        gui_plugins.QMessageBox,
        "critical",
        lambda _parent, title, message: critical.append((title, message)),
    )
    auth = _FakeAuth(auth_outcomes)
    client = SimpleNamespace(auth=auth)
    plugin_manager = _FakePluginManager()
    remote_release = SimpleNamespace(manifest=SimpleNamespace(artifacts=(object(), object())))

    initial = gui_plugins.start_plugin_sync(
        object(),
        [{"PLUGIN_NAME": "existing"}],
        remote_release,
        plugin_manager,
        on_complete=on_complete,
        client=client,
        thread_factory=_FakeSyncThread,
    )
    return initial, auth, plugin_manager, information, critical


def test_plugin_sync_worker_reports_authentication_separately(monkeypatch) -> None:
    def reject_authentication(*_args, **_kwargs):
        raise AuthError("saved login rejected")

    monkeypatch.setattr(core_plugins, "sync_plugins", reject_authentication)
    thread = core_plugins.PluginSyncThread(
        [],
        SimpleNamespace(),
        plugin_manager=SimpleNamespace(),
    )
    authentication_errors = []
    generic_errors = []
    thread.authentication_required.connect(authentication_errors.append)
    thread.sync_failed.connect(generic_errors.append)

    thread.run()

    assert authentication_errors == ["saved login rejected"]
    assert generic_errors == []


def test_rejected_saved_credentials_prompt_and_resume_same_plugin_update(monkeypatch) -> None:
    completed = []
    initial, auth, plugin_manager, information, critical = _start_sync(
        monkeypatch,
        [None, ("replacement@example.com", "correct-password")],
        on_complete=lambda: completed.append(True),
    )
    progress = _FakeProgress.instances[0]

    assert initial is _FakeSyncThread.instances[0]
    assert initial.started
    initial.authentication_required.emit("The saved login was rejected. Please sign in again.")

    assert auth.calls == 2
    assert len(_FakeSyncThread.instances) == 2
    retry = _FakeSyncThread.instances[1]
    assert retry.started
    assert retry.local_plugins is initial.local_plugins
    assert retry.remote_release is initial.remote_release
    assert retry.credentials == ("replacement@example.com", "correct-password")
    assert progress._plugin_sync_thread is retry
    assert "Sign in to resume" in progress.label

    retry.sync_completed.emit(object())

    assert progress.closed
    assert plugin_manager.load_calls == 1
    assert completed == [True]
    assert information == []
    assert critical == []


def test_cancelling_replacement_sign_in_cancels_original_update(monkeypatch) -> None:
    initial, auth, plugin_manager, information, critical = _start_sync(
        monkeypatch,
        [None, AuthError("Sign-in was cancelled.")],
    )

    initial.authentication_required.emit("The saved login was rejected. Please sign in again.")

    assert auth.calls == 2
    assert len(_FakeSyncThread.instances) == 1
    assert _FakeProgress.instances[0].closed
    assert plugin_manager.load_calls == 0
    assert information == [("Plugin Update Canceled", "No partial plugin release was activated.")]
    assert critical == []


def test_replacement_credentials_are_not_prompted_repeatedly(monkeypatch) -> None:
    initial, auth, plugin_manager, information, critical = _start_sync(
        monkeypatch,
        [None, ("replacement@example.com", "still-wrong")],
    )

    initial.authentication_required.emit("saved login rejected")
    retry = _FakeSyncThread.instances[1]
    retry.authentication_required.emit("replacement login rejected")

    assert auth.calls == 2
    assert len(_FakeSyncThread.instances) == 2
    assert _FakeProgress.instances[0].closed
    assert plugin_manager.load_calls == 0
    assert information == []
    assert critical == [
        (
            "Plugin Update Failed",
            "Plugin update could not authenticate after signing in:\nreplacement login rejected",
        )
    ]
