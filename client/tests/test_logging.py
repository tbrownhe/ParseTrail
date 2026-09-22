import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("profile", ["default", "staging"])
def test_startup_logging_uses_saved_log_path(tmp_path: Path, profile: str):
    code = """
import json
from pathlib import Path
import sys

from parsetrail.core import profile
root = Path(sys.argv[1])
profile.application_data_dir = lambda *args, **kwargs: root
custom_log = root / 'custom' / 'nested' / 'acceptance.log'
(root / 'config.json').write_text(json.dumps({'log_file': str(custom_log)}))

from parsetrail.core.logging import logger
logger.info('configured log marker')
logger.remove()
assert custom_log.is_file(), 'Configured log file was not created'
assert 'configured log marker' in custom_log.read_text()
assert not (root / 'logs' / 'parsetrail.log').exists(), 'Unexpected default log'
"""
    env = os.environ.copy()
    env.update(
        {"PARSETRAIL_PROFILE": profile, "PARSETRAIL_STAGING_SERVER_URL": "https://api.staging.parsetrail.com/api/v1"}
    )
    result = subprocess.run(
        [sys.executable, "-c", code, str(tmp_path)],
        cwd=Path(__file__).parents[1],
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
