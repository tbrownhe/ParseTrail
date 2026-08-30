from __future__ import annotations

import json
import stat
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import call, patch

from staging_recovery_rehearsal import (
    EXPECTED_MIGRATION_ERROR,
    MISSING_REVISION,
    RecoveryError,
    expect_incompatible_migration,
    inspect_service,
    rehearsal,
    restore_resource_archive,
    validate_inputs,
)


class StagingRecoveryRehearsalTests(unittest.TestCase):
    def test_service_inspection_captures_environment_without_logging_it(self) -> None:
        inspection = [{"Config": {"Env": ["SECRET_KEY=must-not-be-logged"]}}]
        completed = subprocess.CompletedProcess([], 0, stdout=json.dumps(inspection))
        with (
            patch("staging_recovery_rehearsal.BOUNDARY_OVERRIDES", ()),
            patch("staging_recovery_rehearsal.compose_command", return_value=["docker", "compose"]),
            patch("staging_recovery_rehearsal.run", return_value="container-id"),
            patch("staging_recovery_rehearsal.subprocess.run", return_value=completed),
            patch("builtins.print") as output,
        ):
            self.assertEqual(inspect_service(SimpleNamespace(), {}, "backend"), inspection[0])
        output.assert_not_called()

    def test_resource_recovery_preserves_verified_archive_modes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source" / "resources"
            evidence_dir = root / "evidence"
            output = root / "output"
            source.mkdir(parents=True)
            evidence_dir.mkdir()
            output.mkdir()
            (source / "statements").mkdir(mode=0o700)
            artifact = source / "statements" / "statement.enc"
            artifact.write_bytes(b"ciphertext")
            artifact.chmod(0o664)
            with tarfile.open(evidence_dir / "resources.tar.gz", "x:gz") as bundle:
                bundle.add(source, arcname="resources")
            evidence_path = evidence_dir / "restore-evidence.json"
            evidence_path.write_text("{}", encoding="utf-8")

            resources = restore_resource_archive(evidence_path, {"files_restored_count": 1}, output)

            self.assertEqual((resources / "statements" / "statement.enc").read_bytes(), b"ciphertext")
            self.assertEqual(
                stat.S_IMODE((resources / "statements").stat().st_mode),
                stat.S_IMODE((source / "statements").stat().st_mode),
            )
            self.assertEqual(
                stat.S_IMODE((resources / "statements" / "statement.enc").stat().st_mode),
                stat.S_IMODE(artifact.stat().st_mode),
            )

    def test_input_guard_requires_confirmation_new_disposable_volume_and_scoped_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            restore_root = root / "restore-drill"
            recovery_root = root / "recovery-rehearsal"
            restore_root.mkdir()
            recovery_root.mkdir()
            args = SimpleNamespace(
                confirm_staging_recovery="YES",
                restore_evidence=restore_root / "one" / "restore-evidence.json",
                output=recovery_root / "one",
                failure_database_container="parsetrail-staging-recovery-rehearsal-db",
                failure_database_volume="parsetrail-staging-recovery-rehearsal-data",
                timeout=180,
            )
            with (
                patch("staging_recovery_rehearsal.RESTORE_DRILL_ROOT", restore_root.resolve()),
                patch("staging_recovery_rehearsal.RECOVERY_ROOT", recovery_root.resolve()),
                patch("staging_recovery_rehearsal.docker_volume_exists", return_value=False),
                patch("staging_recovery_rehearsal.docker_container_exists", return_value=False),
            ):
                validate_inputs(args)
                args.confirm_staging_recovery = "NO"
                with self.assertRaisesRegex(RecoveryError, "confirm-staging-recovery"):
                    validate_inputs(args)
                args.confirm_staging_recovery = "YES"
                args.failure_database_volume = "staging-data"
                with self.assertRaisesRegex(RecoveryError, "recovery-rehearsal"):
                    validate_inputs(args)

    def test_expected_migration_failure_requires_the_incompatible_revision_error(self) -> None:
        args = SimpleNamespace(timeout=30)
        values = {
            "POSTGRES_VOLUME_NAME": "failed",
            "SUBMISSION_KEYS_VOLUME_NAME": "keys",
            "CLIENTS_DIR": "clients",
            "PLUGINS_DIR": "plugins",
            "STATEMENTS_DIR": "statements",
        }
        release = {"images": {}}
        output = f"FAILED: {EXPECTED_MIGRATION_ERROR} '{MISSING_REVISION}'\n"
        with tempfile.TemporaryDirectory() as temporary:
            log = Path(temporary) / "failure.log"
            with (
                patch("staging_recovery_rehearsal.compose_command", return_value=["docker", "compose"]),
                patch("staging_recovery_rehearsal.compose_env", return_value={}),
                patch("staging_recovery_rehearsal.run"),
                patch("builtins.print"),
                patch(
                    "staging_recovery_rehearsal.subprocess.run",
                    return_value=subprocess.CompletedProcess([], 1, stdout=output),
                ),
            ):
                digest = expect_incompatible_migration(args, values, release, log)
            self.assertEqual(len(digest), 64)
            self.assertEqual(log.read_text(encoding="utf-8"), output)

    def test_rehearsal_restores_original_boundaries_after_recovery_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "output"
            evidence_path = root / "restore-evidence.json"
            args = SimpleNamespace(
                state_dir=root / "state",
                smoke_config=root / "smoke.json",
                production_smoke_config=root / "production-smoke.json",
                failure_database_volume="staging-recovery-rehearsal-data",
                failure_database_container="staging-recovery-rehearsal-db",
                output=output,
            )
            deploy = {
                "ENVIRONMENT": "staging",
                "POSTGRES_IMAGE": f"postgres:17@sha256:{'a' * 64}",
                "POSTGRES_VOLUME_NAME": "original-db",
                "SUBMISSION_KEYS_VOLUME_NAME": "original-keys",
                "CLIENTS_DIR": "original-clients",
                "PLUGINS_DIR": "original-plugins",
                "STATEMENTS_DIR": "original-statements",
                "POSTGRES_USER": "app",
                "POSTGRES_DB": "app",
                "POSTGRES_PASSWORD": "secret",
            }
            release = {
                "source_commit": "b" * 40,
                "images": {"backend": "backend", "frontend": "frontend", "website": "website"},
            }
            restore_evidence = {
                "database_target_volume": "restored-db",
                "submission_keys_target_volume": "restored-keys",
                "database_dump": str(root / "database.dump"),
                "database_public_table_counts": {"public.user": 1},
            }
            recovered = root / "recovered" / "resources"
            smoke = SimpleNamespace()
            production = {
                "POSTGRES_VOLUME_NAME": "production-db",
                "SUBMISSION_KEYS_VOLUME_NAME": "production-keys",
            }
            expected_failure = RecoveryError("expected recovery test failure")
            with (
                patch("staging_recovery_rehearsal.validate_inputs", return_value=(evidence_path, output)),
                patch("staging_recovery_rehearsal.current_commit", return_value="c" * 40),
                patch("staging_recovery_rehearsal.deployment_context", return_value=(deploy, production)),
                patch("staging_recovery_rehearsal.validate_restore_evidence", return_value=restore_evidence),
                patch("staging_recovery_rehearsal.load_json", return_value=release),
                patch("staging_recovery_rehearsal.validate_release", return_value=release),
                patch("staging_recovery_rehearsal.validate_staging_artifacts"),
                patch("staging_recovery_rehearsal.SmokeConfig.from_file", return_value=smoke),
                patch("staging_recovery_rehearsal.validate_staging_smoke_credentials"),
                patch("staging_recovery_rehearsal.verify_key_evidence"),
                patch("staging_recovery_rehearsal.verify_running_boundaries") as verify,
                patch("staging_recovery_rehearsal.restore_resource_archive", return_value=recovered),
                patch("staging_recovery_rehearsal.artifact_inventory", return_value={}),
                patch("staging_recovery_rehearsal.prepare_failed_database"),
                patch("staging_recovery_rehearsal.compose_command", return_value=["docker", "compose"]),
                patch("staging_recovery_rehearsal.run"),
                patch("staging_recovery_rehearsal.expect_incompatible_migration", side_effect=expected_failure),
                patch("staging_recovery_rehearsal.activate") as activate,
                patch("staging_recovery_rehearsal.run_public_smoke", return_value=[]) as public_smoke,
                self.assertRaisesRegex(RecoveryError, "expected recovery test failure"),
            ):
                rehearsal(args)

            self.assertEqual(activate.call_args_list, [call(args, deploy, release)])
            self.assertEqual(verify.call_args_list, [call(args, deploy, release), call(args, deploy, release)])
            public_smoke.assert_called_once_with(smoke)


if __name__ == "__main__":
    unittest.main()
