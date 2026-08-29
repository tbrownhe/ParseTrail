"""Keep tests isolated from the developer's profile and OS credentials."""

import os
import tempfile

_TEST_PROFILE = tempfile.TemporaryDirectory(prefix="parsetrail-pytest-")
os.environ["HOME"] = _TEST_PROFILE.name
os.environ["USERPROFILE"] = _TEST_PROFILE.name
os.environ["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
