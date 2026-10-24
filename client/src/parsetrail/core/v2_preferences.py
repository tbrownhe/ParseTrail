"""Small, separate 2.0 application preferences file; never opens a 1.x profile."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class V2Preferences:
    allow_abbreviated_account_matching: bool = False


def default_preferences_path() -> Path:
    if os.name == "nt":
        root = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))) / "ParseTrail"
    elif sys.platform == "darwin":
        root = Path.home() / "Library" / "Application Support" / "ParseTrail"
    else:
        root = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "parsetrail"
    return root / "v2-preferences.json"


def load_preferences(path: Path) -> V2Preferences:
    if not path.exists():
        return V2Preferences()
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 4096:
        raise ValueError("v2_preferences_shape")
    try:
        raw = json.loads(path.read_bytes())
    except (OSError, UnicodeError, ValueError):
        raise ValueError("v2_preferences_shape") from None
    if (
        type(raw) is not dict
        or set(raw) != {"allow_abbreviated_account_matching"}
        or type(raw["allow_abbreviated_account_matching"]) is not bool
    ):
        raise ValueError("v2_preferences_shape")
    return V2Preferences(raw["allow_abbreviated_account_matching"])


def save_preferences(path: Path, preferences: V2Preferences) -> None:
    if not isinstance(preferences, V2Preferences) or type(preferences.allow_abbreviated_account_matching) is not bool:
        raise ValueError("v2_preferences_shape")
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError("v2_preferences_shape")
    descriptor, name = tempfile.mkstemp(prefix="v2-preferences-", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump({"allow_abbreviated_account_matching": preferences.allow_abbreviated_account_matching}, stream)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)
