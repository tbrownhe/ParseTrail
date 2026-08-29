from __future__ import annotations

import json
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import call, patch

from public_smoke import SmokeFailure
from release import (
    ReleaseError,
    artifact_inventory,
    atomic_json,
    command_deploy,
    validate_backup_evidence,
    validate_release,
)


def _release() -> dict[str, object]:
    return {
        "schema_version": 1,
        "created_at": "2026-08-28T00:00:00Z",
        "source_commit": "a" * 40,
        "deployable": True,
        "images": {
            "backend": f"example/backend@sha256:{'b' * 64}",
            "frontend": f"example/frontend@sha256:{'c' * 64}",
            "website": f"example/website@sha256:{'d' * 64}",
        },
    }


class ReleaseValidationTests(unittest.TestCase):
    def test_release_requires_immutable_image_digests(self) -> None:
        validate_release(_release())
        invalid = _release()
        invalid["images"]["backend"] = "example/backend:latest"  # type: ignore[index]

        with self.assertRaisesRegex(ReleaseError, "immutable digest"):
            validate_release(invalid)

    def test_backup_evidence_rehashes_the_dump(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            dump = root / "database.dump"
            dump.write_bytes(b"verified backup")
            import hashlib

            evidence = root / "evidence.json"
            evidence.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "verified_at": datetime.now(UTC).isoformat(),
                        "database_dump": str(dump),
                        "database_dump_sha256": hashlib.sha256(dump.read_bytes()).hexdigest(),
                        "database_restore_id": "restore-db-1",
                        "files_restore_id": "restore-files-1",
                        "submission_keys_restore_id": "restore-keys-1",
                    }
                ),
                encoding="utf-8",
            )

            validate_backup_evidence(evidence, 48)
            dump.write_bytes(b"tampered")
            with self.assertRaisesRegex(ReleaseError, "digest"):
                validate_backup_evidence(evidence, 48)

    def test_artifact_inventory_records_manifest_and_signed_hashes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plugin_root = root / "plugins"
            release_root = plugin_root / "releases" / "7"
            release_root.mkdir(parents=True)
            (plugin_root / "current-release.json").write_text(
                '{"schema_version":1,"release_sequence":7}', encoding="utf-8"
            )
            (release_root / "plugin-manifest.json").write_text(
                json.dumps(
                    {
                        "release_sequence": 7,
                        "artifacts": [
                            {
                                "filename": "parser.pyc",
                                "version": "1.0.0",
                                "size": 12,
                                "sha256": "e" * 64,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (release_root / "plugin-manifest.sig").write_bytes(b"s" * 64)

            inventory = artifact_inventory({"PLUGINS_DIR": str(plugin_root)})

            self.assertEqual(inventory["plugins"]["release_sequence"], 7)
            self.assertEqual(inventory["plugins"]["artifacts"][0]["version"], "1.0.0")

    def test_append_only_record_refuses_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "record.json"
            atomic_json(path, {"status": "first"}, exclusive=True)

            with self.assertRaisesRegex(ReleaseError, "append-only"):
                atomic_json(path, {"status": "replacement"}, exclusive=True)

    def test_failed_smoke_reactivates_and_records_previous_release(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repo = root / "repo"
            repo.mkdir()
            state = root / "state"
            pending_dir = state / "pending"
            pending_dir.mkdir(parents=True)
            identifier = "20260828T120000Z-aaaaaaaaaaaa"
            target = _release()
            previous = _release()
            previous["source_commit"] = "f" * 40
            previous["images"] = {
                "backend": f"example/backend@sha256:{'1' * 64}",
                "frontend": f"example/frontend@sha256:{'2' * 64}",
                "website": f"example/website@sha256:{'3' * 64}",
            }
            pending = {
                "deployment_id": identifier,
                "phase": "migrated",
                "release": target,
                "rollback_target": previous,
                "schema_before": "oldrevision",
                "schema_after_migration": "newrevision",
                "migration_policy": "backward-compatible",
                "migration_log_sha256": "9" * 64,
                "backup_evidence": {"verified": True},
            }
            atomic_json(pending_dir / f"{identifier}.json", pending)
            deploy_env = root / "deploy.env"
            deploy_env.write_text("STACK_NAME=parsetrail-test\n", encoding="utf-8")
            smoke_config = root / "smoke.json"
            smoke_config.write_text(
                json.dumps(
                    {
                        "api_base_url": "https://api.example.com/api/v1",
                        "dashboard_url": "https://dashboard.example.com",
                        "website_url": "https://example.com",
                        "username": "smoke@example.com",
                        "password": "test-password",
                    }
                ),
                encoding="utf-8",
            )
            args = SimpleNamespace(
                state_dir=state,
                deployment_id=identifier,
                deploy_env=deploy_env,
                smoke_config=smoke_config,
                compose_file=repo / "docker-compose.yml",
                timeout=180,
            )

            with (
                patch("release.repository_root", return_value=repo),
                patch("release.activate") as activate_mock,
                patch(
                    "release.run_public_smoke",
                    side_effect=[SmokeFailure("injected"), [{"name": "rollback", "status": "passed"}]],
                ),
            ):
                with self.assertRaisesRegex(ReleaseError, "previous immutable images"):
                    command_deploy(args)

            self.assertEqual(
                activate_mock.call_args_list,
                [
                    call(args, {"STACK_NAME": "parsetrail-test"}, target),
                    call(args, {"STACK_NAME": "parsetrail-test"}, previous),
                ],
            )
            self.assertEqual(json.loads((state / "current-release.json").read_text()), previous)
            record = json.loads((state / "records" / f"{identifier}.json").read_text())
            self.assertEqual(record["status"], "failed-rolling-back")
            self.assertEqual(record["rollback_status"], "succeeded")

    def test_normal_prestart_cannot_run_alembic(self) -> None:
        prestart = Path("backend/scripts/prestart.sh").read_text(encoding="utf-8")
        migrate = Path("backend/scripts/migrate.sh").read_text(encoding="utf-8")

        self.assertNotIn("alembic upgrade", prestart)
        self.assertIn("alembic upgrade head", migrate)


if __name__ == "__main__":
    unittest.main()
