"""Disposable synthetic V2 integrated review preparation; no daily profile state."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
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


def inherit_public_catalog_access(root):
    """Hand off only this generated public fixture catalog using its parent ACL.

    Windows temporary directories restrict access to their creating principal.
    Catalog activation retains that ACL when renaming its staging directory.
    Ordinary runtime caches retain their normal protection; only a prepared
    synthetic demo needs to be readable by the owner of its containing folder.
    """
    if sys.platform != "win32":
        return
    catalog = root / "catalog"
    releases = catalog / "releases"
    if any(path.is_symlink() or path.is_junction() for path in (catalog, releases)):
        raise ValueError("demo_catalog_path")
    directories = list(releases.iterdir())
    if len(directories) != 1:
        raise ValueError("demo_catalog_release_count")
    release = directories[0]
    if release.is_symlink() or release.is_junction() or not release.is_dir():
        raise ValueError("demo_catalog_path")
    files = list(release.iterdir())
    if {path.name for path in files} != {"catalog.json", "catalog.sig"} or any(
        path.is_symlink() or path.is_junction() or not path.is_file() for path in files
    ):
        raise ValueError("demo_catalog_shape")
    subprocess.run(
        [str(Path(os.environ["SystemRoot"]) / "System32/icacls.exe"), str(release), "/inheritance:e", "/Q"],
        check=True,
        capture_output=True,
        text=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
        timeout=30,
    )


def prepare(destination: Path | None = None):
    import hashlib

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
    inherit_public_catalog_access(root)
    workspace.catalog_cache.load_current()
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
    loan_sources = add_loan_sources(workspace, sources, family_sources())
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
        seed_loan_reviews(store, loan_sources)
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
    with (root / "WALKTHROUGH.txt").open("a", encoding="utf-8") as walkthrough:
        walkthrough.write(
            "\n9. Review > Evidenced loan principal and interest: inspect the active Capital event history. It contains the January 14 bank outflow $220 and January 15 lender event: $200 principal plus $20 Loan interest. Original lender activity date remains observed; accounting date is explicitly assumed, not a source posting guess. The fixture author opted in for that review only; saved Settings remain default off. Current Demo Capital principal is $9500 owed from an independent authored $9700 opening; its PDF has no printed opening. Select its source closing point to inspect the separate nonposting proof.\n10. Select Yamaha-February.pdf and Review > Review selected liability register. Whole liability opening $1000 owed is source-backed at January 31. Transaction February 5 posts February 7: $10 Vehicle charge. Transaction February 9 posts February 10: $20 owned repayment from Demo payment checking; no principal/interest split or second expense. Register now $990 owed; its separate source closing agrees. Inspect history/correction without changing source dates.\n11. Reviewed reports: January expense is only $20 Loan interest; February expense is only $10 Vehicle charge, whose February budget is $50/$10/$40. Account positions: payment checking $760, Capital principal $9500 owed (principal component), Yamaha whole register $990 owed. Through January 14, $220 is in clearing until lender January 15; through February 9, $20 clears only at lender February 10. The later HSA $100 expected receipt remains unresolved.\n12. Cash movement: select only Demo payment checking. January 1-February 1 shows one actual -$220 bank record split into -$200 principal/-$20 expense purposes. February 1-March 1 shows one -$20 liability repayment, no principal/interest allocation. Source previews retain both account sources and original dates.\n13. Back up and restore into a new file, reopen, and recover Capital/Yamaha originals to new paths. All six embedded originals and complete loan/register histories survive. The runtime is pinned to schema22 for this demo; no old-profile migration or release is performed.\n"
        )
    guide = [
        "Sources are listed by hash in the workspace. When a step names a file, select its matching Source prefix:",
    ]
    for name in (
        "Checking-October.csv",
        "HSA-August.pdf",
        "Card-January.pdf",
        "Payments-January-February.csv",
        "Capital-January.pdf",
        "Yamaha-February.pdf",
    ):
        guide.append(f"  {name}: Source {hashlib.sha256((sources / name).read_bytes()).hexdigest()[:16]}")
    guide.append("Before step 6 select the HSA source; before step 10 select the Yamaha source.")
    walkthrough = root / "WALKTHROUGH.txt"
    walkthrough.write_text("\n".join(guide) + "\n\n" + walkthrough.read_text(encoding="utf-8"), encoding="utf-8")
    print(json.dumps({"root": str(root), "launcher": str(launcher), "verification": summary}, indent=2))
    return root


def add_loan_sources(workspace, sources, cases):
    """Public source bytes only; all three imports use real signed routing/workers."""
    payment = (
        b"Date,Account,Description,Amount,ReportedBalance\n"
        b"01/14/2026,Payment checking,Capital payment,-$220.00,$780.00\n"
        b"02/09/2026,Payment checking,Yamaha repayment,-$20.00,$760.00\n"
    )
    payment_path = sources / "Payments-January-February.csv"
    payment_path.write_bytes(payment)
    result = {"bank": workspace.import_file(payment_path)}
    for name, definition, filename in (
        ("capital", "capital-one-loan-pilot-definition.json", "Capital-January.pdf"),
        ("yamaha", "yamaha-card-pilot-definition.json", "Yamaha-February.pdf"),
    ):
        case = next(case for case in cases if case.definition_name == definition)
        path = sources / filename
        path.write_bytes(case.source)
        result[name] = workspace.import_file(path)
    return result


def seed_loan_reviews(store, sources):
    """Seed explicit fixture-author decisions; do not change saved global preferences."""
    from parsetrail.core.v2_preferences import V2Preferences
    from parsetrail.core.v2_profile_store import FinancialAccount

    for account in (
        FinancialAccount("payment-checking", "Demo payment checking", "asset", "synthetic"),
        FinancialAccount(
            "capital-principal",
            "Demo Capital principal",
            "liability",
            "capital_one",
            tracking_scope="principal_component",
        ),
        FinancialAccount("yamaha-register", "Demo Yamaha whole register", "liability", "yamaha"),
    ):
        store.add_financial_account(account)
    store.add_category_account("expense:vehicle-charge", "Vehicle charge", "expense")
    store.set_category_budget_rate("expense:vehicle-charge", date(2026, 2, 1), 5000)
    store.bind_source_account(sources["bank"].source_sha256, "Payment checking", "opaque", "payment-checking")
    for name, account_id in (("capital", "capital-principal"), ("yamaha", "yamaha-register")):
        section = sources[name].evidence.payload.accounts[0]
        store.bind_source_account(
            sources[name].source_sha256, section.source_identity, section.source_identity_form, account_id
        )
    for account_id, amount in (("payment-checking", 100000), ("capital-principal", -970000)):
        frame = store.account_anchor_snapshot(account_id)
        store.post_reviewed_manual_opening(
            account_id,
            amount_minor=amount,
            cutoff_date=date(2025, 12, 31),
            tracking_scope=frame.account.tracking_scope,
            reference="Public synthetic independent opening, not a printed source fact",
            reason="Explicit fixture-author opening decision",
            expected_decision_version=None,
            expected_basis_sha256=frame.basis_sha256,
        )
    store.record_statement_source_review(
        "yamaha-register",
        sources["yamaha"].source_sha256,
        expected_revision_id=None,
        opening_origin="reported",
        closing_origin="reported",
        timing_confirmed=True,
        posting_dates="reported",
        source_reference="Public synthetic Yamaha register endpoints and both date columns",
    )
    opening = store.post_reviewed_opening("yamaha-register")
    assert opening.amount_minor == -100000 and opening.cutoff_date == date(2026, 1, 31)
    bank_rows = sources["bank"].evidence.payload.rows
    capital_rows = sources["capital"].evidence.payload.accounts[0].rows
    assert capital_rows[0].posting_date_guess is None and capital_rows[0].date_role == "activity_date"
    # An explicit fixture-author opt-in permits the observed activity date as an
    # assumed accounting date; it does not add a source posting date or preference.
    permission = V2Preferences(False, True)
    basis = store.loan_review_snapshot(permission).basis_sha256
    event = store.post_reviewed_loan_payment(
        bank_rows[0].row_id,
        tuple(row.row_id for row in capital_rows),
        expected_basis_sha256=basis,
        preferences=permission,
        reference="Public synthetic Capital printed principal/interest and actual owned bank outflow",
        reason="Reviewed full gross payment; assumed lender accounting date explicitly permitted",
    )
    assert event.manifest.principal_minor == 20000 and event.manifest.interest_minor == 2000
    yamaha_rows = sources["yamaha"].evidence.payload.accounts[0].rows
    frame = store.source_interpretation_snapshot(sources["yamaha"].source_sha256, kind="register")
    store.post_reviewed_register_category(
        yamaha_rows[0].row_id,
        "expense:vehicle-charge",
        purpose="expense",
        reason="Explicit synthetic whole-register vehicle charge, no inferred interest",
        expected_basis_sha256=frame.basis_sha256,
    )
    store.post_reviewed_transfer(
        bank_rows[1].row_id,
        yamaha_rows[1].row_id,
        preferences=V2Preferences(),
        reason="Explicit synthetic owned whole-liability repayment; no principal/interest split",
    )
    for account_id in ("capital-principal", "yamaha-register"):
        frame = store.source_dated_value_snapshot(account_id)
        candidate = frame.source_value_candidates[0]
        store.record_reviewed_source_value(
            account_id,
            candidate.candidate_id,
            expected_candidate_sha256=candidate.version,
            expected_basis_sha256=frame.basis_sha256,
            reference="Public synthetic printed closing point, separate from books",
            reason="Explicit nonposting source closing review",
        )
    check = next(check for check in store.statement_reconciliation_checks() if check.account_id == "yamaha-register")
    assert check.reconciled, check.exceptions
    store.save_reconciliation_decision(
        "yamaha-register",
        sources["yamaha"].source_sha256,
        expected_input_version=check.input_version,
        reason="Reviewed account-total register check; no component split inferred",
    )


def verify(root):
    from parsetrail.core.v2_cash_movement import read_cash_movement
    from parsetrail.core.v2_preferences import V2Preferences
    from parsetrail.core.v2_profile_store import SCHEMA_VERSION, V2ProfileStore

    workspace = workspace_at(root)
    assert workspace.preferences() == V2Preferences()
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert SCHEMA_VERSION == 22
        spending = store.reviewed_category_summary(
            kind="expense", start=date(2026, 10, 1), end=date(2026, 11, 1)
        ).total_minor
        income = store.reviewed_category_summary(
            kind="income", start=date(2026, 10, 1), end=date(2026, 11, 1)
        ).total_minor
        positions = store.account_positions(as_of=date(2026, 10, 26))
        accounts = {row.account_id: row for row in positions.accounts}
        expected = {
            "checking": 100600,
            "savings": 0,
            "hsa": 110010,
            "card": -10000,
            "investment": None,
            "payment-checking": 76000,
            "capital-principal": -950000,
            "yamaha-register": -99000,
        }
        assert {key: row.position_debit_minor for key, row in accounts.items()} == expected
        assert spending == 400 and income == 1000
        assert accounts["investment"].latest_dated_value.amount_minor == 500000
        assert accounts["hsa"].latest_dated_value.amount_minor == 110010
        assert accounts["capital-principal"].latest_dated_value.amount_minor == -950000
        assert accounts["yamaha-register"].latest_dated_value.amount_minor == -99000
        assert positions.transfer_clearing_debit_minor == 10000
        assert len(store.reconciliation_history("hsa")) == 1
        assert len(store.reconciliation_history("yamaha-register")) == 1
        assert len(store.source_ids()) == 6
        january = store.reviewed_category_summary(kind="expense", start=date(2026, 1, 1), end=date(2026, 2, 1))
        february = store.reviewed_category_summary(kind="expense", start=date(2026, 2, 1), end=date(2026, 3, 1))
        assert january.total_minor == 2000 and february.total_minor == 1000
        assert {row.category_id: row.amount_minor for row in january.categories}["builtin:loan-interest"] == 2000
        assert {row.category_id: row.amount_minor for row in february.categories}["expense:vehicle-charge"] == 1000
        events = store.loan_history()
        assert len(events) == 1 and events[0].status == "active"
        proof = events[0].manifest.components[0]
        assert (proof.raw_amount_minor, proof.principal_minor, proof.interest_minor) == (-22000, 20000, 2000)
        assert proof.date_provenance == "assumed" and proof.activity_date == proof.effective_date == "2026-01-15"
        capital = store.load_import(proof.source_sha256).evidence.payload.accounts[0]
        assert capital.opening is None and capital.rows[0].posting_date_guess is None
        assert capital.rows[0].date_role == "activity_date" and capital.rows[0].date.provenance == "observed"
        assert accounts["capital-principal"].opening_status == "valid"
        assert store.opening_decision("capital-principal").origin == "manual"
        register_source = next(
            source
            for source in store.source_ids()
            if store.load_import(source).evidence.parser_id == "pdf_yamahafin_202306"
        )
        register = store.load_import(register_source).evidence.payload.accounts[0]
        assert [(r.transaction_date.iso, r.date.iso, r.amount.minor) for r in register.rows] == [
            ("2026-02-05", "2026-02-07", -1000),
            ("2026-02-09", "2026-02-10", 2000),
        ]
        assert all(not row.components for row in register.rows)
        assert store.opening_decision("yamaha-register").origin == "source"
        assert store.connection.execute(
            "SELECT count(*) FROM Accounts WHERE id='builtin:loan-interest'"
        ).fetchone() == (1,)
        for day, register_position, clearing in (
            (date(2026, 2, 7), -101000, 0),
            (date(2026, 2, 9), -101000, 2000),
            (date(2026, 2, 10), -99000, 0),
        ):
            point = store.account_positions(as_of=day)
            assert (
                next(row for row in point.accounts if row.account_id == "yamaha-register").position_debit_minor
                == register_position
            )
            assert point.transfer_clearing_debit_minor == clearing
        for day, principal, clearing in ((date(2026, 1, 14), -970000, 22000), (date(2026, 1, 15), -950000, 0)):
            point = store.account_positions(as_of=day)
            assert (
                next(row for row in point.accounts if row.account_id == "capital-principal").position_debit_minor
                == principal
            )
            assert point.transfer_clearing_debit_minor == clearing
    hsa_cash = read_cash_movement(workspace.profile_path, ("hsa",), start=date(2026, 8, 1), end=date(2026, 9, 1))
    assert hsa_cash.total_minor == 10010 and hsa_cash.expected_receipts_without_source == 1
    principal_cash = read_cash_movement(
        workspace.profile_path, ("payment-checking",), start=date(2026, 1, 1), end=date(2026, 2, 1)
    )
    assert principal_cash.total_minor == -22000 and len(principal_cash.rows) == 1
    assert {part.classification: part.amount_minor for part in principal_cash.rows[0].components} == {
        "loan_principal": -20000,
        "expense": -2000,
    }
    register_cash = read_cash_movement(
        workspace.profile_path, ("payment-checking",), start=date(2026, 2, 1), end=date(2026, 3, 1)
    )
    assert register_cash.total_minor == -2000 and len(register_cash.rows) == 1
    assert [(part.classification, part.amount_minor) for part in register_cash.rows[0].components] == [
        ("liability_payment", -2000)
    ]
    return {
        "schema": SCHEMA_VERSION,
        "october_spending_minor": spending,
        "october_income_minor": income,
        "checking_position_minor": 100600,
        "hsa_cash_position_minor": 110010,
        "transfer_clearing_minor": 10000,
        "hsa_cash_movement_minor": 10010,
        "investment_reviewed_value_minor": 500000,
        "payment_checking_position_minor": 76000,
        "capital_principal_minor": -950000,
        "yamaha_whole_register_minor": -99000,
        "january_loan_interest_minor": january.total_minor,
        "february_vehicle_charge_minor": february.total_minor,
        "january_bank_movement_minor": principal_cash.total_minor,
        "february_bank_movement_minor": register_cash.total_minor,
        "source_count": 6,
        "loan_events": 1,
        "saved_assumed_date_preference": False,
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
        "DISPOSABLE SYNTHETIC DEMO. Capital principal/interest and Yamaha whole-register repayment are seeded; preferences remain default off. October reports: $4 Food / $10 income; Tea $3 pending. Positions: checking $1006; HSA cash $1100.10; $100 unresolved transfer clearing; investment $5000 is a separate dated value, not receipt. See WALKTHROUGH.txt beside the launcher."
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
