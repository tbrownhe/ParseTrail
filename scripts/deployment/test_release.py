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
    validate_deployment_boundary,
    validate_release,
    validate_staging_smoke_credentials,
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


def _target_values(environment: str, suffix: str) -> dict[str, str]:
    return {
        "ENVIRONMENT": environment,
        "STACK_NAME": f"parsetrail-{suffix}",
        "POSTGRES_VOLUME_NAME": f"postgres-{suffix}",
        "SUBMISSION_KEYS_VOLUME_NAME": f"keys-{suffix}",
        "CLIENTS_DIR": f"/srv/{suffix}/clients",
        "PLUGINS_DIR": f"/srv/{suffix}/plugins",
        "STATEMENTS_DIR": f"/srv/{suffix}/statements",
        "SECRET_KEY": f"secret-{suffix}",
        "MASTER_KEY": f"master-{suffix}",
        "POSTGRES_PASSWORD": f"postgres-password-{suffix}",
        "FIRST_SUPERUSER_PASSWORD": f"admin-password-{suffix}",
        "DOMAIN": f"{suffix}.example.com",
        "BACKEND_HOST": f"https://api.{suffix}.example.com/api/v1",
        "FRONTEND_HOST": f"https://dashboard.{suffix}.example.com",
        "SMTP_HOST": f"smtp-{suffix}.internal",
        "TRAEFIK_ALLOWED_IP_RANGES": "192.168.1.0/24,100.64.0.0/10",
    }


def _dotenv(values: dict[str, str]) -> str:
    return "".join(f"{name}={value}\n" for name, value in values.items())


class ReleaseValidationTests(unittest.TestCase):
    def test_staging_mail_is_pinned_and_network_isolated(self) -> None:
        application = Path("docker-compose.yml").read_text(encoding="utf-8")
        mail = Path("deployment/staging-mail.compose.yml").read_text(encoding="utf-8")

        self.assertNotIn("env_file:", application)
        self.assertIn("mail:\n    internal: true", application)
        self.assertIn("      - mail\n", application)
        self.assertRegex(mail, r"image: axllent/mailpit:v[0-9.]+@sha256:[0-9a-f]{64}")
        self.assertRegex(mail, r"image: nginx:[0-9.]+-alpine@sha256:[0-9a-f]{64}")
        self.assertIn("external: true", mail)
        self.assertIn("MP_SMTP_ALLOWED_RECIPIENTS", mail)
        self.assertNotIn(":1025:1025", mail)
        self.assertIn("MAILPIT_UI_BIND_ADDRESS", mail)

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

    def test_staging_rejects_every_reused_protected_target(self) -> None:
        production = _target_values("production", "production")
        for field in (
            "STACK_NAME",
            "POSTGRES_VOLUME_NAME",
            "SUBMISSION_KEYS_VOLUME_NAME",
            "CLIENTS_DIR",
            "PLUGINS_DIR",
            "STATEMENTS_DIR",
            "SECRET_KEY",
            "MASTER_KEY",
            "POSTGRES_PASSWORD",
            "FIRST_SUPERUSER_PASSWORD",
            "DOMAIN",
            "BACKEND_HOST",
            "FRONTEND_HOST",
        ):
            with self.subTest(field=field):
                staging = _target_values("staging", "staging")
                staging[field] = production[field]
                with self.assertRaisesRegex(ReleaseError, field):
                    validate_deployment_boundary(
                        staging,
                        state_dir=Path("/srv/staging/state"),
                        production_values=production,
                        production_state_dir=Path("/srv/production/state"),
                    )

    def test_staging_rejects_production_state_and_smtp(self) -> None:
        staging = _target_values("staging", "staging")
        production = _target_values("production", "production")
        with self.assertRaisesRegex(ReleaseError, "release state"):
            validate_deployment_boundary(
                staging,
                state_dir=Path("/srv/shared/state"),
                production_values=production,
                production_state_dir=Path("/srv/shared/state"),
            )

        staging["SMTP_HOST"] = production["SMTP_HOST"]
        with self.assertRaisesRegex(ReleaseError, "SMTP_HOST"):
            validate_deployment_boundary(
                staging,
                state_dir=Path("/srv/staging/state"),
                production_values=production,
                production_state_dir=Path("/srv/production/state"),
            )

    def test_staging_rejects_public_traefik_source_ranges(self) -> None:
        production = _target_values("production", "production")
        for source_range in ("0.0.0.0/0", "::/0", "8.8.8.0/24", "not-a-network"):
            with self.subTest(source_range=source_range):
                staging = _target_values("staging", "staging")
                staging["TRAEFIK_ALLOWED_IP_RANGES"] = source_range
                with self.assertRaisesRegex(ReleaseError, "TRAEFIK_ALLOWED_IP_RANGES"):
                    validate_deployment_boundary(
                        staging,
                        state_dir=Path("/srv/staging/state"),
                        production_values=production,
                        production_state_dir=Path("/srv/production/state"),
                    )

    def test_staging_smoke_credentials_and_urls_are_distinct(self) -> None:
        staging_values = _target_values("staging", "staging")
        with tempfile.TemporaryDirectory() as temporary:
            production_config = Path(temporary) / "production-smoke.json"
            production_config.write_text(
                json.dumps(
                    {
                        "api_base_url": "https://api.production.example.com/api/v1",
                        "dashboard_url": "https://dashboard.production.example.com",
                        "website_url": "https://production.example.com",
                        "username": "production@example.com",
                        "password": "production-password",
                    }
                ),
                encoding="utf-8",
            )
            production_config.chmod(0o600)
            from public_smoke import SmokeConfig

            valid = SmokeConfig(
                api_base_url="https://api.staging.example.com/api/v1",
                dashboard_url="https://dashboard.staging.example.com",
                website_url="https://staging.example.com",
                username="staging@example.com",
                password="staging-password",
            )
            validate_staging_smoke_credentials(staging_values, valid, production_config)

            reused = SmokeConfig(
                api_base_url=valid.api_base_url,
                dashboard_url=valid.dashboard_url,
                website_url=valid.website_url,
                username="production@example.com",
                password=valid.password,
            )
            with self.assertRaisesRegex(ReleaseError, "username"):
                validate_staging_smoke_credentials(staging_values, reused, production_config)

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
            deploy_values = _target_values("production", "test")
            deploy_env.write_text(_dotenv(deploy_values), encoding="utf-8")
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
            smoke_config.chmod(0o600)
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
                    call(args, deploy_values, target),
                    call(args, deploy_values, previous),
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

    def test_postgres_upgrade_volume_root_matches_compose_pgdata_mount(self) -> None:
        compose = Path("docker-compose.yml").read_text(encoding="utf-8")
        upgrade = Path("scripts/postgres/upgrade-12-to-17.sh").read_text(encoding="utf-8")

        mount_target = "/var/lib/postgresql/data/pgdata"
        self.assertIn(f"app-db-data:{mount_target}", compose)
        self.assertIn(f"$target_volume:{mount_target}", upgrade)
        self.assertNotIn('$target_volume:/var/lib/postgresql/data"', upgrade)


if __name__ == "__main__":
    unittest.main()
