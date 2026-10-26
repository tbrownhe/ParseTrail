"""Disposable final review preparation checks; no owner/native acceptance claim."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

TOOL = Path(__file__).with_name("prepare_demo.py")


@pytest.fixture(scope="module")
def prepared(tmp_path_factory):
    destination = tmp_path_factory.mktemp("final-review") / "demo"
    env = os.environ.copy()
    env["PYTHON_KEYRING_BACKEND"] = "keyring.backends.null.Keyring"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [sys.executable, "-B", str(TOOL), "--prepare-at", str(destination)],
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
        check=True,
    )
    return destination, json.loads(result.stdout)


def test_prepare_exact_books_sources_and_pinned_reopen(prepared):
    destination, result = prepared
    expected = result["verification"]
    assert expected["schema"] == 22 and expected["source_count"] == 6
    assert expected["october_spending_minor"] == 400 and expected["october_income_minor"] == 1000
    assert expected["checking_position_minor"] == 100600 and expected["transfer_clearing_minor"] == 10000
    assert expected["payment_checking_position_minor"] == 76000
    assert expected["capital_principal_minor"] == -950000 and expected["yamaha_whole_register_minor"] == -99000
    assert expected["january_loan_interest_minor"] == 2000 and expected["february_vehicle_charge_minor"] == 1000
    assert expected["saved_assumed_date_preference"] is False
    walkthrough = (destination / "WALKTHROUGH.txt").read_text(encoding="utf-8")
    for source in (destination / "sources").iterdir():
        if source.name != "Import-this-next.csv":
            assert f"{source.name}: Source {hashlib.sha256(source.read_bytes()).hexdigest()[:16]}" in walkthrough
    before = hashlib.sha256((destination / "review.db").read_bytes()).hexdigest()
    for helper in (TOOL, destination / "runtime/devtools/v2_review_demo/prepare_demo.py"):
        checked = subprocess.run(
            [sys.executable, "-B", str(helper), "--verify", str(destination)],
            cwd=destination / "runtime",
            capture_output=True,
            text=True,
            timeout=60,
            check=True,
        )
        assert json.loads(checked.stdout) == expected
    manifest = json.loads((destination / "runtime-manifest.json").read_text())
    assert manifest["schema_version"] == 22
    assert all(
        hashlib.sha256((destination / "runtime" / row["path"]).read_bytes()).hexdigest() == row["sha256"]
        for row in manifest["files"]
    )
    assert hashlib.sha256((destination / "review.db").read_bytes()).hexdigest() == before
    refused = subprocess.run(
        [sys.executable, "-B", str(TOOL), "--prepare-at", str(destination)], capture_output=True, text=True, timeout=30
    )
    assert refused.returncode != 0 and "FileExistsError" in refused.stderr
    assert hashlib.sha256((destination / "review.db").read_bytes()).hexdigest() == before


def test_walkthrough_cash_scope_dates_and_record_details(prepared):
    destination, _ = prepared
    before = hashlib.sha256((destination / "review.db").read_bytes()).hexdigest()
    helper = destination / "runtime/devtools/v2_review_demo/prepare_demo.py"
    code = """import importlib.util,json,sys
from pathlib import Path
helper,root=map(Path,sys.argv[1:])
spec=importlib.util.spec_from_file_location('pinned_demo',helper)
tool=importlib.util.module_from_spec(spec);spec.loader.exec_module(tool);tool.isolate(root)
from PySide6.QtCore import QDate,Qt
from PySide6.QtWidgets import QApplication
from parsetrail.gui.v2_cash_movement import V2CashMovementDialog
app=QApplication([]);dialog=V2CashMovementDialog(root/'review.db')
items={dialog.accounts.item(i).data(Qt.UserRole):dialog.accounts.item(i) for i in range(dialog.accounts.count())}
items['payment-checking'].setSelected(True)
assert dialog.report is None
items['hsa'].setCheckState(Qt.Checked)
for key,item in items.items():item.setCheckState(Qt.Checked if key=='payment-checking' else Qt.Unchecked)
assert dialog._selected_ids()==('payment-checking',)
dialog.start.setDate(QDate(2026,1,1));dialog.end.setDate(QDate(2026,2,1))
assert dialog.entries.rowCount()==1 and dialog.summary.rowCount()==2
assert [dialog.entries.item(0,c).text() for c in (0,2,3)]==['2026-01-14','-$220.00','Reviewed loan payment cash outflow']
assert dialog.report.total_minor==-22000
assert [(p.classification,p.amount_minor) for p in dialog.report.rows[0].components]==[('loan_principal',-20000),('expense',-2000)]
assert 'Reviewed loan principal payment: -$200.00' in dialog.details.toPlainText()
assert 'Reviewed cash expense: -$20.00' in dialog.details.toPlainText()
assert dialog.sources.count()==2
dialog.start.setDate(QDate(2026,2,1));dialog.end.setDate(QDate(2026,3,1))
assert dialog.entries.rowCount()==1 and dialog.summary.rowCount()==1
assert [dialog.entries.item(0,c).text() for c in (0,2,3)]==['2026-02-09','-$20.00','Transfer sent']
assert dialog.report.total_minor==-2000
assert [(p.classification,p.amount_minor) for p in dialog.report.rows[0].components]==[('liability_payment',-2000)]
assert '2026-02-10' in dialog.details.toPlainText()
assert dialog.sources.count()==1
dialog.close();app.processEvents()
print(json.dumps({'walkthrough_cash_screen':'passed'}))
"""
    environment = os.environ.copy()
    environment["QT_QPA_PLATFORM"] = "offscreen"
    result = subprocess.run(
        [sys.executable, "-B", "-c", code, str(helper), str(destination)],
        cwd=destination / "runtime",
        capture_output=True,
        text=True,
        env=environment,
        timeout=60,
        check=True,
    )
    assert json.loads(result.stdout)["walkthrough_cash_screen"] == "passed"
    assert hashlib.sha256((destination / "review.db").read_bytes()).hexdigest() == before
    walkthrough = (destination / "WALKTHROUGH.txt").read_text(encoding="utf-8")
    assert "2026-01-14, Reviewed loan payment cash outflow, -$220.00" in walkthrough
    assert "2026-02-09, Transfer sent, -$20.00" in walkthrough


def test_backup_restore_recovery_retains_six_sources_and_histories(prepared, tmp_path):
    destination, _ = prepared
    spec = importlib.util.spec_from_file_location("final_review_candidate", TOOL)
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    from parsetrail.core.v2_profile_store import V2ProfileStore
    from parsetrail.core.v2_source_recovery import recover_source_original

    before = hashlib.sha256((destination / "review.db").read_bytes()).hexdigest()
    backup = V2ProfileStore.snapshot_to(destination / "review.db", tmp_path / "backup.dbb")
    restored = V2ProfileStore.snapshot_to(backup, tmp_path / "restored.db")
    with (
        V2ProfileStore.open(destination / "review.db", read_only=True) as original,
        V2ProfileStore.open(restored, read_only=True) as reopened,
    ):
        assert original.source_ids() == reopened.source_ids() and len(reopened.source_ids()) == 6
        assert original.loan_history() == reopened.loan_history() and len(reopened.loan_history()) == 1
        assert original.transfer_history() == reopened.transfer_history() and len(reopened.transfer_history()) == 2
        for source_id in original.source_ids():
            saved = original.load_import(source_id)
            assert reopened.load_import(source_id) == saved
            recovered = recover_source_original(restored, source_id, tmp_path / (source_id + saved.suffix))
            assert (
                recovered.read_bytes() == saved.source
                and hashlib.sha256(recovered.read_bytes()).hexdigest() == source_id
            )
    assert hashlib.sha256((destination / "review.db").read_bytes()).hexdigest() == before


def test_native_windows_display_suppressed_same_entry_and_loan_dialogs(prepared):
    destination, _ = prepared
    helper = destination / "runtime/devtools/v2_review_demo/prepare_demo.py"
    env = os.environ.copy()
    env["QT_QPA_PLATFORM"] = "windows" if sys.platform == "win32" else "offscreen"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    before = hashlib.sha256((destination / "review.db").read_bytes()).hexdigest()
    startup = subprocess.run(
        [sys.executable, "-B", str(helper), "--smoke-ui", str(destination)],
        cwd=destination / "runtime",
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=True,
    )
    report = json.loads(startup.stdout)
    assert report["startup"] == "passed" and report["profile_unchanged"]
    assert report["platform"] == ("windows" if sys.platform == "win32" else "offscreen")
    code = """import hashlib,importlib.util,json,sys
from pathlib import Path
helper,root=map(Path,sys.argv[1:])
spec=importlib.util.spec_from_file_location('pinned_demo',helper);tool=importlib.util.module_from_spec(spec);spec.loader.exec_module(tool);tool.isolate(root)
from PySide6.QtWidgets import QApplication,QMessageBox
from parsetrail.core.v2_profile_store import V2ProfileStore
from parsetrail.gui.v2_loan_payment_review import V2LoanPaymentReview
from parsetrail.gui.v2_liability_register_review import V2LiabilityRegisterReview
from parsetrail.gui.v2_reviewed_reports import V2ReviewedReportsDialog
app=QApplication([])
def warning(*args):raise RuntimeError(str(args[1:]))
QMessageBox.warning=warning
workspace=tool.workspace_at(root)
with V2ProfileStore.open(workspace.profile_path,read_only=True) as store:
 event=store.loan_history()[0];source=next(s for s in store.source_ids() if store.load_import(s).evidence.parser_id=='pdf_yamahafin_202306')
views=[V2LoanPaymentReview(workspace,event_id=event.event_id),V2LiabilityRegisterReview(workspace,source),V2ReviewedReportsDialog(workspace.profile_path)]
assert all(not view.isVisible() for view in views)
for view in views:view.close()
app.processEvents()
print(json.dumps({'loan_and_register_dialogs':'constructed','visible':False,'platform':app.platformName()}))
"""
    dialogs = subprocess.run(
        [sys.executable, "-B", "-c", code, str(helper), str(destination)],
        cwd=destination / "runtime",
        capture_output=True,
        text=True,
        env=env,
        timeout=60,
        check=True,
    )
    assert json.loads(dialogs.stdout)["visible"] is False
    assert hashlib.sha256((destination / "review.db").read_bytes()).hexdigest() == before
