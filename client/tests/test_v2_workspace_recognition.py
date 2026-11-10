"""Preview decisions hold no database lock and authorize only reviewed inputs."""

import hashlib
import json
import sqlite3
from dataclasses import replace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from parsetrail.core.v2_data_catalog import key_id_for_public_key
from parsetrail.core.v2_profile_store import V2ProfileStore
from parsetrail.core.v2_source_import import CatalogImportError, ImportCancelled
from parsetrail.core.v2_workspace import ImportSkipped, V2Workspace, WorkspaceError
from scripts.v2_catalog_release import signed_catalog_bytes

from .test_v2_workspace import DEFINITION, SOURCE


def workspace_with_choices(tmp_path, *, account_routing=False):
    definitions = tmp_path / "definitions"
    definitions.mkdir()
    first = json.loads(DEFINITION)
    first["parser_id"] = "synthetic_posted_csv"
    second = {**first, "parser_id": "synthetic_activity_csv", "date_role": "activity_date"}
    for item in (first, second):
        (definitions / (item["parser_id"] + "-definition.json")).write_text(json.dumps(item), encoding="utf-8")
    if account_routing:
        # Same headers can describe genuinely different bank export products.
        # The authored product resolves the declared route, never a column pick.
        profiles = {
            item["parser_id"]: [{"institution_key": None, "product_type": product, "tracking_scope": "account_total"}]
            for item, product in ((first, "checking"), (second, "savings"))
        }
        (definitions / "account-profiles.json").write_text(json.dumps(profiles), encoding="utf-8")
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    workspace = V2Workspace.create(
        tmp_path / "fresh.db",
        tmp_path / "catalog",
        trusted_keys={key_id_for_public_key(public): public},
        preferences_path=tmp_path / "preferences.json",
    )

    def activate(sequence, *, install=False):
        snapshot, signature, _ = signed_catalog_bytes(
            definitions,
            private,
            release_sequence=sequence,
            source_revision="b" * 40,
        )
        if install:
            release = tmp_path / f"release-{sequence}"
            release.mkdir()
            (release / "catalog.json").write_bytes(snapshot)
            (release / "catalog.sig").write_bytes(signature)
            return workspace.install_catalog_release(release)
        return workspace.catalog_cache.activate(snapshot, signature)

    activate(1)
    path = tmp_path / "synthetic.csv"
    path.write_bytes(SOURCE)
    return workspace, path, activate


def test_explicit_validated_choice_reparses_without_preview_writes_and_retry_needs_no_choice(tmp_path):
    workspace, path, _ = workspace_with_choices(tmp_path)
    before = workspace.profile_path.read_bytes()
    seen = []

    def choose(selected_path, recognition):
        assert selected_path == path and len(recognition.candidates) == 2
        assert workspace.profile_path.read_bytes() == before
        # An independent immediate writer proves no import write lock is held
        # while the GUI callback waits for a user decision.
        with V2ProfileStore.open(workspace.profile_path) as store:
            store.connection.execute("BEGIN IMMEDIATE")
            store.connection.rollback()
        assert all(item.institution_key is None for item in recognition.candidates)
        seen.append(recognition)
        return recognition.selection("synthetic_activity_csv")

    result = workspace.import_file(path, review_format=choose)
    assert result.evidence.parser_id == "synthetic_activity_csv"
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert store.load_import(result.source_sha256).source == SOURCE
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
    assert (
        workspace.import_file(path, review_format=lambda *_: pytest.fail("Exact retry asked again")).status
        == "already_imported"
    )
    assert len(seen) == 1 and path.read_bytes() == SOURCE


@pytest.mark.parametrize("decision", ["skip", "cancel", "source", "catalog", "token"])
def test_preview_cancel_skip_and_drift_leave_no_source_or_profile_changes(tmp_path, decision):
    workspace, path, activate = workspace_with_choices(tmp_path)
    before = workspace.profile_path.read_bytes()
    cancelled = False

    def choose(_path, recognition):
        nonlocal cancelled
        selected = recognition.selection("synthetic_posted_csv")
        if decision == "skip":
            return None
        if decision == "cancel":
            cancelled = True
            return None
        if decision == "source":
            path.write_bytes(SOURCE.replace(b"Coffee", b"Changed externally"))
        if decision == "catalog":
            activate(2)
        if decision == "token":
            selected = replace(selected, definition_sha256="0" * 64)
        return selected

    error = {
        "skip": ImportSkipped,
        "cancel": ImportCancelled,
        "source": WorkspaceError,
        "catalog": CatalogImportError,
        "token": CatalogImportError,
    }[decision]
    with pytest.raises(error):
        workspace.import_file(path, review_format=choose, cancelled=lambda: cancelled)
    assert workspace.profile_path.read_bytes() == before
    assert workspace.source_ids() == ()


def test_mixed_batch_skips_and_cancels_without_losing_completed_import(tmp_path):
    workspace, first, _ = workspace_with_choices(tmp_path)
    paths = (first, *(tmp_path / f"{index}.csv" for index in range(1, 4)))
    for index, path in enumerate(paths[1:], 1):
        path.write_bytes(SOURCE.replace(b"Coffee", f"Tea {index}".encode()))
    cancelled = False
    decisions = []

    def choose(path, recognition):
        nonlocal cancelled
        decisions.append(path)
        if len(decisions) == 2:
            return None
        if len(decisions) == 3:
            cancelled = True
            return None
        return recognition.selection("synthetic_posted_csv")

    result = workspace.import_files(paths, review_format=choose, cancelled=lambda: cancelled)
    assert [item.status for item in result.files] == ["imported", "skipped", "cancelled", "not_attempted"]
    assert result.cancelled and len(workspace.source_ids()) == 1
    assert result.files[0].source_sha256 == hashlib.sha256(SOURCE).hexdigest()


def test_registry_choices_do_not_write_and_catalog_sync_survives_catalog_removal(tmp_path):
    workspace, _, activate = workspace_with_choices(tmp_path)
    contexts = tmp_path / "definitions" / "account-contexts.json"
    contexts.write_text(
        json.dumps(
            {
                "synthetic_posted_csv": {"institution_key": "sample_credit_union", "kind": "asset"},
            }
        ),
        encoding="utf-8",
    )
    activate(2)
    before = workspace.profile_path.read_bytes()
    assert any(item.id == "sample_credit_union" for item in workspace.institutions())
    assert workspace.profile_path.read_bytes() == before
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert all(item.id != "sample_credit_union" for item in store.institutions())
    workspace.sync_catalog_institutions()
    contexts.unlink()
    activate(3)
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert any(item.id == "sample_credit_union" for item in store.institutions())


def test_institution_conflict_refuses_before_catalog_activation(tmp_path):
    from parsetrail.core.v2_institutions import Institution
    from parsetrail.core.v2_profile_store import ProfileFormatError

    workspace, _, activate = workspace_with_choices(tmp_path)
    with V2ProfileStore.open(workspace.profile_path) as store:
        store.register_institution(Institution("sample_credit_union", "Existing managed name"))
    contexts = tmp_path / "definitions" / "account-contexts.json"
    contexts.write_text(
        json.dumps(
            {
                "synthetic_posted_csv": {"institution_key": "sample_credit_union", "kind": "asset"},
            }
        ),
        encoding="utf-8",
    )
    before = workspace.profile_path.read_bytes()
    with pytest.raises(ProfileFormatError, match="institution_identity_conflict"):
        activate(2, install=True)
    assert workspace.catalog_cache.load_current().release_sequence == 1
    assert workspace.profile_path.read_bytes() == before


def test_catalog_activation_reports_registry_retention_failure_separately(tmp_path, monkeypatch):
    workspace, _, activate = workspace_with_choices(tmp_path)
    original_sync = workspace.sync_catalog_institutions

    def unavailable(_catalog):
        raise sqlite3.OperationalError("synthetic registry busy")

    monkeypatch.setattr(workspace, "sync_catalog_institutions", unavailable)
    result = activate(2, install=True)
    assert result.catalog.release_sequence == 2
    assert result.institution_error_code == "synthetic registry busy"
    assert workspace.catalog_cache.load_current().release_sequence == 2
    monkeypatch.setattr(workspace, "sync_catalog_institutions", original_sync)
    assert workspace.sync_catalog_institutions(result.catalog) == ()
