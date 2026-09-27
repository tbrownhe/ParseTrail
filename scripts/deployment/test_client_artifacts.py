from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import release


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


class StagingClientCandidateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.values = {}
        for environment in ("staging", "production"):
            root = self.root / environment
            self.values[environment] = {
                "ENVIRONMENT": environment,
                "CLIENTS_DIR": str(root / "clients"),
                "PLUGINS_DIR": str(root / "plugins"),
            }
            for channel in ("plugins", "clients/win64", "clients/macos"):
                prefix = "plugin" if channel == "plugins" else "client"
                directory = root / channel / "releases/7"
                write_json(root / channel / "current-release.json", {"schema_version": 1, "release_sequence": 7})
                write_json(directory / f"{prefix}-manifest.json", {"release_sequence": 7, "artifacts": []})
                (directory / f"{prefix}-manifest.sig").write_bytes(b"legacy-signature")
        self.candidate = {
            "schema_version": 1,
            "version": "1.4.2",
            "source_tag": "client-v1.4.2",
            "source_commit": "a" * 40,
            "targets": {},
            "publication": {},
        }
        self.directories = {}
        for target in release.CLIENT_TARGETS:
            directory = self.root / "staging/clients" / target / "releases/8"
            self.directories[target] = directory
            write_json(directory.parent.parent / "current-release.json", {"schema_version": 1, "release_sequence": 8})
            suffix = "exe" if target == "windows-x86_64" else "dmg"
            installer = f"parsetrail_1.4.2_{target}_setup.{suffix}"
            directory.mkdir(parents=True)
            (directory / installer).write_bytes(b"synthetic installer")
            artifact = {
                "filename": installer,
                "version": "1.4.2",
                "platform": target,
                "architecture": "x86_64",
                "size": 19,
                "sha256": release.sha256_file(directory / installer),
            }
            write_json(
                directory / "client-manifest.json",
                {"schema_version": 2, "release_sequence": 8, "artifacts": [artifact]},
            )
            (directory / "client-manifest.sig").write_bytes(b"synthetic accepted signature")
            inventory = {
                "schema_version": 1,
                "release_kind": "client",
                "target_platform": target,
                "architecture": "x86_64",
                "manifest_schema_version": 2,
                "version": "1.4.2",
                "source_tag": "client-v1.4.2",
                "source_commit": "a" * 40,
                "release_sequence": 8,
                "files": [
                    {
                        "filename": name,
                        "size": (directory / name).stat().st_size,
                        "sha256": release.sha256_file(directory / name),
                    }
                    for name in ("client-manifest.json", "client-manifest.sig", installer)
                ],
            }
            write_json(directory / "release-inventory.json", inventory)
            self.candidate["targets"][target] = {
                "release_sequence": 8,
                "inventory_sha256": release.sha256_file(directory / "release-inventory.json"),
            }

    def validate(self, candidate: dict | None = None) -> dict | None:
        return release.validate_staging_artifacts(self.values["staging"], self.values["production"], candidate)

    def test_inventory_includes_legacy_and_explicit_targets_with_architecture(self) -> None:
        inventory = release.artifact_inventory(self.values["staging"])
        self.assertEqual(set(inventory["clients"]), {"macos", "win64", *release.CLIENT_TARGETS})
        self.assertEqual(inventory["clients"]["macos-x86_64"]["artifacts"][0]["architecture"], "x86_64")

    def test_new_channels_require_explicit_review_and_both_targets(self) -> None:
        with self.assertRaisesRegex(release.ReleaseError, "does not match"):
            self.validate()
        incomplete = copy.deepcopy(self.candidate)
        del incomplete["targets"]["macos-x86_64"]
        with self.assertRaisesRegex(release.ReleaseError, "paired desktop-release"):
            self.validate(incomplete)
        review = self.validate(self.candidate)
        self.assertNotIn("publication", review["client_release"])
        release.recheck_staging_review(self.values["staging"], self.values["production"], review)

    def test_candidate_cannot_relax_plugin_or_legacy_channel_parity(self) -> None:
        for channel in ("plugins", "clients/win64", "clients/macos"):
            with self.subTest(channel=channel):
                prefix = "plugin" if channel == "plugins" else "client"
                signature = self.root / "staging" / channel / "releases/7" / f"{prefix}-manifest.sig"
                old = signature.read_bytes()
                signature.write_bytes(b"changed")
                with self.assertRaisesRegex(release.ReleaseError, "does not match"):
                    self.validate(self.candidate)
                signature.write_bytes(old)

    def test_candidate_rejects_tampered_installer_manifest_signature_and_inventory(self) -> None:
        directory = self.directories["macos-x86_64"]
        for name in (
            "parsetrail_1.4.2_macos-x86_64_setup.dmg",
            "client-manifest.json",
            "client-manifest.sig",
            "release-inventory.json",
        ):
            with self.subTest(name=name):
                path = directory / name
                old = path.read_bytes()
                # Keep JSON parseable so this proves the digest check.
                path.write_bytes(old + b" ")
                with self.assertRaisesRegex(release.ReleaseError, "differs"):
                    self.validate(self.candidate)
                path.write_bytes(old)

    def test_candidate_rejects_identity_and_pointer_drift(self) -> None:
        wrong = copy.deepcopy(self.candidate)
        wrong["source_commit"] = "b" * 40
        with self.assertRaisesRegex(release.ReleaseError, "identity"):
            self.validate(wrong)
        pointer = self.directories["macos-x86_64"].parent.parent / "current-release.json"
        write_json(pointer, {"schema_version": 1, "release_sequence": 7})
        with self.assertRaisesRegex(release.ReleaseError, "reviewed candidate"):
            self.validate(self.candidate)

    def test_candidate_rejects_duplicate_and_traversing_inventory_names(self) -> None:
        directory = self.directories["macos-x86_64"]
        path = directory / "release-inventory.json"
        original = json.loads(path.read_text())
        for name in ("../outside.dmg", "client-manifest.json"):
            inventory = copy.deepcopy(original)
            inventory["files"][2]["filename"] = name
            write_json(path, inventory)
            self.candidate["targets"]["macos-x86_64"]["inventory_sha256"] = release.sha256_file(path)
            with self.assertRaisesRegex(release.ReleaseError, "filenames"):
                self.validate(self.candidate)

    def test_production_drift_after_preflight_stops_pending_deployment(self) -> None:
        review = self.validate(self.candidate)
        # Even a matching plugin change to both environments needs a new review.
        for environment in ("staging", "production"):
            path = self.root / environment / "plugins/releases/7/plugin-manifest.sig"
            path.write_bytes(b"new plugin release")
        state = self.root / "state"
        identifier = "20260927T020000Z-aaaaaaaaaaaa"
        write_json(
            state / f"pending/{identifier}.json", {"deployment_id": identifier, "staging_artifact_review": review}
        )
        args = SimpleNamespace(state_dir=state, deployment_id=identifier)
        with (
            patch("release.repository_root", return_value=self.root / "repo"),
            patch("release.deployment_context", return_value=(self.values["staging"], self.values["production"])),
            self.assertRaisesRegex(release.ReleaseError, "changed after review"),
        ):
            release.load_pending(args)

    def test_missing_review_and_production_candidate_are_rejected(self) -> None:
        with self.assertRaisesRegex(release.ReleaseError, "fresh preflight"):
            release.recheck_staging_review(self.values["staging"], self.values["production"], None)
        with self.assertRaisesRegex(release.ReleaseError, "cannot be used for production"):
            release.validate_staging_artifacts(self.values["production"], None, self.candidate)

    def test_publication_progress_does_not_change_reviewed_identity(self) -> None:
        review = self.validate(self.candidate)
        self.candidate["publication"] = {"staging": {"targets": {"macos-x86_64": "verified"}}}
        self.assertEqual(self.validate(self.candidate), review)


if __name__ == "__main__":
    unittest.main()
