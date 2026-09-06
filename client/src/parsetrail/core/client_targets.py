"""Explicit installer identities, separate from experimental source platforms."""

from __future__ import annotations

import platform
import struct

INSTALLER_SUFFIXES = {"windows-x86_64": ".exe", "macos-x86_64": ".dmg"}
TARGET_SYSTEMS = {"windows-x86_64": "Windows", "macos-x86_64": "Darwin"}


def native_installer_target() -> str | None:
    """Return a supported native process target; never guess from pointer width alone."""
    if struct.calcsize("P") != 8:
        return None
    system = platform.system()
    machine = platform.machine().lower()
    if system == "Windows" and machine in {"amd64", "x86_64"}:
        return "windows-x86_64"
    if system == "Darwin" and machine == "x86_64":
        return "macos-x86_64"
    return None
