from __future__ import annotations

import json
import tarfile
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from staging_restore_drill import (
    STAGING_PROJECT,
    DrillError,
    file_inventory,
    require_staging_database,
    restore_resources,
    validate_inputs,
)


class StagingRestoreDrillTests(unittest.TestCase):
    def test_database_guard_requires_running_digest_pinned_staging_service(self) -> None:
        inspection = [
            {
                "Config": {
                    "Image": f"postgres@sha256:{'a' * 64}",
                    "Labels": {
                        "com.docker.compose.project": STAGING_PROJECT,
                        "com.docker.compose.service": "db",
                    },
                },
                "State": {"Running": True},
            }
        ]
        with patch("staging_restore_drill.run", return_value=json.dumps(inspection)):
            self.assertEqual(require_staging_database("parsetrail-staging-db-1")["State"]["Running"], True)

        inspection[0]["Config"]["Labels"]["com.docker.compose.project"] = "parsetrail"
        with (
            patch("staging_restore_drill.run", return_value=json.dumps(inspection)),
            self.assertRaisesRegex(DrillError, STAGING_PROJECT),
        ):
            require_staging_database("parsetrail-db-1")

    def test_input_guard_requires_exact_staging_paths_and_disposable_names(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            resources = root / "resources"
            drill_root = root / "restore-drill"
            resources.mkdir()
            drill_root.mkdir()
            valid = SimpleNamespace(
                confirm_writers_stopped="YES",
                database_container="parsetrail-staging-db-1",
                target_database_container="parsetrail-staging-restore-drill-db",
                target_database_volume="parsetrail-staging-restore-drill-db-data",
                source_keys_volume="parsetrail_app-keys-data-staging",
                target_keys_volume="parsetrail-staging-restore-drill-keys",
                resources=resources,
                output=drill_root / "20260830",
            )
            with (
                patch("staging_restore_drill.STAGING_RESOURCES", resources.resolve()),
                patch("staging_restore_drill.STAGING_DRILL_ROOT", drill_root.resolve()),
            ):
                validate_inputs(valid)

                valid.confirm_writers_stopped = "NO"
                with self.assertRaisesRegex(DrillError, "confirm-writers"):
                    validate_inputs(valid)
                valid.confirm_writers_stopped = "YES"
                valid.resources = root / "production-resources"
                with self.assertRaisesRegex(DrillError, "resource source"):
                    validate_inputs(valid)

    def test_resource_archive_round_trip_preserves_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source"
            output = root / "output"
            source.mkdir()
            output.mkdir()
            (source / "nested").mkdir()
            (source / "nested" / "artifact.bin").write_bytes(b"signed artifact")
            (source / "empty").mkdir()

            digest, count = restore_resources(source, output)

            self.assertEqual(len(digest), 64)
            self.assertEqual(count, 1)
            self.assertEqual(file_inventory(source), file_inventory(output / "restored-files" / "resources"))
            with tarfile.open(output / "resources.tar.gz", "r:gz") as archive:
                self.assertIn("resources/nested/artifact.bin", archive.getnames())


if __name__ == "__main__":
    unittest.main()
