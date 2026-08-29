import os
import subprocess
import sys
from pathlib import Path


def test_parse_core_and_batch_adapter_import_without_qt() -> None:
    client_root = Path(__file__).parents[1]
    devtool_dir = client_root.parent / "devtools" / "server_statements"
    code = f"""
import sys

class BlockQt:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "PySide6" or fullname.startswith("PySide6."):
            raise AssertionError(f"headless parsing imported {{fullname}}")
        return None

sys.meta_path.insert(0, BlockQt())
sys.path.insert(0, {str(devtool_dir)!r})
import parsetrail.core.parse
import parsetrail.core.plugin_manager
import batch_plugin_tester
print("headless imports ok")
"""

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=client_root,
        env={**os.environ, "PARSETRAIL_ENV_FILE": ""},
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "headless imports ok" in result.stdout
