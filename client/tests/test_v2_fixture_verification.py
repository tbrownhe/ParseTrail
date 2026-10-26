"""The opt-in fixture diagnostic cannot reach normal configuration or trust."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from parsetrail.core import v2_fixture_verification as diagnostic
from parsetrail.core.v2_catalog_admission import admit_pilot_definition
from parsetrail.core.v2_data_catalog import key_id_for_public_key
from parsetrail.core.v2_source_pipeline import build_source_evidence

DEFINITION = (
    Path(__file__).parents[2] / "devtools" / "v2_fresh_slice" / "synthetic-posted-cash-definition.json"
).read_bytes()
SOURCE = b"Date,Account,Description,Amount,ReportedBalance\n10/01/2026,Checking A,Synthetic coffee,-$4.00,$996.00\n"


def manifest_object(*, definition=DEFINITION, source=SOURCE, revision="0" * 40):
    identity = admit_pilot_definition(definition)
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    snapshot = json.dumps(
        {
            "schema_version": 1,
            "engine_contract": 1,
            "release_sequence": 1,
            "source_revision": revision,
            "key_id": key_id_for_public_key(public),
            "definitions": [
                {
                    "parser_id": identity.parser_id,
                    "revision": identity.revision,
                    "suffix": identity.suffix,
                    "size": len(definition),
                    "sha256": hashlib.sha256(definition).hexdigest(),
                    "content_base64": base64.b64encode(definition).decode(),
                }
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    evidence = build_source_evidence(source, definition, suffix=".csv")
    return {
        "schema_version": 1,
        "purpose": "synthetic_fixture_baseline",
        "baseline": {
            "runtime": "source",
            "comparison": "synthetic_evidence_hash_equality_only",
            "source_revision": "fixture_placeholder_not_release",
            "python_version": "3.13.15",
            "platform_system": "Windows",
            "platform_machine": "AMD64",
        },
        "catalog_snapshot_base64": base64.b64encode(snapshot).decode(),
        "catalog_signature_base64": base64.b64encode(key.sign(snapshot)).decode(),
        "public_key_base64": base64.b64encode(public).decode(),
        "fixtures": [
            {
                "fixture_id": "synthetic_cash",
                "parser_id": identity.parser_id,
                "suffix": ".csv",
                "source_base64": base64.b64encode(source).decode(),
                "expected_evidence_sha256": hashlib.sha256(evidence.model_dump_json().encode()).hexdigest(),
            }
        ],
    }


def encoded(raw):
    return json.dumps(raw, sort_keys=True, separators=(",", ":")).encode()


def test_csv_diagnostic_checks_exact_baseline_recovery_and_test_only_trust(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "ordinary-home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "ordinary-home"))
    monkeypatch.setenv("PYTHON_KEYRING_BACKEND", "previous-synthetic-backend")
    previous = {key: os.environ[key] for key in ("HOME", "USERPROFILE", "PYTHON_KEYRING_BACKEND")}
    allocated = []
    original_temporary_directory = diagnostic.tempfile.TemporaryDirectory

    def temporary_directory(*args, **kwargs):
        resource = original_temporary_directory(*args, **kwargs)
        allocated.append(Path(resource.name))
        return resource

    monkeypatch.setattr(diagnostic.tempfile, "TemporaryDirectory", temporary_directory)
    report = diagnostic.run_fixture_verification(encoded(manifest_object()))
    assert report["status"] == "passed" and report["runtime"] == "source"
    assert report["counts"] == {"fixtures": 1, "pdf": 0, "csv": 1, "observations": 1}
    assert all(report["checks"].values())
    assert report["trust"]["production_trust_changed"] is False
    assert report["release_provenance"] == "not_attested" and report["owner_acceptance"] == "not_performed"
    assert report["comparison"] == "supplied_source_runtime_evidence_hash_equality_only"
    assert all(
        report["limits"][key] is False
        for key in ("private_source_parity", "complete_capture", "accounting_acceptance", "installed_acceptance")
    )
    assert "Synthetic coffee" not in json.dumps(report) and str(tmp_path) not in json.dumps(report)
    assert previous == {key: os.environ[key] for key in previous}
    assert not (tmp_path / "ordinary-home").exists()
    assert allocated and not any(path.exists() for path in allocated)


@pytest.mark.parametrize(
    "change",
    [
        lambda raw: raw.update(schema_version=True),
        lambda raw: raw.update(profile_path="private-profile-sentinel.db"),
        lambda raw: raw["fixtures"][0].update(source_path="private-source-sentinel.pdf"),
        lambda raw: raw["fixtures"][0].update(source_base64="not base64"),
        lambda raw: raw["fixtures"][0].update(expected_evidence_sha256="invalid"),
        lambda raw: raw["fixtures"][0].update(suffix=".xlsx"),
        lambda raw: raw["fixtures"][0].update(parser_id="unavailable_parser"),
        lambda raw: raw["baseline"].update(runtime="frozen"),
        lambda raw: raw["fixtures"].append(dict(raw["fixtures"][0])),
    ],
)
def test_manifest_strict_shape_and_duplicate_identities_refuse_before_processing(change):
    raw = manifest_object()
    change(raw)
    with pytest.raises(diagnostic.FixtureVerificationError):
        diagnostic.validate_manifest(encoded(raw))


def test_manifest_duplicate_json_key_wrong_signature_and_release_identity_refuse():
    content = encoded(manifest_object())
    with pytest.raises(diagnostic.FixtureVerificationError, match="manifest_duplicate_key"):
        diagnostic.validate_manifest(content.replace(b'"schema_version":1', b'"schema_version":1,"schema_version":1'))
    raw = manifest_object()
    raw["catalog_signature_base64"] = base64.b64encode(b"x" * 64).decode()
    with pytest.raises(diagnostic.FixtureVerificationError, match="fixture_catalog_rejected"):
        diagnostic.validate_manifest(encoded(raw))
    with pytest.raises(diagnostic.FixtureVerificationError, match="catalog_not_fixture_placeholder"):
        diagnostic.validate_manifest(encoded(manifest_object(revision="a" * 40)))
    raw = manifest_object()
    raw["fixtures"][0]["source_base64"] = "AR=="
    with pytest.raises(diagnostic.FixtureVerificationError, match="manifest_noncanonical_base64"):
        diagnostic.validate_manifest(encoded(raw))


@pytest.mark.parametrize("duplicate", ["fixture_id", "parser_id", "source_base64"])
def test_each_duplicate_identity_is_refused_independently(duplicate):
    raw = manifest_object()
    snapshot = json.loads(base64.b64decode(raw["catalog_snapshot_base64"]))
    alternate = json.loads(DEFINITION)
    alternate["parser_id"] = "synthetic_other_cash_csv"
    alternate_bytes = encoded(alternate)
    snapshot["definitions"].append(
        {
            "parser_id": alternate["parser_id"],
            "revision": alternate["revision"],
            "suffix": ".csv",
            "size": len(alternate_bytes),
            "sha256": hashlib.sha256(alternate_bytes).hexdigest(),
            "content_base64": base64.b64encode(alternate_bytes).decode(),
        }
    )
    snapshot["definitions"].sort(key=lambda entry: entry["parser_id"])
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    snapshot["key_id"] = key_id_for_public_key(public)
    snapshot_bytes = encoded(snapshot)
    raw.update(
        catalog_snapshot_base64=base64.b64encode(snapshot_bytes).decode(),
        catalog_signature_base64=base64.b64encode(key.sign(snapshot_bytes)).decode(),
        public_key_base64=base64.b64encode(public).decode(),
    )
    second = dict(
        raw["fixtures"][0],
        fixture_id="other_fixture",
        parser_id=alternate["parser_id"],
        source_base64=base64.b64encode(SOURCE.replace(b"Synthetic coffee", b"Other coffee")).decode(),
    )
    second[duplicate] = raw["fixtures"][0][duplicate]
    raw["fixtures"].append(second)
    with pytest.raises(diagnostic.FixtureVerificationError, match="manifest_duplicate_identity"):
        diagnostic.validate_manifest(encoded(raw))


def test_signed_catalog_duplicate_revisions_refuse_before_profile_processing(monkeypatch):
    from parsetrail.core.v2_profile_store import V2ProfileStore

    raw = manifest_object()
    snapshot = json.loads(base64.b64decode(raw["catalog_snapshot_base64"]))
    revised = json.loads(DEFINITION)
    revised["revision"] = "2"
    revised_bytes = encoded(revised)
    snapshot["definitions"].append(
        dict(
            snapshot["definitions"][0],
            revision="2",
            size=len(revised_bytes),
            sha256=hashlib.sha256(revised_bytes).hexdigest(),
            content_base64=base64.b64encode(revised_bytes).decode(),
        )
    )
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    snapshot["key_id"] = key_id_for_public_key(public)
    snapshot_bytes = encoded(snapshot)
    raw.update(
        catalog_snapshot_base64=base64.b64encode(snapshot_bytes).decode(),
        catalog_signature_base64=base64.b64encode(key.sign(snapshot_bytes)).decode(),
        public_key_base64=base64.b64encode(public).decode(),
    )

    def forbidden_profile(*_args, **_kwargs):
        raise AssertionError("profile processing must follow complete manifest validation")

    monkeypatch.setattr(V2ProfileStore, "create", forbidden_profile)
    # The current shared verifier already rejects repeated parser IDs. The
    # diagnostic separately checks cardinality before making an identity map.
    with pytest.raises(diagnostic.FixtureVerificationError, match="fixture_catalog_rejected"):
        diagnostic.run_fixture_verification(encoded(raw))


def test_manifest_count_source_and_total_limits_are_finite(monkeypatch):
    raw = manifest_object()
    with pytest.raises(diagnostic.FixtureVerificationError, match="manifest_size"):
        diagnostic.validate_manifest(b"x" * (diagnostic.MAX_MANIFEST_BYTES + 1))
    raw["fixtures"] *= diagnostic.MAX_FIXTURES + 1
    with pytest.raises(diagnostic.FixtureVerificationError, match="manifest_shape"):
        diagnostic.validate_manifest(encoded(raw))
    raw = manifest_object()
    raw["fixtures"][0]["source_base64"] = base64.b64encode(b"x" * (diagnostic.MAX_FIXTURE_BYTES + 1)).decode()
    with pytest.raises(diagnostic.FixtureVerificationError):
        diagnostic.validate_manifest(encoded(raw))
    # Same validation path at a small aggregate budget avoids a multi-MiB fixture.
    monkeypatch.setattr(diagnostic, "MAX_TOTAL_SOURCE_BYTES", len(SOURCE) - 1)
    with pytest.raises(diagnostic.FixtureVerificationError, match="manifest_total_source_size"):
        diagnostic.validate_manifest(encoded(manifest_object()))


def test_cli_failures_are_redacted_and_publish_nothing(tmp_path, capsys):
    manifest = tmp_path / "input.json"
    report = tmp_path / "new-report.json"
    raw = manifest_object()
    raw["fixtures"][0]["expected_evidence_sha256"] = "0" * 64
    manifest.write_bytes(encoded(raw))
    assert diagnostic.main(["--v2-verify-fixtures", str(manifest), "--report", str(report)]) == 2
    assert not report.exists() and not tuple(tmp_path.glob(".parsetrail-fixture-output-*"))
    assert capsys.readouterr().err == "fixture_verification_failed:fixture_baseline_mismatch\n"
    assert diagnostic.main(["--v2-verify-fixtures", str(manifest), "--profile", "private-sentinel"]) == 2
    error = capsys.readouterr().err
    assert error == "fixture_verification_failed:diagnostic_arguments\n" and "private-sentinel" not in error


def test_new_report_publication_never_overwrites_and_cleans_failed_staging(tmp_path, monkeypatch):
    destination = tmp_path / "report.json"
    diagnostic.publish_new_json(destination, b'{"complete":true}\n')
    with pytest.raises(diagnostic.FixtureVerificationError, match="destination_exists"):
        diagnostic.publish_new_json(destination, b"replace")
    assert destination.read_bytes() == b'{"complete":true}\n'
    original_link = os.link

    def competing_link(source, target):
        Path(target).write_bytes(b"competing writer")
        return original_link(source, target)

    monkeypatch.setattr(os, "link", competing_link)
    other = tmp_path / "race.json"
    with pytest.raises(diagnostic.FixtureVerificationError, match="destination_exists"):
        diagnostic.publish_new_json(other, b"diagnostic output")
    assert other.read_bytes() == b"competing writer"
    assert not tuple(tmp_path.glob(".parsetrail-fixture-output-*"))


def test_report_write_failure_and_windowed_stderr_are_bounded(tmp_path, monkeypatch):
    def fail_sync(_descriptor):
        raise OSError("synthetic private filesystem detail")

    monkeypatch.setattr(diagnostic.os, "fsync", fail_sync)
    with pytest.raises(OSError):
        diagnostic.publish_new_json(tmp_path / "failed.json", b"complete")
    assert not (tmp_path / "failed.json").exists()
    assert not tuple(tmp_path.glob(".parsetrail-fixture-output-*"))
    monkeypatch.setattr(sys, "stderr", None)
    assert diagnostic.main([]) == 2


def test_actual_main_dispatch_precedes_legacy_and_gui_bootstrap(tmp_path):
    manifest, report = tmp_path / "input.json", tmp_path / "report.json"
    manifest.write_bytes(encoded(manifest_object()))
    script = """
import sys
import parsetrail.main as entry
code = entry.main()
assert not {'parsetrail.core.profile', 'parsetrail.core.config', 'parsetrail.core.logging', 'parsetrail.gui.main_window', 'PySide6.QtWidgets'} & set(sys.modules)
raise SystemExit(code)
"""
    process = subprocess.run(
        [sys.executable, "-c", script, "--v2-verify-fixtures", str(manifest), "--report", str(report)],
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert process.returncode == 0 and process.stdout == process.stderr == b""
    assert json.loads(report.read_bytes())["counts"]["fixtures"] == 1
    unchanged = report.read_bytes()
    process = subprocess.run(
        [sys.executable, "-m", "parsetrail.main", "--v2-verify-fixtures", str(manifest), "--report", str(report)],
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert process.returncode == 2 and process.stderr.decode().splitlines() == [
        "fixture_verification_failed:destination_exists"
    ]
    assert report.read_bytes() == unchanged


def test_deadline_and_evidence_budget_failure_restore_environment(monkeypatch):
    content = encoded(manifest_object())
    previous = {key: os.environ.get(key) for key in ("HOME", "USERPROFILE", "PYTHON_KEYRING_BACKEND")}
    monkeypatch.setattr(diagnostic, "MAX_RUN_SECONDS", -1)
    with pytest.raises(diagnostic.FixtureVerificationError, match="diagnostic_deadline"):
        diagnostic.run_fixture_verification(content)
    monkeypatch.setattr(diagnostic, "MAX_RUN_SECONDS", 180)
    monkeypatch.setattr(diagnostic, "MAX_TOTAL_EVIDENCE_BYTES", 1)
    with pytest.raises(diagnostic.FixtureVerificationError, match="diagnostic_total_evidence_size"):
        diagnostic.run_fixture_verification(content)
    assert previous == {key: os.environ.get(key) for key in previous}
