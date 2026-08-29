from __future__ import annotations

from pathlib import Path

import pytest
from parsetrail.core import client, utils


def test_windows_launch_uses_literal_path_without_shell(monkeypatch, tmp_path: Path) -> None:
    target = tmp_path / "installer & harmless.exe"
    target.touch()
    launched: list[str] = []
    monkeypatch.setattr(utils.sys, "platform", "win32")
    monkeypatch.setattr(utils.os, "startfile", launched.append, raising=False)
    monkeypatch.setattr(
        utils.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("Windows launch must not use subprocess"),
    )

    utils.open_file_in_os(target)

    assert launched == [str(target.resolve())]


@pytest.mark.parametrize(
    ("platform", "launcher"),
    [("darwin", "/usr/bin/open"), ("linux", "xdg-open")],
)
def test_posix_launch_passes_path_as_one_argument(
    monkeypatch,
    tmp_path: Path,
    platform: str,
    launcher: str,
) -> None:
    target = tmp_path / "installer; harmless.dmg"
    target.touch()
    calls: list[tuple[list[str], dict]] = []
    monkeypatch.setattr(utils.sys, "platform", platform)
    monkeypatch.setattr(
        utils.subprocess,
        "run",
        lambda args, **kwargs: calls.append((args, kwargs)),
    )

    utils.open_file_in_os(target)

    assert calls == [([launcher, str(target.resolve())], {"check": True, "shell": False})]


def test_failed_installer_launch_does_not_quit(monkeypatch, tmp_path: Path) -> None:
    installer = tmp_path / "installer.exe"
    installer.touch()
    quit_calls: list[bool] = []
    monkeypatch.setattr(
        client,
        "open_file_in_os",
        lambda _path: (_ for _ in ()).throw(OSError("launch failed")),
    )
    monkeypatch.setattr(client.QApplication, "quit", lambda: quit_calls.append(True))

    with pytest.raises(OSError, match="launch failed"):
        client.quit_and_update(installer)

    assert quit_calls == []
