"""Nonposting source facts remain separate from books, conflicts and exports."""

from datetime import date

from openpyxl import load_workbook
from parsetrail.core.v2_loan_history_lines import parse_loan_history
from parsetrail.core.v2_profile_store import FinancialAccount, V2ProfileStore
from parsetrail.core.v2_report_export import write_reviewed_journal_workbook

from devtools.parser_engine_pilot.test_loan_history_lines import DEFINITION as CAPITAL_DEFINITION
from devtools.parser_engine_pilot.test_loan_history_lines import lines as capital_lines
from devtools.parser_engine_pilot.test_wells_loan_lines import DEFINITION as WELLS_DEFINITION
from devtools.parser_engine_pilot.test_wells_loan_lines import parse as wells_source

JAN, FEB = date(2026, 1, 1), date(2026, 2, 1)


def _profile(path):
    capital = parse_loan_history(CAPITAL_DEFINITION, capital_lines())
    wells = wells_source()
    with V2ProfileStore.create(path) as store:
        for account_id, name, source, definition, evidence in (
            ("capital", "Capital One loan", b"%PDF-synthetic", CAPITAL_DEFINITION, capital),
            ("wells", "Wells Fargo loan", b"%PDF-synthetic-loan", WELLS_DEFINITION, wells),
        ):
            store.import_source(source, definition, evidence, suffix=".pdf")
            store.add_financial_account(
                FinancialAccount(
                    account_id,
                    name,
                    "liability",
                    "synthetic",
                    tracking_scope="principal_component",
                )
            )
            section = evidence.payload.accounts[0]
            store.bind_source_account(
                evidence.source_sha256,
                section.source_identity,
                section.source_identity_form,
                account_id,
            )
    return capital, wells


def _record_source(store, account_id, reference="Reviewed source closing"):
    frame = store.source_dated_value_snapshot(account_id)
    (candidate,) = frame.source_value_candidates
    assert not candidate.blockers
    return store.record_reviewed_source_value(
        account_id,
        candidate.candidate_id,
        expected_candidate_sha256=candidate.version,
        expected_basis_sha256=frame.basis_sha256,
        reference=reference,
        reason="Reviewed source point only",
    )


def test_opposite_loan_sign_rules_preserve_originals_and_never_fill_books(tmp_path):
    profile = tmp_path / "source-points.db"
    capital, wells = _profile(profile)
    with V2ProfileStore.open(profile) as store:
        cap = _record_source(store, "capital")
        wf = _record_source(store, "wells")
        assert cap.amount_minor == -950000 and cap.source_proof.closing.minor == 950000
        assert wf.amount_minor == -8000 and wf.source_proof.closing.minor == -8000
        assert cap.source_proof.sign_rule == "positive-owed-negate-1"
        assert wf.source_proof.sign_rule == "debit-signed-1"
        assert cap.source_proof.closing == capital.payload.accounts[0].closing
        assert wf.source_proof.closing == wells.payload.accounts[0].closing
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
        assert store._active_consumed() == {}
        positions = store.account_positions(as_of=date(2026, 1, 31))
        assert positions.activity_rows_without_full_allocation == 3
        assert {point.account_id: point.latest_dated_value.amount_minor for point in positions.accounts} == {
            "capital": -950000,
            "wells": -8000,
        }
        assert all(point.value_status == "known" and point.recorded_debit_minor == 0 for point in positions.accounts)
        assert all(
            point.position_debit_minor is None and point.opening_status == "missing" for point in positions.accounts
        )
        assert all(
            point.latest_dated_value is None for point in store.account_positions(as_of=date(2026, 1, 30)).accounts
        )
        assert store.reviewed_category_summary(kind="expense", start=JAN, end=FEB).total_minor == 0
        assert store.reviewed_category_summary(kind="income", start=JAN, end=FEB).total_minor == 0
        assert store.load_import(capital.source_sha256).evidence == capital
        assert store.load_import(wells.source_sha256).evidence == wells
    backup = V2ProfileStore.snapshot_to(profile, tmp_path / "backup.db")
    with V2ProfileStore.open(backup, read_only=True) as store:
        assert store.account_positions(as_of=date(2026, 1, 31)) == positions


def test_same_date_conflict_and_withdrawal_keep_unknown_zero_and_fresh_retry_distinct(tmp_path):
    profile = tmp_path / "conflict.db"
    _profile(profile)
    with V2ProfileStore.open(profile) as store:
        source = _record_source(store, "capital")
        frame = store.account_anchor_snapshot("capital")
        manual = store.record_reviewed_dated_value(
            "capital",
            amount_minor=-900000,
            value_date=date(2026, 1, 31),
            tracking_scope="principal_component",
            reference="Independent contrary reviewed point",
            reason="Retain explicit unresolved conflict",
            expected_basis_sha256=frame.basis_sha256,
            allow_conflict=True,
        )
        conflict = store.account_anchor_snapshot("capital", as_of=date(2026, 1, 31))
        assert conflict.value_status == "conflict" and conflict.latest_dated_value is None
        assert {point.value_id for point in conflict.conflicting_dated_values} == {source.value_id, manual.value_id}
        position = next(
            point
            for point in store.account_positions(as_of=date(2026, 1, 31)).accounts
            if point.account_id == "capital"
        )
        assert position.value_status == "conflict" and position.position_debit_minor is None
        withdrawal = store.withdraw_reviewed_dated_value(
            "capital",
            manual.value_id,
            expected_value_version=manual.version,
            expected_basis_sha256=conflict.basis_sha256,
            reason="Withdraw unsupported contrary value",
        )
        frame = store.account_anchor_snapshot("capital")
        assert frame.value_status == "known" and frame.latest_dated_value.value_id == source.value_id
        fresh = store.record_reviewed_dated_value(
            "capital",
            amount_minor=0,
            value_date=FEB,
            tracking_scope="principal_component",
            reference="Reviewed later value without settlement evidence",
            reason="Record zero point only",
            expected_basis_sha256=frame.basis_sha256,
        )
        assert (
            store.withdraw_reviewed_dated_value(
                "capital",
                manual.value_id,
                expected_value_version=manual.version,
                expected_basis_sha256=conflict.basis_sha256,
                reason="Withdraw unsupported contrary value",
            )
            == withdrawal
        )
        frame = store.account_anchor_snapshot("capital")
        assert frame.latest_dated_value.value_id == fresh.value_id and frame.latest_dated_value.amount_minor == 0
        assert frame.latest_dated_value.state == "active" and frame.position_debit_minor is None
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
        history = frame.dated_values
    backup = V2ProfileStore.snapshot_to(profile, tmp_path / "conflict-backup.db")
    with V2ProfileStore.open(backup, read_only=True) as store:
        assert store.account_anchor_snapshot("capital").dated_values == history


def test_point_export_retains_raw_proof_and_withdrawal_without_transaction_money(tmp_path):
    profile = tmp_path / "export.db"
    _profile(profile)
    with V2ProfileStore.open(profile) as store:
        value = _record_source(store, "capital", reference="=1+1")
        frame = store.account_anchor_snapshot("capital")
        store.withdraw_reviewed_dated_value(
            "capital",
            value.value_id,
            expected_value_version=value.version,
            expected_basis_sha256=frame.basis_sha256,
            reason="Retain retired source point",
        )
        export = store.reviewed_journal_export(start=JAN, end=FEB)
        assert export.entries == () and len(export.dated_values) == len(export.dated_value_withdrawals) == 1
    before = profile.read_bytes()
    path = write_reviewed_journal_workbook(export, tmp_path / "points.xlsx")
    workbook = load_workbook(path, read_only=False, data_only=False)
    try:
        assert len(list(workbook["Reviewed Entries"].values)) == 1
        assert len(list(workbook["Posting Lines"].values)) == 1
        assert len(list(workbook["Source Allocations"].values)) == 1
        row = list(workbook["Dated Values"].values)[1]
        assert row[4] == "source" and row[6] == "-950000" and row[7] == "withdrawn"
        assert row[8] == "=1+1" and workbook["Dated Values"]["I2"].data_type == "s"
        proof = list(workbook["Source Value Proofs"].values)[1]
        assert proof[10] == "positive-owed-negate-1" and proof[11] == "950000"
        assert proof[13] == "observed" and proof[14] == "2026-01-31"
        assert len(list(workbook["Value Source Locations"].values)) >= 3
        assert len(list(workbook["Dated Value Withdrawals"].values)) == 2
        assert "Nonposting points" in dict(list(workbook["Scope"].values)[1:])["Dated value metadata"]
    finally:
        workbook.close()
    assert profile.read_bytes() == before


def test_positions_show_source_sign_and_conflict_without_promoting_value_to_book_balance(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from parsetrail.gui.v2_account_anchors import V2AccountAnchors
    from parsetrail.gui.v2_reviewed_reports import V2ReviewedReportsDialog
    from PySide6.QtCore import QDate, Qt
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    profile = tmp_path / "positions.db"
    _profile(profile)
    with V2ProfileStore.open(profile) as store:
        _record_source(store, "capital")
    seen = []
    monkeypatch.setattr(
        V2AccountAnchors,
        "exec",
        lambda dialog: seen.append((dialog.profile, dialog.account.currentData(), dialog.tabs.currentIndex())) or 0,
    )
    before = profile.read_bytes()
    dialog = V2ReviewedReportsDialog(profile)
    try:
        dialog.tabs.setCurrentIndex(4)
        dialog.as_of.setDate(QDate(2026, 1, 31))
        index = next(index for index, row in enumerate(dialog.positions_model.rows) if row.account_id == "capital")
        dialog.positions_table.selectRow(index)

        def cell(column):
            return dialog.positions_model.data(dialog.positions_model.index(index, column))

        assert cell(2) == "$0.00" and cell(3) == "Unknown"
        assert "$9,500.00" in cell(12) and "source" in cell(12)
        tooltip = dialog.positions_model.data(dialog.positions_model.index(index, 12), Qt.ToolTipRole)
        assert "Extracted closing $9,500.00" in tooltip and "reviewed debit -$9,500.00" in tooltip
        assert "does not replace the books or establish settlement" in dialog.position_details.text()
        dialog.source_value_button.click()
        assert seen == [(profile, "capital", 3)]
        assert profile.read_bytes() == before
        with V2ProfileStore.open(profile) as store:
            frame = store.account_anchor_snapshot("capital")
            store.record_reviewed_dated_value(
                "capital",
                amount_minor=-900000,
                value_date=date(2026, 1, 31),
                tracking_scope="principal_component",
                reference="Contrary current point",
                reason="Explicit unresolved same-date conflict",
                expected_basis_sha256=frame.basis_sha256,
                allow_conflict=True,
            )
        dialog._refresh_positions()
        assert cell(12) == "Conflicting reviewed values\n2026-01-31"
        assert "No single value is selected" in dialog.position_details.text()
        assert cell(3) == "Unknown" and dialog.source_value_button.isEnabled()
        dialog.as_of.setDate(QDate(2026, 10, 31))
        assert cell(12) == "Conflicting reviewed values\n2026-01-31"
        assert "Conflicting reviewed dated values at 2026-01-31" in dialog.position_details.text()
        changed = profile.read_bytes()

        def refuse(_store, *, as_of):
            from parsetrail.core.v2_profile_store import ProfileFormatError

            assert as_of == date(2026, 10, 31)
            raise ProfileFormatError("synthetic_source_proof_refused")

        monkeypatch.setattr(V2ProfileStore, "account_positions", refuse)
        dialog._refresh_positions()
        assert not dialog.source_value_button.isEnabled() and not dialog.account_anchor_button.isEnabled()
        assert dialog.positions_model.rows == () and dialog.position_details.toolTip() == ""
        assert "unavailable" in dialog.position_details.text()
        assert profile.read_bytes() == changed
    finally:
        dialog.close()
        app.processEvents()


def test_workspace_opens_source_value_tab_and_blocks_both_anchor_routes_during_import(tmp_path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from parsetrail.core.v2_workspace import V2Workspace
    from parsetrail.gui.v2_account_anchors import V2AccountAnchors
    from parsetrail.gui.v2_workspace_window import V2WorkspaceWindow
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    profile = tmp_path / "workspace.db"
    _profile(profile)
    workspace = V2Workspace.open(
        profile, tmp_path / "catalog", trusted_keys={}, preferences_path=tmp_path / "prefs.json"
    )
    opened = []
    monkeypatch.setattr(
        V2AccountAnchors, "exec", lambda dialog: opened.append((dialog.profile, dialog.tabs.currentIndex())) or 0
    )
    window = V2WorkspaceWindow(workspace)
    before = profile.read_bytes()
    try:
        window.source_values_action.trigger()
        assert opened == [(profile, 3)]
        window.import_worker = object()
        window.refresh()
        assert not window.source_values_action.isEnabled() and not window.account_anchors_action.isEnabled()
        window._review_source_values()
        window._review_account_anchors()
        assert opened == [(profile, 3)]
        assert profile.read_bytes() == before
    finally:
        window.import_worker = None
        window.close()
        app.processEvents()
