"""Disposable synthetic V2 integrated review preparation; no daily profile state."""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path
from uuid import uuid4

REPO = Path(__file__).resolve().parents[2]
SNAPSHOT_PATHS = (REPO / "client/src", REPO / "client", REPO)
sys.path[:0] = [str(component) for component in SNAPSHOT_PATHS]
os.environ["PYTHONPATH"] = os.pathsep.join(str(component) for component in SNAPSHOT_PATHS)
sys.dont_write_bytecode = True
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"


def isolate(root):
    home = root / "isolated-home"
    home.mkdir(exist_ok=True)
    for key, value in {
        "HOME": home,
        "USERPROFILE": home,
        "APPDATA": home / "AppData/Roaming",
        "LOCALAPPDATA": home / "AppData/Local",
    }.items():
        os.environ[key] = str(value)
    os.environ["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"


def workspace_at(root):
    from parsetrail.core.v2_workspace import V2Workspace

    raw = json.loads((root / "demo-public-trust.json").read_text())
    return V2Workspace.open(
        root / "review.db",
        root / "catalog",
        trusted_keys={key: bytes.fromhex(value) for key, value in raw.items()},
        preferences_path=root / "preferences.json",
    )


def prepare(destination: Path | None = None):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from parsetrail.core.v2_data_catalog import key_id_for_public_key
    from parsetrail.core.v2_preferences import V2Preferences, save_preferences
    from parsetrail.core.v2_profile_store import SCHEMA_VERSION, FinancialAccount, V2ProfileStore
    from parsetrail.core.v2_settlements import ExpectedOwnedDestination
    from parsetrail.core.v2_workspace import V2Workspace
    from scripts.v2_catalog_release import signed_catalog_bytes

    from devtools.parser_engine_pilot.synthetic_family_sources import family_sources
    from devtools.v2_review_demo.pin_runtime import pin_runtime

    root = destination or REPO / "scratch" / ("v2-review-" + date.today().strftime("%Y%m%d") + "-" + uuid4().hex[:8])
    root.mkdir(parents=True)
    isolate(root)
    definitions = root / "definitions"
    definitions.mkdir()
    pilot = REPO / "devtools/parser_engine_pilot"
    for path in pilot.glob("*definition.json"):
        (definitions / path.name).write_bytes(path.read_bytes())
    (definitions / "account-contexts.json").write_bytes((pilot / "account-contexts.json").read_bytes())
    cash_definition = REPO / "devtools/v2_fresh_slice/synthetic-posted-cash-definition.json"
    (definitions / cash_definition.name).write_bytes(cash_definition.read_bytes())
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    key_id = key_id_for_public_key(public)
    snapshot, signature, _ = signed_catalog_bytes(definitions, private, release_sequence=1, source_revision="a" * 40)
    (root / "demo-public-trust.json").write_text(json.dumps({key_id: public.hex()}))
    release = root / "test-signed-release"
    release.mkdir()
    (release / "catalog.json").write_bytes(snapshot)
    (release / "catalog.sig").write_bytes(signature)
    workspace = V2Workspace.create(
        root / "review.db", root / "catalog", trusted_keys={key_id: public}, preferences_path=root / "preferences.json"
    )
    save_preferences(root / "preferences.json", V2Preferences())
    workspace.install_catalog_release(release)
    sources = root / "sources"
    sources.mkdir()
    cash = b"Date,Account,Description,Amount,ReportedBalance\n10/01/2026,Checking A,Coffee,-$4.00,$996.00\n10/02/2026,Checking A,Deposit,$10.00,$1006.00\n10/03/2026,Checking A,Tea,-$3.00,$1003.00\n"
    (sources / "Checking-October.csv").write_bytes(cash)
    cash_result = workspace.import_file(sources / "Checking-October.csv")
    hsa_case = next(case for case in family_sources() if case.definition_name == "hsa-cash-pilot-definition.json")
    (sources / "HSA-August.pdf").write_bytes(hsa_case.source)
    hsa_result = workspace.import_file(sources / "HSA-August.pdf")
    card_case = next(case for case in family_sources() if case.definition_name == "recent-citi-pilot-definition.json")
    (sources / "Card-January.pdf").write_bytes(card_case.source)
    card_result = workspace.import_file(sources / "Card-January.pdf")
    extra = b"Date,Account,Description,Amount,ReportedBalance\n10/04/2026,Unbound savings,Gift,$25.00,$25.00\n"
    (sources / "Import-this-next.csv").write_bytes(extra)
    with V2ProfileStore.open(workspace.profile_path) as store:
        for account in (
            FinancialAccount("checking", "Demo checking", "asset", "synthetic"),
            FinancialAccount("savings", "Demo zero savings", "asset", "synthetic"),
            FinancialAccount("hsa", "Demo HSA cash", "asset", "healthequity", tracking_scope="cash_component"),
            FinancialAccount("investment", "Demo investment", "asset", "synthetic"),
            FinancialAccount("card", "Demo card", "liability", "citi", "999991234"),
        ):
            store.add_financial_account(account)
        for ident, name, kind in (
            ("expense:food", "Food", "expense"),
            ("expense:travel", "Travel", "expense"),
            ("income:deposit", "Reviewed deposits", "income"),
            ("income:hsa", "Reviewed HSA income", "income"),
        ):
            store.add_category_account(ident, name, kind)
        store.set_category_budget_rate("expense:food", date(2026, 10, 1), 10000)
        store.bind_source_account(cash_result.source_sha256, "Checking A", "opaque", "checking")
        for account_id, result in (("hsa", hsa_result), ("card", card_result)):
            section = result.evidence.payload.accounts[0]
            store.bind_source_account(
                result.source_sha256, section.source_identity, section.source_identity_form, account_id
            )
        for ident, amount, cutoff in (
            ("checking", 100000, date(2026, 9, 30)),
            ("savings", 0, date(2026, 9, 30)),
            ("card", -10000, date(2025, 12, 31)),
        ):
            frame = store.account_anchor_snapshot(ident)
            store.post_reviewed_manual_opening(
                ident,
                amount_minor=amount,
                cutoff_date=cutoff,
                tracking_scope=frame.account.tracking_scope,
                reference="Public synthetic review fixture opening",
                reason="Seeded explicit demo opening; no imported endpoint claimed",
                expected_decision_version=None,
                expected_basis_sha256=frame.basis_sha256,
            )
        for row, category in (
            (cash_result.evidence.payload.rows[0], "expense:food"),
            (cash_result.evidence.payload.rows[1], "income:deposit"),
        ):
            store.post_reviewed_cash_category(row.row_id, category, reason="Seeded explicit synthetic review")
        store.record_statement_source_review(
            "hsa",
            hsa_result.source_sha256,
            expected_revision_id=None,
            opening_origin="reported",
            closing_origin="reported",
            timing_confirmed=True,
            posting_dates="reported",
            source_reference="Public synthetic HSA cash statement endpoints",
        )
        store.post_reviewed_opening("hsa")
        hsa_rows = hsa_result.evidence.payload.accounts[0].rows
        for row in (hsa_rows[0], hsa_rows[2]):
            store.post_reviewed_cash_category(
                row.row_id, "income:hsa", purpose="income", reason="Reviewed synthetic HSA receipt purpose"
            )
        frame = store.settlement_review_snapshot(preferences=V2Preferences())
        store.post_reviewed_settlement(
            hsa_rows[1].row_id,
            (),
            preferences=V2Preferences(),
            expected_basis_sha256=frame.basis_sha256,
            expected_destination=ExpectedOwnedDestination(
                "investment", "Synthetic owned destination; no receipt source exists", True
            ),
            reason="Explicit synthetic ownership review; receipt stays missing",
        )
        frame = store.source_dated_value_snapshot("hsa")
        candidate = frame.source_value_candidates[0]
        store.record_reviewed_source_value(
            "hsa",
            candidate.candidate_id,
            expected_candidate_sha256=candidate.version,
            expected_basis_sha256=frame.basis_sha256,
            reference="Synthetic printed cash closing",
            reason="Nonposting source closing review",
        )
        frame = store.account_anchor_snapshot("investment")
        store.record_reviewed_dated_value(
            "investment",
            amount_minor=500000,
            value_date=date(2026, 9, 30),
            tracking_scope="account_total",
            reference="Public synthetic independently reviewed value",
            reason="Nonposting value, no transfer receipt or opening asserted",
            expected_basis_sha256=frame.basis_sha256,
        )
        check = next(c for c in store.statement_reconciliation_checks() if c.account_id == "hsa")
        assert check.reconciled, check.exceptions
        store.save_reconciliation_decision(
            "hsa",
            hsa_result.source_sha256,
            expected_input_version=check.input_version,
            reason="Synthetic cash-component-only check; destination receipt remains unknown",
        )
    summary = verify(root)
    (root / "demo.json").write_text(
        json.dumps(
            {"schema": SCHEMA_VERSION, "selected_source": cash_result.source_sha256, "expected": summary}, indent=2
        )
    )
    launcher = root / "Open-review-demo.cmd"
    pin_runtime(REPO, root, Path(sys.executable), Path(__file__))
    (root / "WALKTHROUGH.txt").write_text(
        "PUBLIC SYNTHETIC DATA ONLY. Independent disposable schema "
        + str(SCHEMA_VERSION)
        + "\n\n1. Double-click Open-review-demo.cmd.\n2. Reviewed reports: October spending $4.00 Food, income $10.00, budget Food $100/$4/$96.\n3. Account positions, as of 2026-10-26: checking $1006, zero savings $0, HSA cash $1100.10, card $100 owed, investment opening unknown with separate reviewed value $5000 dated September 30. Clearing $100 remains in transit, with no investment receipt.\n4. Review cash activity on checking: Tea -$3 remains pending; classify Food and October spending becomes $7, checking $1003. Correct Coffee to Travel to inspect retained history.\n5. Review > Transfer fees and partial settlements: inspect HSA $100 outflow to expected investment destination, zero receipt. Reports > Cash movement: select HSA, range August 1 to September 1: income $200.10, unsettled owned transfer -$100, net $100.10. No extra spending or destination posting.\n6. Statement coverage: HSA cash is reconciled against its component endpoint, full-page capture unverified. Saved cutoff and source proof remain separate.\n7. Import sources/Import-this-next.csv, then review its unbound account.\n8. Profile > Back up; restore as a NEW .db in this folder; Save selected source original to a NEW path. Reopen this demo only.\n\nAll files are disposable synthetic fixtures. Do not use a daily/1.x profile. Catalog uses a separate local ephemeral test trust key; private key is discarded. Closing does not delete the demo, so reopen is repeatable.\n"
    )
    print(json.dumps({"root": str(root), "launcher": str(launcher), "verification": summary}, indent=2))
    return root


def verify(root):
    from parsetrail.core.v2_cash_movement import read_cash_movement
    from parsetrail.core.v2_profile_store import V2ProfileStore

    workspace = workspace_at(root)
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        spending = store.reviewed_category_summary(
            kind="expense", start=date(2026, 10, 1), end=date(2026, 11, 1)
        ).total_minor
        income = store.reviewed_category_summary(
            kind="income", start=date(2026, 10, 1), end=date(2026, 11, 1)
        ).total_minor
        positions = store.account_positions(as_of=date(2026, 10, 26))
        accounts = {row.account_id: row for row in positions.accounts}
        assert spending == 400 and income == 1000
        assert accounts["checking"].position_debit_minor == 100600
        assert accounts["savings"].position_debit_minor == 0
        assert accounts["hsa"].position_debit_minor == 110010
        assert accounts["card"].position_debit_minor == -10000
        assert accounts["investment"].position_debit_minor is None
        assert accounts["investment"].latest_dated_value.amount_minor == 500000
        assert positions.transfer_clearing_debit_minor == 10000
        assert accounts["hsa"].latest_dated_value.amount_minor == 110010
        assert len(store.reconciliation_history("hsa")) == 1
        assert len(store.source_ids()) == 3
    cash = read_cash_movement(workspace.profile_path, ("hsa",), start=date(2026, 8, 1), end=date(2026, 9, 1))
    assert cash.total_minor == 10010 and cash.expected_receipts_without_source == 1
    return {
        "october_spending_minor": spending,
        "october_income_minor": income,
        "checking_position_minor": 100600,
        "hsa_cash_position_minor": 110010,
        "transfer_clearing_minor": 10000,
        "hsa_cash_movement_minor": 10010,
        "investment_reviewed_value_minor": 500000,
        "source_count": 3,
    }


def open_demo(root, *, smoke=False):
    import hashlib

    from PySide6.QtCore import Qt, QTimer

    isolate(root)
    if not smoke:
        os.environ.pop("QT_QPA_PLATFORM", None)
    from parsetrail.gui.v2_workspace_window import V2WorkspaceWindow
    from PySide6.QtWidgets import QApplication, QFormLayout, QLineEdit

    workspace = workspace_at(root)
    before = hashlib.sha256(workspace.profile_path.read_bytes()).hexdigest() if smoke else None
    app = QApplication.instance() or QApplication([])
    window = V2WorkspaceWindow(workspace)
    window.setWindowTitle("ParseTrail 2.0 - PUBLIC SYNTHETIC REVIEW DEMO")
    selected = json.loads((root / "demo.json").read_text())["selected_source"]
    window.refresh(select_source=selected)
    window.status.setWordWrap(True)
    window.status.setText(
        "DISPOSABLE SYNTHETIC DEMO. October reports: $4 Food / $10 income; Tea $3 pending. Positions: checking $1006; HSA cash $1100.10; $100 unresolved transfer clearing; investment $5000 is a separate dated value, not receipt. See WALKTHROUGH.txt beside the launcher."
    )
    paths = QFormLayout()
    for label, path in (
        ("Walkthrough:", root / "WALKTHROUGH.txt"),
        ("Import next:", root / "sources/Import-this-next.csv"),
        ("Demo files:", root),
    ):
        field = QLineEdit(str(path))
        field.setReadOnly(True)
        paths.addRow(label, field)
    window.centralWidget().layout().addLayout(paths)
    window.resize(1150, 720)
    if smoke:
        window.setAttribute(Qt.WA_DontShowOnScreen, True)
        QTimer.singleShot(100, app.quit)
    window.show()
    result = app.exec()
    window.close()
    if smoke:
        if hashlib.sha256(workspace.profile_path.read_bytes()).hexdigest() != before:
            raise RuntimeError("demo_startup_changed_profile")
        print(json.dumps({"startup": "passed", "platform": app.platformName(), "profile_unchanged": True}))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--open", type=Path)
    mode.add_argument("--verify", type=Path)
    mode.add_argument("--smoke-ui", type=Path, help="Check the same startup path with display suppressed and exit.")
    mode.add_argument(
        "--prepare-at", type=Path, help="Prepare at a new disposable directory; existing paths are refused."
    )
    args = parser.parse_args()
    if args.open:
        raise SystemExit(open_demo(args.open.resolve()))
    if args.smoke_ui:
        raise SystemExit(open_demo(args.smoke_ui.resolve(), smoke=True))
    if args.verify:
        isolate(args.verify.resolve())
        print(json.dumps(verify(args.verify.resolve()), indent=2))
    else:
        prepare(args.prepare_at.resolve() if args.prepare_at else None)
