from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import call, patch

from reset_staging_submissions import (
    ResetError,
    delete_database_rows,
    invalidate_backup_evidence,
    remove_statement_files,
    replace_dotenv_value,
    reset,
    statement_inventory,
    validate_inputs,
)


class ResetStagingSubmissionsTests(unittest.TestCase):
    def test_backup_evidence_invalidation_is_exact_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            expected = Path(temporary).resolve() / "backup-evidence.json"
            expected.write_text("{}", encoding="utf-8")
            with patch("reset_staging_submissions.STAGING_BACKUP_EVIDENCE", expected):
                self.assertTrue(invalidate_backup_evidence(expected))
                self.assertFalse(invalidate_backup_evidence(expected))
                with self.assertRaisesRegex(ResetError, "may address only"):
                    invalidate_backup_evidence(expected.with_name("other.json"))

    def test_dotenv_replacement_requires_exactly_one_existing_key(self) -> None:
        source = "ENVIRONMENT=staging\nMASTER_KEY=old\nOTHER=value\n"
        self.assertEqual(
            replace_dotenv_value(source, "MASTER_KEY", "new"),
            "ENVIRONMENT=staging\nMASTER_KEY=new\nOTHER=value\n",
        )
        with self.assertRaisesRegex(ResetError, "does not define"):
            replace_dotenv_value(source, "MISSING", "new")
        with self.assertRaisesRegex(ResetError, "more than once"):
            replace_dotenv_value(source + "MASTER_KEY=duplicate\n", "MASTER_KEY", "new")

    def test_statement_deletion_is_flat_exact_and_complete(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            first = root / "one.enc"
            second = root / "two.tmp"
            first.write_bytes(b"ciphertext-one")
            second.write_bytes(b"ciphertext-two")
            with patch("reset_staging_submissions.STAGING_STATEMENTS", root):
                inventory = statement_inventory(root)
                remove_statement_files(root, inventory)
                self.assertEqual(statement_inventory(root), [])

                (root / "nested").mkdir()
                with self.assertRaisesRegex(ResetError, "unsupported entry"):
                    statement_inventory(root)

    def test_database_reset_requires_zero_remaining_rows(self) -> None:
        values = {"POSTGRES_USER": "app", "POSTGRES_DB": "app"}
        with patch("reset_staging_submissions.psql", side_effect=["3", "0"]):
            self.assertEqual(delete_database_rows("db", values), 3)
        with (
            patch("reset_staging_submissions.psql", side_effect=["3", "1"]),
            self.assertRaisesRegex(ResetError, "remain"),
        ):
            delete_database_rows("db", values)

    def test_input_guard_requires_confirmation_bounded_timeout_and_new_state_child(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary).resolve()
            args = SimpleNamespace(
                confirm_abandon_staging_submissions="YES",
                timeout=180,
                evidence=state / "incident/reset.json",
            )
            self.assertEqual(validate_inputs(args, state), args.evidence.resolve())
            args.confirm_abandon_staging_submissions = "NO"
            with self.assertRaisesRegex(ResetError, "confirm-abandon"):
                validate_inputs(args, state)
            args.confirm_abandon_staging_submissions = "YES"
            args.timeout = 10
            with self.assertRaisesRegex(ResetError, "timeout"):
                validate_inputs(args, state)

    def test_reset_attempts_backend_recovery_after_destructive_phase_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            environment = root / ".env"
            statements = root / "statements"
            statements.mkdir()
            environment.write_text("MASTER_KEY=old\n", encoding="utf-8")
            args = SimpleNamespace(
                state_dir=root / "state",
                deploy_env=environment,
                smoke_config=root / "smoke.json",
                production_smoke_config=root / "production-smoke.json",
            )
            deploy = {"ENVIRONMENT": "staging", "STATEMENTS_DIR": str(statements)}
            release = {"source_commit": "a" * 40}
            expected = ResetError("expected reset failure")
            with (
                patch("reset_staging_submissions.current_commit", return_value="b" * 40),
                patch("reset_staging_submissions.validate_inputs", return_value=root / "evidence.json"),
                patch("reset_staging_submissions.deployment_context", return_value=(deploy, {})),
                patch("reset_staging_submissions.load_json", return_value=release),
                patch("reset_staging_submissions.validate_release", return_value=release),
                patch("reset_staging_submissions.validate_staging_artifacts"),
                patch("reset_staging_submissions.SmokeConfig.from_file", return_value=SimpleNamespace()),
                patch("reset_staging_submissions.validate_staging_smoke_credentials"),
                patch("reset_staging_submissions.verify_running_boundaries") as verify,
                patch("reset_staging_submissions.STAGING_STATEMENTS", statements.resolve()),
                patch("reset_staging_submissions.database_container", return_value="db"),
                patch("reset_staging_submissions.compose_command", return_value=["docker", "compose"]),
                patch("reset_staging_submissions.run"),
                patch("reset_staging_submissions.delete_database_rows", side_effect=expected),
                patch("reset_staging_submissions.activate") as activate,
                self.assertRaisesRegex(ResetError, "expected reset failure"),
            ):
                reset(args)

            self.assertEqual(verify.call_args_list, [call(args, deploy, release), call(args, deploy, release)])
            activate.assert_called_once_with(args, deploy, release)


if __name__ == "__main__":
    unittest.main()
