from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from sanitize_staging import (
    DISABLED_PASSWORD_HASH,
    STAGING_PROJECT,
    SanitizationError,
    inspect_staging_database,
    parse_counts,
    repository_root,
    sanitization_sql,
    validate_inputs,
)


class SanitizeStagingTests(unittest.TestCase):
    def test_requires_explicit_confirmation_and_staging_email(self) -> None:
        with self.assertRaisesRegex(SanitizationError, "confirm-sanitize"):
            validate_inputs("parsetrail-staging-db-1", "operator@staging.parsetrail.com", "NO")
        with self.assertRaisesRegex(SanitizationError, "must end"):
            validate_inputs("parsetrail-staging-db-1", "operator@example.com", "YES")

        self.assertEqual(
            validate_inputs("parsetrail-staging-db-1", "Operator@Staging.ParseTrail.com", "YES"),
            "operator@staging.parsetrail.com",
        )

    def test_requires_running_staging_compose_database(self) -> None:
        inspection = [
            {
                "Id": "container-id",
                "Config": {
                    "Labels": {
                        "com.docker.compose.project": STAGING_PROJECT,
                        "com.docker.compose.service": "db",
                    }
                },
                "State": {"Running": True},
            }
        ]
        with patch("sanitize_staging.run", return_value=json.dumps(inspection)):
            self.assertEqual(inspect_staging_database("parsetrail-staging-db-1")["Id"], "container-id")

        inspection[0]["Config"]["Labels"]["com.docker.compose.project"] = "parsetrail"
        with (
            patch("sanitize_staging.run", return_value=json.dumps(inspection)),
            self.assertRaisesRegex(SanitizationError, STAGING_PROJECT),
        ):
            inspect_staging_database("parsetrail-db-1")

    def test_sql_preserves_ids_but_revokes_copied_identities_and_submissions(self) -> None:
        sql = sanitization_sql("deployment-smoke@staging.parsetrail.com")

        self.assertNotIn('DELETE FROM public."user"', sql)
        self.assertIn('UPDATE public."user"', sql)
        self.assertIn("is_active = false", sql)
        self.assertIn("is_superuser = false", sql)
        self.assertIn("session_version = session_version + 1", sql)
        self.assertIn("password_reset_version = password_reset_version + 1", sql)
        self.assertIn("email_verification_version = email_verification_version + 1", sql)
        self.assertIn(DISABLED_PASSWORD_HASH, sql)
        self.assertIn("DELETE FROM public.statement_uploads", sql)
        self.assertIn("refusing a repeat or late scrub", sql)

    def test_count_parser_is_strict(self) -> None:
        self.assertEqual(parse_counts("3|14", fields=2), (3, 14))
        with self.assertRaisesRegex(SanitizationError, "count shape"):
            parse_counts("3|14|0", fields=2)
        with self.assertRaisesRegex(SanitizationError, "non-numeric"):
            parse_counts("three|14", fields=2)

    def test_repository_root_is_resolved_from_checkout_markers(self) -> None:
        root = repository_root()

        self.assertTrue((root / ".git").exists())
        self.assertTrue((root / "docker-compose.yml").is_file())


if __name__ == "__main__":
    unittest.main()
