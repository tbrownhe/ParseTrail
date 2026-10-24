"""Signed context and the global toggle resolve only unique, eligible identities."""

from __future__ import annotations

import json
import os
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from parsetrail.core.v2_account_matching import LedgerAccountCandidate, match_verified_source_account
from parsetrail.core.v2_data_catalog import key_id_for_public_key
from parsetrail.core.v2_preferences import V2Preferences, load_preferences
from parsetrail.core.v2_profile_store import FinancialAccount, V2ProfileStore
from parsetrail.core.v2_synchrony_source_output import from_synchrony_table
from parsetrail.core.v2_workspace import V2Workspace
from scripts.v2_catalog_release import signed_catalog_bytes

from devtools.parser_engine_pilot.test_synchrony_source_output import DEFINITION, SOURCE, channels


def _workspace(tmp_path: Path, *, context: bool = True, kind: str = "liability") -> V2Workspace:
    tmp_path.mkdir(exist_ok=True)
    definitions = tmp_path / "definitions"
    definitions.mkdir()
    (definitions / "card-definition.json").write_bytes(DEFINITION)
    if context:
        (definitions / "account-contexts.json").write_text(
            json.dumps({"synchrony_amazon_store_card": {"institution_key": "synchrony", "kind": kind}})
        )
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    snapshot, signature, _ = signed_catalog_bytes(definitions, private, release_sequence=1, source_revision="a" * 40)
    workspace = V2Workspace.create(
        tmp_path / "fresh.db",
        tmp_path / "catalog",
        trusted_keys={key_id_for_public_key(public): public},
        preferences_path=tmp_path / "preferences.json",
    )
    workspace.catalog_cache.activate(snapshot, signature)
    evidence = from_synchrony_table(DEFINITION, *channels())
    with V2ProfileStore.open(workspace.profile_path) as store:
        store.import_source(SOURCE, DEFINITION, evidence, suffix=".pdf")
        store.add_financial_account(FinancialAccount("card-a", "Card A", "liability", "synchrony", "999991234"))
    return workspace


def test_signed_context_controls_effective_binding_and_explicit_override(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    source_id = workspace.source_ids()[0]
    assert workspace.account_bindings(source_id)[0].ledger_account_id is None
    assert load_preferences(workspace.preferences_path) == V2Preferences()
    workspace.set_allow_abbreviated_account_matching(True)
    assert [(item.ledger_account_id, item.basis) for item in workspace.account_bindings(source_id)] == [
        ("card-a", "automatic")
    ]
    with V2ProfileStore.open(workspace.profile_path) as store:
        store.add_financial_account(FinancialAccount("card-b", "Card B", "liability", "synchrony", "888881234"))
    assert workspace.account_bindings(source_id)[0].ledger_account_id is None
    with V2ProfileStore.open(workspace.profile_path) as store:
        store.bind_source_account(source_id, "1234", "last_four", "card-b")
    assert [(item.ledger_account_id, item.basis) for item in workspace.account_bindings(source_id)] == [
        ("card-b", "source")
    ]
    workspace.set_allow_abbreviated_account_matching(False)
    assert workspace.account_bindings(source_id)[0].ledger_account_id == "card-b"


def test_no_signed_context_or_wrong_class_never_matches(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path, context=False)
    source_id = workspace.source_ids()[0]
    workspace.set_allow_abbreviated_account_matching(True)
    assert workspace.account_bindings(source_id)[0].ledger_account_id is None
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        evidence = store.load_import(source_id).evidence
    catalog = workspace.catalog_cache.load_current()
    match = match_verified_source_account(
        evidence,
        "1234",
        "last_four",
        catalog=catalog,
        candidates=(LedgerAccountCandidate("asset", "synchrony", "asset", "999991234"),),
        preferences=workspace.preferences(),
    )
    assert match.status == "review"
    wrong_class = _workspace(tmp_path / "wrong-class", kind="asset")
    wrong_class.set_allow_abbreviated_account_matching(True)
    assert wrong_class.account_bindings(wrong_class.source_ids()[0])[0].ledger_account_id is None


def test_review_offers_inline_toggle_and_updates_menu(tmp_path: Path) -> None:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from parsetrail.gui.v2_source_account_review import V2SourceAccountReview
    from parsetrail.gui.v2_workspace_window import V2WorkspaceWindow
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    workspace = _workspace(tmp_path)
    window = V2WorkspaceWindow(workspace)
    dialog = V2SourceAccountReview(workspace, workspace.source_ids()[0], window)
    try:
        window.show()
        dialog.show()
        app.processEvents()
        assert dialog.abbreviated_matching_button.isVisible()
        assert not dialog.abbreviated_matching_button.isChecked()
        assert dialog.matches[0].offer_enable_abbreviated_matching
        dialog.abbreviated_matching_button.click()
        assert window.abbreviated_matching_action.isChecked()
        assert dialog.abbreviated_matching_button.isVisible()
        assert dialog.abbreviated_matching_button.isChecked()
        assert dialog.matches[0].status == "automatic"
        assert workspace.account_bindings(workspace.source_ids()[0])[0].basis == "automatic"
        dialog.abbreviated_matching_button.click()
        assert dialog.abbreviated_matching_button.isVisible()
        assert not dialog.abbreviated_matching_button.isChecked()
        assert not window.abbreviated_matching_action.isChecked()
        assert dialog.matches[0].offer_enable_abbreviated_matching
        assert workspace.account_bindings(workspace.source_ids()[0])[0].ledger_account_id is None
    finally:
        dialog.close()
        window.close()
        app.processEvents()
