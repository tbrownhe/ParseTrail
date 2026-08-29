from __future__ import annotations

import subprocess
import sys
from contextlib import nullcontext
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from parsetrail.core import query
from parsetrail.core.diagnostics import Diagnostic, DiagnosticSeverity
from parsetrail.core.parser_routing import ParseResult, ParseWarningsRejectedError
from parsetrail.core.statements import (
    AccountAssignmentRequiredError,
    SourceArchiveError,
    StatementImportService,
)
from parsetrail.core.validation import Account, Statement


def _statement(source: Path, *, account_num: str = "1234") -> Statement:
    return Statement(
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 31),
        accounts=[
            Account(
                account_num=account_num,
                start_balance=Decimal("0.00"),
                end_balance=Decimal("0.00"),
                transactions=[],
            )
        ],
        plugin_name="example",
        fpath=source,
    )


def _service(**kwargs) -> StatementImportService:
    return StatementImportService(
        lambda: nullcontext(object()),
        SimpleNamespace(
            metadata={
                "example": {
                    "PLUGIN_NAME": "example",
                    "COMPANY": "Example Bank",
                    "STATEMENT_TYPE": "Checking",
                }
            }
        ),
        **kwargs,
    )


def test_import_service_module_loads_when_qt_and_gui_imports_are_forbidden() -> None:
    code = """
import sys

class DenyUiImports:
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "PySide6" or fullname.startswith("PySide6.") or fullname.startswith("parsetrail.gui"):
            raise AssertionError(f"UI dependency imported by core service: {fullname}")
        return None

sys.meta_path.insert(0, DenyUiImports())
import parsetrail.core.statements
print("headless import service ok")
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=Path(__file__).parents[1],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "headless import service ok" in result.stdout


def test_validation_warnings_require_an_explicit_adapter_decision(tmp_path: Path) -> None:
    statement = _statement(tmp_path / "statement.pdf")
    warning = Diagnostic(
        code="fixture.warning",
        message="Fixture warning",
        severity=DiagnosticSeverity.WARNING,
    )
    result = ParseResult(
        statement=statement,
        plugin_name="example",
        diagnostics=(warning,),
    )

    with pytest.raises(ParseWarningsRejectedError):
        _service()._statement_from_result(result)

    observed = []
    service = _service(warning_decision=lambda warnings: observed.extend(warnings) or True)
    assert service._statement_from_result(result) is statement
    assert observed == [warning]


def test_unknown_account_requires_an_adapter_resolver(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    statement = _statement(tmp_path / "statement.pdf", account_num="new-account")
    monkeypatch.setattr(
        query,
        "account_id_of_account_number",
        lambda _session, _account_num: (_ for _ in ()).throw(KeyError("unknown")),
    )

    with pytest.raises(AccountAssignmentRequiredError, match="new-account"):
        _service().attach_account_info(statement)


def test_account_resolver_result_is_attached_to_the_statement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    statement = _statement(tmp_path / "statement.pdf", account_num="new-account")
    observed = []
    monkeypatch.setattr(
        query,
        "account_id_of_account_number",
        lambda _session, _account_num: (_ for _ in ()).throw(KeyError("unknown")),
    )
    monkeypatch.setattr(query, "account_name_of_account_id", lambda _session, account_id: f"Account {account_id}")
    service = _service(
        account_resolver=lambda fpath, account_num, metadata: observed.append((fpath, account_num, metadata)) or 42,
    )

    service.attach_account_info(statement)

    account = statement.accounts[0]
    assert account.account_id == 42
    assert account.account_name == "Account 42"
    assert observed == [
        (
            statement.fpath,
            "new-account",
            service.plugin_manager.metadata["example"],
        )
    ]


def test_locked_source_move_retries_only_when_adapter_approves(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "statement.pdf"
    destination = tmp_path / "SUCCESS" / source.name
    source.write_bytes(b"statement")
    original_rename = __import__("os").rename
    attempts = 0
    decisions = []

    def initially_locked(source_path, destination_path):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise PermissionError("locked")
        return original_rename(source_path, destination_path)

    monkeypatch.setattr("parsetrail.core.statements.os.rename", initially_locked)
    service = _service(
        move_retry_decision=lambda fpath, dpath, error: decisions.append((fpath, dpath, str(error))) or True,
    )

    service.move_file_safely(source, destination)

    assert destination.read_bytes() == b"statement"
    assert decisions == [(source, destination, "locked")]


def test_locked_source_move_without_retry_raises_typed_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "statement.pdf"
    destination = tmp_path / "SUCCESS" / source.name
    source.write_bytes(b"statement")
    monkeypatch.setattr(
        "parsetrail.core.statements.os.rename",
        lambda _source, _destination: (_ for _ in ()).throw(PermissionError("locked")),
    )

    with pytest.raises(SourceArchiveError, match="statement.pdf"):
        _service().move_file_safely(source, destination)

    assert source.read_bytes() == b"statement"
    assert not destination.exists()
