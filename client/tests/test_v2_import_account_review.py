"""Account-first import uses real Qt events and commits no provisional accounts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from parsetrail.core.v2_data_catalog import key_id_for_public_key
from parsetrail.core.v2_profile_store import FinancialAccount, V2ProfileStore
from parsetrail.core.v2_source_pipeline import build_source_evidence
from parsetrail.core.v2_workspace import V2Workspace
from parsetrail.gui.v2_workspace_window import V2WorkspaceWindow
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox
from scripts.v2_catalog_release import signed_catalog_bytes

from .qt_journey_helpers import JourneyArtifacts, ModalSteps, activate, choose_combo, enter_text, select_file
from .qt_journey_scenarios import prepare_close


@pytest.fixture(autouse=True)
def pickers(qapp):
    previous = qapp.testAttribute(Qt.AA_DontUseNativeDialogs)
    qapp.setAttribute(Qt.AA_DontUseNativeDialogs, True)
    yield
    qapp.setAttribute(Qt.AA_DontUseNativeDialogs, previous)


def workspace(tmp_path, *, ambiguous=False, structure=False, accountless=False, routed=False):
    definitions = tmp_path / "definitions"
    definitions.mkdir()
    base = json.loads(
        (Path(__file__).parents[2] / "devtools/v2_fresh_slice/synthetic-posted-cash-definition.json").read_bytes()
    )
    if accountless:
        base["header"].remove("Account")
        del base["columns"]["account"]
        base["account_key"] = "unknown"
    if structure:
        base["header"].insert(2, "AlternateAccount")
    (definitions / "cash-definition.json").write_text(json.dumps(base), encoding="utf-8")
    if ambiguous or structure or routed:
        alternate = {
            **base,
            "parser_id": "synthetic_alternate",
            "columns": {
                **base["columns"],
                **(
                    {"account": "AlternateAccount"}
                    if structure
                    else {}
                    if routed
                    else {"total": "ReportedBalance", "balance": "Amount"}
                ),
            },
        }
        (definitions / "alternate-definition.json").write_text(json.dumps(alternate), encoding="utf-8")
    if routed:
        (definitions / "account-profiles.json").write_text(
            json.dumps(
                {
                    base["parser_id"]: [
                        {"institution_key": "chase", "product_type": "checking", "tracking_scope": "account_total"}
                    ],
                    "synthetic_alternate": [
                        {"institution_key": "citi", "product_type": "checking", "tracking_scope": "account_total"}
                    ],
                }
            ),
            encoding="utf-8",
        )
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    catalog, signature, _ = signed_catalog_bytes(definitions, private, release_sequence=1, source_revision="a" * 40)
    result = V2Workspace.create(
        tmp_path / "review.db",
        tmp_path / "catalog",
        trusted_keys={key_id_for_public_key(public): public},
        preferences_path=tmp_path / "preferences.json",
    )
    result.catalog_cache.activate(catalog, signature)
    raw = ",".join(base["header"]) + "\n"
    for i in range(7):
        values = {
            "Date": f"10/{i + 1:02d}/2026",
            "Account": "Checking A" if i < 6 else "Savings B",
            "AlternateAccount": "Different account",
            "Description": f"Purchase {i + 1}",
            "Amount": "-$4.00",
            "ReportedBalance": "$996.00",
        }
        raw += ",".join(values[column] for column in base["header"]) + "\n"
    source = tmp_path / "Synthetic-October.csv"
    source.write_text(raw, encoding="utf-8")
    return result, source


def open_import(qtbot, workspace, source, size=(1050, 700)):
    window = V2WorkspaceWindow(workspace)
    qtbot.addWidget(window, before_close_func=lambda widget: prepare_close(qtbot, widget))
    window.resize(*size)
    window.show()
    qtbot.waitUntil(lambda: not window.inventory_pending, timeout=15000)
    modals = ModalSteps(qtbot)
    modals.arm((QFileDialog, lambda dialog: select_file(qtbot, dialog, source)))
    qtbot.mouseClick(window.import_button, Qt.LeftButton)
    modals.finish()
    qtbot.waitUntil(lambda: window.import_preview is not None and window.import_preview.isVisible(), timeout=15000)
    preview = window.import_preview
    preview.resize(*size)
    return window, preview


def assert_task_focus(qtbot, view, target):
    qtbot.waitUntil(lambda: view.focusWidget() is target)
    if QApplication.platformName() == "offscreen":
        # This plugin can leave the already-hidden popup QFrame as activeWindow
        # after delivering the correct logical focus. Restore only the task's
        # activation, then retain the actual focus and typing assertions below.
        activate(qtbot, view)
    qtbot.waitUntil(target.hasFocus)


def create(qtbot, view, name, product="checking", institution=None):
    choose_combo(
        qtbot, view.account_choice, view.account_choice.itemData(view.account_choice.findText("Create a new account…"))
    )
    assert_task_focus(qtbot, view, view.name)
    qtbot.keyClick(view.name, Qt.Key_A, Qt.ControlModifier)
    qtbot.keyClicks(view.name, name)
    choose_combo(qtbot, view.institution, institution)
    profile = next(
        view.product.itemData(i)
        for i in range(1, view.product.count())
        if view.product.itemData(i).product_type == product
    )
    choose_combo(qtbot, view.product, profile)


def group(qtbot, view, row):
    index = view.groups.model().index(row, 0)
    qtbot.mouseClick(view.groups.viewport(), Qt.LeftButton, pos=view.groups.visualRect(index).center())


@pytest.mark.parametrize("size", [(1050, 700), (1280, 800)], ids=["1050x700", "1280x800"])
def test_all_groups_account_first_back_preserves_drafts_final_import_assigns_without_posting(
    qtbot, qapp, tmp_path, journey_artifacts, size
):
    model, source = workspace(tmp_path)
    window, view = open_import(qtbot, model, source, size)
    artifacts = JourneyArtifacts(journey_artifacts, qapp, size)
    assert_task_focus(qtbot, view, view.account_choice)
    assert view.groups.rowCount() == 2  # Savings appears only after the five-row preview.
    assert view.groups.item(1, 0).text() == "Savings B"
    assert view.account_choice.choice() is None and not view.next_button.isEnabled()
    artifacts.capture("01-all-source-groups-require-account-choice", view)
    create(qtbot, view, "Everyday checking")
    assert not view.next_button.isEnabled()
    group(qtbot, view, 1)
    create(qtbot, view, "Rainy day savings", "savings")
    assert view.next_button.isEnabled()
    with V2ProfileStore.open(model.profile_path, read_only=True) as store:
        assert not store.financial_accounts() and not store.source_ids()
    artifacts.capture("02-two-new-accounts-are-only-drafts", view)
    qtbot.mouseClick(view.next_button, Qt.LeftButton)
    assert view.pages.currentIndex() == 1 and not view.preview.format_selector.isVisible()
    assert_task_focus(qtbot, view, view.import_button)
    assert "Review import" in view.step_label.text()
    assert view.preview.rows.rowCount() == 5 and view.preview.rows.item(0, 3).text() == "-$4.00"
    assert "7 activity rows" in view.preview.interpretation.text()
    assert (
        "Everyday checking" in view.assignment_summary.toPlainText()
        and "Rainy day savings" in view.assignment_summary.toPlainText()
    )
    artifacts.capture("03-single-interpretation-exact-assignment-confirmation", view)
    qtbot.mouseClick(view.back_button, Qt.LeftButton)
    group(qtbot, view, 0)
    assert view.name.text() == "Everyday checking" and view.product.currentData().product_type == "checking"
    group(qtbot, view, 1)
    assert view.name.text() == "Rainy day savings"
    qtbot.mouseClick(view.next_button, Qt.LeftButton)
    qtbot.mouseClick(view.import_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: window.import_worker is None and not window.inventory_pending, timeout=15000)
    with V2ProfileStore.open(model.profile_path, read_only=True) as store:
        accounts = {account.name: account for account in store.financial_accounts()}
        assert {account.product_type for account in accounts.values()} == {"checking", "savings"}
        saved = store.load_import(store.source_ids()[0])
        assert saved.source == source.read_bytes()
        bindings = store.source_account_bindings(saved.evidence.source_sha256)
        assert {binding.ledger_account_id for binding in bindings} == {account.id for account in accounts.values()}
        assert store.connection.execute("SELECT COUNT(*) FROM JournalEntries").fetchone() == (0,)


def test_matching_csv_header_does_not_select_existing_and_create_new_skip_has_no_orphans(qtbot, tmp_path):
    model, source = workspace(tmp_path)
    with V2ProfileStore.open(model.profile_path) as store:
        store.add_financial_account(FinancialAccount("existing", "Checking A", "asset", None, product_type="checking"))
    window, view = open_import(qtbot, model, source)
    assert view.account_choice.choice() is None
    assert view.account_choice.findData("existing") >= 0 and view.account_choice.findText("Create a new account…") > 0
    create(qtbot, view, "Another checking")
    qtbot.mouseClick(view.skip_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: window.import_worker is None and not window.inventory_pending, timeout=15000)
    with V2ProfileStore.open(model.profile_path, read_only=True) as store:
        assert [account.id for account in store.financial_accounts()] == ["existing"]
        assert not store.source_ids()


def test_unresolved_same_header_formats_are_blocked_without_column_choices_and_keep_drafts(
    qtbot, qapp, tmp_path, journey_artifacts
):
    model, source = workspace(tmp_path, ambiguous=True, accountless=True)
    window, view = open_import(qtbot, model, source)
    assert view.groups.rowCount() == 1 and "not identified" in view.groups.item(0, 0).text().lower()
    create(qtbot, view, "My cash account")
    qtbot.mouseClick(view.next_button, Qt.LeftButton)
    assert not view.preview.format_selector.isVisible() and not view.import_button.isEnabled()
    assert view.preview.format_selector.count() == 0 and view.preview.rows.rowCount() == 0
    assert "more than one supported format" in view.status.text()
    assert "Nothing has been imported" in view.preview.interpretation.text()
    assert_task_focus(qtbot, view, view.back_button)
    JourneyArtifacts(journey_artifacts, qapp, (1050, 700)).capture(
        "01-conflicting-declarations-blocked-no-column-choice", view
    )
    qtbot.mouseClick(view.back_button, Qt.LeftButton)
    assert view.name.text() == "My cash account"
    assert_task_focus(qtbot, view, view.account_choice)
    qtbot.mouseClick(view.next_button, Qt.LeftButton)
    assert not view.import_button.isEnabled() and not view.preview.format_selector.isVisible()
    qtbot.mouseClick(view.cancel_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: window.import_worker is None and not window.inventory_pending, timeout=15000)
    with V2ProfileStore.open(model.profile_path, read_only=True) as store:
        assert not store.financial_accounts() and not store.source_ids()


def test_account_institution_routes_same_header_declared_formats_without_a_format_question(
    qtbot, qapp, tmp_path, journey_artifacts
):
    model, source = workspace(tmp_path, routed=True, accountless=True)
    window, view = open_import(qtbot, model, source)
    assert len(view.review.recognition.candidates) == 2
    create(qtbot, view, "My checking", institution="chase")
    qtbot.mouseClick(view.next_button, Qt.LeftButton)
    assert view.import_button.isEnabled()
    assert_task_focus(qtbot, view, view.import_button)
    assert not view.preview.format_selector.isVisible()
    assert view.preview.format_selector.currentData() == "synthetic_posted_cash_csv"
    assert view.preview.rows.item(0, 3).text() == "-$4.00"
    assert "recognized automatically" in view.preview.format_label.text()
    assert not view.preview.mapping.isVisible()
    JourneyArtifacts(journey_artifacts, qapp, (1050, 700)).capture(
        "01-institution-resolves-declared-format-automatically", view
    )
    qtbot.mouseClick(view.import_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: window.import_worker is None and not window.inventory_pending, timeout=15000)
    with V2ProfileStore.open(model.profile_path, read_only=True) as store:
        assert store.load_import(store.source_ids()[0]).evidence.parser_id == "synthetic_posted_cash_csv"
        assert store.financial_accounts()[0].institution_key == "chase"
        assert store.connection.execute("SELECT COUNT(*) FROM JournalEntries").fetchone() == (0,)


def test_different_declared_account_structures_refuse_before_any_mapping_question(qtbot, tmp_path):
    model, source = workspace(tmp_path, structure=True)
    window = V2WorkspaceWindow(model)
    qtbot.addWidget(window, before_close_func=lambda widget: prepare_close(qtbot, widget))
    window.show()
    qtbot.waitUntil(lambda: not window.inventory_pending, timeout=15000)
    modals = ModalSteps(qtbot)

    def acknowledge(dialog):
        assert "import_account_routing_conflict" in dialog.text()
        qtbot.mouseClick(dialog.button(QMessageBox.Ok), Qt.LeftButton)

    modals.arm((QFileDialog, lambda dialog: select_file(qtbot, dialog, source)), (QMessageBox, acknowledge))
    qtbot.mouseClick(window.import_button, Qt.LeftButton)
    modals.finish()
    qtbot.waitUntil(lambda: window.import_worker is None and not window.inventory_pending, timeout=15000)
    assert window.import_preview is None and window.import_button.isEnabled()
    with V2ProfileStore.open(model.profile_path, read_only=True) as store:
        assert not store.financial_accounts() and not store.source_ids()


def family_workspace(tmp_path, family):
    from devtools.parser_engine_pilot.synthetic_family_sources import family_sources
    from devtools.parser_engine_pilot.test_engine import mohela_download

    definition_name = {
        "yamaha": "yamaha-card-pilot-definition.json",
        "mohela": "mohela-pilot-definition.json",
        "occu": "occu-bank-pilot-definition.json",
    }[family]
    definition = (Path(__file__).parents[2] / "devtools/parser_engine_pilot" / definition_name).read_bytes()
    raw = json.loads(definition)
    content = (
        mohela_download()
        if family == "mohela"
        else next(case.source for case in family_sources() if case.definition_name == definition_name)
    )
    definitions = tmp_path / "definitions"
    definitions.mkdir()
    (definitions / definition_name).write_bytes(definition)
    (definitions / "account-contexts.json").write_text(
        json.dumps(
            {raw["parser_id"]: {"institution_key": family, "kind": "asset" if family == "occu" else "liability"}}
        ),
        encoding="utf-8",
    )
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    catalog, signature, _ = signed_catalog_bytes(definitions, private, release_sequence=1, source_revision="a" * 40)
    model = V2Workspace.create(
        tmp_path / "review.db",
        tmp_path / "catalog",
        trusted_keys={key_id_for_public_key(public): public},
        preferences_path=tmp_path / "preferences.json",
    )
    model.catalog_cache.activate(catalog, signature)
    source = tmp_path / ("Known-document" + raw["suffix"])
    source.write_bytes(content)
    return model, source


@pytest.mark.parametrize("family", ["yamaha", "mohela", "occu"])
def test_reliable_source_defaults_only_identified_product_and_keeps_unknown_product_a_choice(
    qtbot, qapp, tmp_path, journey_artifacts, family
):
    model, source = family_workspace(tmp_path, family)
    window, view = open_import(qtbot, model, source)
    choose_combo(
        qtbot, view.account_choice, view.account_choice.itemData(view.account_choice.findText("Create a new account…"))
    )
    assert not view.institution.isEnabled() and view.institution.currentData() == family
    if family == "occu":
        assert view.product.currentData() is None and view.product.isEnabled()
        assert not view.name.text()
        product = next(
            view.product.itemData(i)
            for i in range(1, view.product.count())
            if view.product.itemData(i).product_type == "checking"
        )
        choose_combo(qtbot, view.product, product)
        assert "your choice" in view.detected.text() and "Identified product" not in view.detected.text()
    else:
        assert view.product.currentData().product_type == "loan" and not view.product.isEnabled()
        assert view.name.text() and "Identified product" in view.detected.text()
    enter_text(qtbot, view.name, "My recognizable account")
    JourneyArtifacts(journey_artifacts, qapp, (1050, 700)).capture("01-source-identified-versus-authored-product", view)
    qtbot.mouseClick(view.cancel_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: window.import_worker is None and not window.inventory_pending, timeout=15000)
    with V2ProfileStore.open(model.profile_path, read_only=True) as store:
        assert not store.source_ids() and not store.financial_accounts()


def test_long_existing_account_is_searchable_without_expanding_dialog(qtbot, qapp, tmp_path, journey_artifacts):
    model, source = workspace(tmp_path)
    name = ("Everyday checking " + "Long recognizable account label " * 6)[:200]
    with V2ProfileStore.open(model.profile_path) as store:
        store.add_financial_account(FinancialAccount("long", name, "asset", "occu", product_type="checking"))
    window, view = open_import(qtbot, model, source)
    choose_combo(qtbot, view.account_choice, "long")
    assert view.width() == 1050 and view.account_choice.toolTip().startswith(name)
    qtbot.keyClick(view.account_choice.lineEdit(), Qt.Key_Return)
    assert view.pages.currentIndex() == 0 and not view.request.decided.is_set()
    group(qtbot, view, 1)
    choose_combo(qtbot, view.account_choice, "long")
    assert_task_focus(qtbot, view, view.account_choice)
    for _ in range(30):
        if view.next_button.hasFocus():
            break
        qtbot.keyClick(QApplication.focusWidget(), Qt.Key_Tab)
    assert_task_focus(qtbot, view, view.next_button)
    qtbot.keyClick(view.next_button, Qt.Key_Return)
    assert name in view.assignment_summary.toPlainText() and view.width() == 1050
    JourneyArtifacts(journey_artifacts, qapp, (1050, 700)).capture(
        "01-long-existing-name-keeps-dialog-width-full-summary", view
    )
    qtbot.mouseClick(view.cancel_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: window.import_worker is None and not window.inventory_pending, timeout=15000)


@pytest.mark.parametrize("drift", ["accounts", "source"])
def test_changed_inputs_represent_same_file_preserving_only_applicable_draft_and_requiring_confirmation(
    qtbot, qapp, tmp_path, journey_artifacts, drift
):
    model, source = workspace(tmp_path, accountless=True)
    window, view = open_import(qtbot, model, source)
    create(qtbot, view, "Keep my nickname")
    qtbot.mouseClick(view.next_button, Qt.LeftButton)
    previous = view.request
    if drift == "accounts":
        with V2ProfileStore.open(model.profile_path) as store:
            store.add_financial_account(
                FinancialAccount("unrelated", "Other saved work", "asset", None, product_type="savings")
            )
    else:
        source.write_bytes(source.read_bytes().replace(b"10/01/2026", b"10/08/2026"))
    qtbot.mouseClick(view.import_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: view.request is not previous and view.pages.currentIndex() == 0, timeout=15000)
    assert view.recovery_notice.isVisible() and "changed" in view.recovery_notice.text()
    assert window.import_preview is view
    if drift == "accounts":
        assert view.account_choice.choice() is not None and view.name.text() == "Keep my nickname"
        assert view.next_button.isEnabled()
    else:
        assert view.account_choice.choice() is None
        choose_combo(
            qtbot,
            view.account_choice,
            view.account_choice.itemData(view.account_choice.findText("Create a new account…")),
        )
        assert view.name.text() == "Keep my nickname"
        assert view.product.currentData() is None and view.institution.currentIndex() == 0
        choose_combo(qtbot, view.institution, None)
        profile = next(
            view.product.itemData(i)
            for i in range(1, view.product.count())
            if view.product.itemData(i).product_type == "checking"
        )
        choose_combo(qtbot, view.product, profile)
    with V2ProfileStore.open(model.profile_path, read_only=True) as store:
        assert not store.source_ids()
        assert len(store.financial_accounts()) == (1 if drift == "accounts" else 0)
    JourneyArtifacts(journey_artifacts, qapp, (1050, 700)).capture(
        "01-refreshed-inputs-retain-draft-require-new-confirmation", view
    )
    qtbot.mouseClick(view.next_button, Qt.LeftButton)
    assert view.preview.format_selector.currentData() == "synthetic_posted_cash_csv" and view.import_button.isEnabled()
    qtbot.mouseClick(view.import_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: window.import_worker is None and not window.inventory_pending, timeout=15000)
    with V2ProfileStore.open(model.profile_path, read_only=True) as store:
        assert len(store.financial_accounts()) == (2 if drift == "accounts" else 1)
        assert store.load_import(store.source_ids()[0]).source == source.read_bytes()
        assert store.connection.execute("SELECT COUNT(*) FROM JournalEntries").fetchone() == (0,)


@pytest.mark.parametrize("change_origin", [False, True], ids=["reuse-for-both", "origin-changes-account"])
def test_provisional_account_reuse_keeps_one_identity_until_last_group_reference(
    qtbot, qapp, tmp_path, journey_artifacts, change_origin
):
    model, source = workspace(tmp_path)
    if change_origin:
        with V2ProfileStore.open(model.profile_path) as store:
            store.add_financial_account(
                FinancialAccount("existing", "Already saved checking", "asset", None, product_type="checking")
            )
    window, view = open_import(qtbot, model, source)
    create(qtbot, view, "One physical account")
    provisional_id = view._states[view._active_group]["new_id"]
    group(qtbot, view, 1)
    index = view.account_choice.findData(provisional_id)
    assert index >= 0 and view.account_choice.itemText(index).startswith("New in this import:")
    choose_combo(qtbot, view.account_choice, provisional_id)
    assert view.name.text() == "One physical account" and view.next_button.isEnabled()
    qtbot.mouseClick(view.next_button, Qt.LeftButton)
    assert "creates 1 new accounts" in view.assignment_summary.toPlainText()
    qtbot.mouseClick(view.back_button, Qt.LeftButton)
    group(qtbot, view, 0)
    if change_origin:
        choose_combo(qtbot, view.account_choice, "existing")
        group(qtbot, view, 1)
        assert view.account_choice.choice() == provisional_id and view.name.text() == "One physical account"
    else:
        assert view.name.text() == "One physical account"
    qtbot.mouseClick(view.next_button, Qt.LeftButton)
    JourneyArtifacts(journey_artifacts, qapp, (1050, 700)).capture(
        "01-provisional-account-reused-without-duplicate-creation", view
    )
    qtbot.mouseClick(view.import_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: window.import_worker is None and not window.inventory_pending, timeout=15000)
    with V2ProfileStore.open(model.profile_path, read_only=True) as store:
        accounts = store.financial_accounts()
        assert len(accounts) == (2 if change_origin else 1)
        assert next(account for account in accounts if account.name == "One physical account").id == provisional_id
        bindings = store.source_account_bindings(store.source_ids()[0])
        assert len(bindings) == 2
        assert {binding.ledger_account_id for binding in bindings} == (
            {provisional_id, "existing"} if change_origin else {provisional_id}
        )
        assert store.connection.execute("SELECT COUNT(*) FROM JournalEntries").fetchone() == (0,)


@pytest.mark.parametrize("family,scope", [("yamaha", "account_total"), ("mohela", "principal_component")])
def test_known_pdf_and_component_csv_complete_interpretation_import_and_assignment_without_ledger_effects(
    qtbot, qapp, tmp_path, journey_artifacts, family, scope
):
    model, source = family_workspace(tmp_path, family)
    original = source.read_bytes()
    definition = next((tmp_path / "definitions").glob("*definition.json")).read_bytes()
    expected = build_source_evidence(original, definition, suffix=source.suffix)
    window, view = open_import(qtbot, model, source)
    choose_combo(
        qtbot, view.account_choice, view.account_choice.itemData(view.account_choice.findText("Create a new account…"))
    )
    enter_text(qtbot, view.name, f"My {family} loan")
    assert view.product.currentData().product_type == "loan" and view.product.currentData().tracking_scope == scope
    groups = len(view.review.groups)
    qtbot.mouseClick(view.next_button, Qt.LeftButton)
    assert view.pages.currentIndex() == 1 and view.import_button.isEnabled()
    assert not view.preview.format_selector.isVisible()
    if family == "yamaha":
        assert "one signed route" in view.preview.format_label.text()
        assert "Statement period:" in view.preview.interpretation.text()
        assert (
            "Column interpretation" not in view.preview.mapping.text()
            and "Date format:" not in view.preview.mapping.text()
        )
        assert "normalized financial direction" in view.preview.mapping.text()
        assert "column" not in view.preview.retained_format_notice.text()
        assert "2026-02-07 (derived)" == view.preview.rows.item(0, 0).text()
        assert "printed" in view.preview.interpretation.text()
        assert "Raw amount:" in view.preview.rows.item(0, 3).toolTip()
    else:
        assert "activity export recognized automatically" in view.preview.format_label.text()
        assert (
            "Declared column mapping:" in view.preview.mapping.text()
            and "Principal component" in view.preview.mapping.text()
        )
        assert "Date format: month/day/year" in view.preview.mapping.text()
    artifacts = JourneyArtifacts(journey_artifacts, qapp, (1050, 700))
    artifacts.capture("01-known-source-complete-interpretation-before-import", view)
    with V2ProfileStore.open(model.profile_path, read_only=True) as store:
        assert not store.financial_accounts() and not store.source_ids()
    qtbot.mouseClick(view.import_button, Qt.LeftButton)
    qtbot.waitUntil(lambda: window.import_worker is None and not window.inventory_pending, timeout=15000)
    artifacts.capture("02-known-source-imported-assigned-no-ledger-posting", window)
    with V2ProfileStore.open(model.profile_path, read_only=True) as store:
        accounts = store.financial_accounts()
        assert len(accounts) == 1
        account = accounts[0]
        assert (account.product_type, account.kind, account.tracking_scope, account.institution_key) == (
            "loan",
            "liability",
            scope,
            family,
        )
        saved = store.load_import(expected.source_sha256)
        assert saved.source == original and saved.evidence == expected
        bindings = store.source_account_bindings(expected.source_sha256)
        assert len(bindings) == groups and all(binding.ledger_account_id == account.id for binding in bindings)
        assert store.connection.execute("SELECT COUNT(*) FROM JournalEntries").fetchone() == (0,)
        assert store.connection.execute("SELECT COUNT(*) FROM OpeningDecisions").fetchone() == (0,)


def test_escape_from_embedded_interpretation_cancels_owner_and_releases_worker_without_orphans(qtbot, tmp_path):
    model, source = workspace(tmp_path, accountless=True)
    window, view = open_import(qtbot, model, source)
    create(qtbot, view, "Only a provisional account")
    qtbot.mouseClick(view.next_button, Qt.LeftButton)
    assert not view.preview.format_selector.view().isVisible()
    index = view.preview.rows.model().index(0, 0)
    qtbot.mouseClick(view.preview.rows.viewport(), Qt.LeftButton, pos=view.preview.rows.visualRect(index).center())
    assert_task_focus(qtbot, view, view.preview.rows)
    qtbot.keyClick(view.preview.rows, Qt.Key_Escape)
    qtbot.waitUntil(lambda: window.import_worker is None and not window.inventory_pending, timeout=15000)
    assert window.import_preview is None and window.import_button.isEnabled()
    with V2ProfileStore.open(model.profile_path, read_only=True) as store:
        assert not store.source_ids() and not store.financial_accounts()
        assert store.connection.execute("SELECT COUNT(*) FROM JournalEntries").fetchone() == (0,)
