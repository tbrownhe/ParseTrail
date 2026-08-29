from contextlib import AbstractContextManager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from parsetrail.core import query
from parsetrail.core.orm import Transactions, create_database
from parsetrail.core.parser_routing import ParseResult
from parsetrail.core.settings import settings
from parsetrail.core.statements import ArchivePendingError, StatementProcessor
from parsetrail.core.validation import Account, Statement
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError


def _transaction_row(md5hash: str) -> dict[str, Any]:
    return {
        "StatementID": None,
        "AccountID": 1,
        "Date": "2026-08-28",
        "Amount": 10.0,
        "Balance": 100.0,
        "Description": "Example",
        "MD5": md5hash,
        "CategoryID": None,
        "Verified": 0,
        "ConfidenceScore": None,
    }


def test_duplicate_insert_is_detected_at_flush_and_savepoint_keeps_session_usable(tmp_path: Path) -> None:
    Session = create_database(tmp_path / "duplicates.db")

    with Session() as session, session.begin():
        query.insert_rows_carefully(
            session,
            Transactions,
            [_transaction_row("same"), _transaction_row("same"), _transaction_row("new")],
            skip_duplicates=True,
        )

    with Session() as session:
        assert session.scalar(select(func.count()).select_from(Transactions)) == 2


def test_duplicate_insert_raises_when_skipping_is_disabled(tmp_path: Path) -> None:
    Session = create_database(tmp_path / "strict-duplicates.db")

    with pytest.raises(IntegrityError), Session() as session, session.begin():
        query.insert_rows_carefully(
            session,
            Transactions,
            [_transaction_row("same"), _transaction_row("same")],
            skip_duplicates=False,
        )


class _SessionContext(AbstractContextManager[object]):
    def __enter__(self) -> object:
        return object()

    def __exit__(self, *_args: object) -> None:
        return None


def _processor() -> StatementProcessor:
    return StatementProcessor(lambda: _SessionContext(), SimpleNamespace(metadata={}))


def _statement(source: Path) -> Statement:
    return Statement(
        start_date=datetime(2026, 7, 1),
        end_date=datetime(2026, 7, 31),
        accounts=[
            Account(
                account_num="1234",
                start_balance=0.0,
                end_balance=0.0,
                transactions=[],
                account_id=1,
                account_name="Checking",
            )
        ],
        plugin_name="example",
        fpath=source,
    )


def _prepare_import(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[StatementProcessor, Path, list[str]]:
    source = tmp_path / "statement.pdf"
    source.write_bytes(b"statement")
    statement = _statement(source)
    processor = _processor()
    events: list[str] = []

    monkeypatch.setattr(settings, "db_path", tmp_path / "parsetrail.db")
    monkeypatch.setattr("parsetrail.core.statements.hash_file", lambda _path: "file-hash")
    monkeypatch.setattr(
        "parsetrail.core.statements.parse_any",
        lambda *_args, **_kwargs: ParseResult(statement=statement, plugin_name="example"),
    )
    monkeypatch.setattr(processor, "file_already_imported", lambda _hash: "")
    monkeypatch.setattr(processor, "statement_already_imported", lambda _name: False)
    monkeypatch.setattr(processor, "attach_account_info", lambda _statement: None)
    monkeypatch.setattr(
        processor,
        "complete_data_transaction",
        lambda _session, _statement: events.append("database-committed"),
    )
    return processor, source, events


def test_database_commit_happens_before_source_archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    processor, source, events = _prepare_import(tmp_path, monkeypatch)

    def move(_source: Path, _destination: Path) -> None:
        events.append("source-archived")

    monkeypatch.setattr(processor, "move_file_safely", move)

    assert processor.import_one(source) == "success"
    assert events == ["database-committed", "source-archived"]


def test_archive_failure_after_commit_leaves_source_for_deterministic_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    processor, source, events = _prepare_import(tmp_path, monkeypatch)

    def fail_move(_source: Path, _destination: Path) -> None:
        events.append("archive-failed")
        raise OSError("injected archive failure")

    monkeypatch.setattr(processor, "move_file_safely", fail_move)

    with pytest.raises(ArchivePendingError, match="source remains recoverable"):
        processor.import_one(source)

    assert events == ["database-committed", "archive-failed"]
    assert source.read_bytes() == b"statement"


def test_database_failure_leaves_source_in_import_folder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    processor, source, events = _prepare_import(tmp_path, monkeypatch)

    def fail_transaction(_session: object, _statement: Statement) -> None:
        events.append("database-failed")
        raise IntegrityError("injected flush failure", {}, RuntimeError("duplicate"))

    monkeypatch.setattr(processor, "complete_data_transaction", fail_transaction)

    with pytest.raises(IntegrityError):
        processor.import_one(source)

    assert events == ["database-failed"]
    assert source.read_bytes() == b"statement"


def test_parse_failure_leaves_source_available_for_failure_recovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "unrecognized.pdf"
    source.write_bytes(b"statement")
    processor = _processor()
    monkeypatch.setattr(processor, "file_already_imported", lambda _hash: "")
    monkeypatch.setattr("parsetrail.core.statements.parse_any", lambda *_args, **_kwargs: 1 / 0)

    with pytest.raises(ZeroDivisionError):
        processor.import_one(source)

    assert source.read_bytes() == b"statement"


def test_duplicate_retry_recovers_missing_success_archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "db_path", tmp_path / "parsetrail.db")
    processor = _processor()
    source = settings.import_dir / "retry.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"statement")

    processor.handle_duplicate(source, "Checking_20260701_20260731.pdf")

    recovered = settings.success_dir / "Checking_20260701_20260731.pdf"
    assert recovered.read_bytes() == b"statement"
    assert not source.exists()


def test_startup_scan_reports_committed_file_awaiting_archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "db_path", tmp_path / "parsetrail.db")
    processor = StatementProcessor(
        lambda: _SessionContext(),
        SimpleNamespace(metadata={"example": {"SUFFIX": ".pdf"}}),
    )
    source = settings.import_dir / "pending.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"statement")
    monkeypatch.setattr(processor, "file_already_imported", lambda _hash: "archived.pdf")

    pending = processor.find_pending_archives()

    assert pending == [(source, settings.success_dir / "archived.pdf")]


def test_multi_account_statement_hash_resolves_one_archive_name(monkeypatch: pytest.MonkeyPatch) -> None:
    processor = _processor()
    monkeypatch.setattr(
        query,
        "statements_with_hash",
        lambda _session, _hash: [(10, "shared.pdf"), (11, "shared.pdf")],
    )

    assert processor.file_already_imported("same-file") == "shared.pdf"
