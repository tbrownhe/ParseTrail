"""Keep tests isolated from the developer's profile and OS credentials."""

import json
import os
import platform
import re
import tempfile
from importlib.metadata import version
from pathlib import Path
from uuid import uuid4

import pytest

_TEST_PROFILE = tempfile.TemporaryDirectory(prefix="parsetrail-pytest-")
os.environ["HOME"] = _TEST_PROFILE.name
os.environ["USERPROFILE"] = _TEST_PROFILE.name
os.environ["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"


def pytest_addoption(parser):
    group = parser.getgroup("Qt journey verification")
    group.addoption(
        "--journey-native", action="store_true", help="Render journey tests with the platform's native Qt plugin."
    )
    group.addoption(
        "--journey-artifacts",
        help="Keep synthetic journey screenshots and metadata beneath the repository scratch directory.",
    )


@pytest.fixture(scope="session")
def qapp_args(pytestconfig):
    if pytestconfig.getoption("--journey-native"):
        os.environ.pop("QT_QPA_PLATFORM", None)
    else:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    return []


@pytest.fixture
def journey_artifacts(request, tmp_path, qapp):
    from PySide6.QtCore import qVersion
    from PySide6.QtGui import QFont, QFontDatabase, QFontInfo

    font_setup = "platform default"
    if platform.system() == "Windows" and qapp.platformName() == "offscreen" and not QFontDatabase.families():
        font_file = Path(os.environ.get("SystemRoot", "C:/Windows")) / "Fonts" / "segoeui.ttf"
        font_id = QFontDatabase.addApplicationFont(str(font_file))
        families = QFontDatabase.applicationFontFamilies(font_id)
        if not families:
            pytest.fail("Journey screenshots need a readable font; Windows Segoe UI could not be loaded")
        qapp.setFont(QFont(families[0], 9))
        font_setup = "explicit Windows Segoe UI for the otherwise fontless offscreen plugin"
    resolved_font = QFontInfo(qapp.font())
    if not resolved_font.family():
        pytest.fail("Journey screenshots need a resolved application font")

    selected = request.config.getoption("--journey-artifacts")
    if selected:
        root = Path(selected).resolve()
        scratch = Path(__file__).resolve().parents[2] / "scratch"
        if not root.is_relative_to(scratch.resolve()):
            raise pytest.UsageError("--journey-artifacts must be beneath the repository scratch directory")
        name = re.sub(r"[^A-Za-z0-9_-]", "_", request.node.name)
        target = root / name / uuid4().hex[:8]
    else:
        target = tmp_path / "journey-artifacts"
    target.mkdir(parents=True, exist_ok=False)
    native = request.config.getoption("--journey-native")
    if native and qapp.platformName() in {"offscreen", "minimal"}:
        pytest.fail("--journey-native requires a native Qt platform plugin")
    (target / "runtime.json").write_text(
        json.dumps(
            {
                "python": platform.python_version(),
                "system": platform.system(),
                "machine": platform.machine(),
                "qt": qVersion(),
                "pytest": pytest.__version__,
                "pytest_qt": version("pytest-qt"),
                "qt_platform": qapp.platformName(),
                "requested_native": native,
                "font_family": resolved_font.family(),
                "font_point_size": resolved_font.pointSizeF(),
                "font_setup": font_setup,
                "screen_device_pixel_ratio": qapp.primaryScreen().devicePixelRatio(),
                "screen_logical_dpi": qapp.primaryScreen().logicalDotsPerInch(),
                "input": "Qt software-test events",
                "human_acceptance": False,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return target
