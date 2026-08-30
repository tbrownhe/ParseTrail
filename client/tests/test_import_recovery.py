import hashlib
from contextlib import AbstractContextManager
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from parsetrail.core import query
from parsetrail.core.migrate import upgrade_db
from parsetrail.core.orm import (
    Accounts,
    AccountTypes,
    Statements,
    StatementTransactions,
    Transactions,
    create_database,
)
from parsetrail.core.parser_routing import ParseResult
from parsetrail.core.settings import settings
from parsetrail.core.statements import ArchivePendingError, SourceFileAction, StatementProcessor
from parsetrail.core.validation import Account, Statement, Transaction
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError


def _transaction_row(fingerprint_seed: str) -> dict[str, Any]:
    return {
        "AccountID": 1,
        "TransactionDate": date(2026, 8, 28),
        "PostingDate": date(2026, 8, 28),
        "Amount": Decimal("10.00"),
        "Balance": Decimal("100.00"),
        "CurrencyCode": "USD",
        "Description": "Example",
        "Fingerprint": hashlib.sha256(fingerprint_seed.encode()).hexdigest(),
        "FingerprintVersion": 1,
        "CategoryID": None,
        "Verified": False,
        "ConfidenceScore": None,
    }


def _empty_database(path: Path):
    upgrade_db(path)
    Session = create_database(path)
    with Session() as session:
        session.add(AccountTypes(AccountTypeID=1, AccountType="Checking", AssetType="Asset"))
        session.add(
            Accounts(
                AccountID=1,
                AccountName="Checking",
                AccountTypeID=1,
                CurrencyCode="USD",
                Company="Example",
                Description="Fixture",
                AppreciationRate=Decimal(0),
            )
        )
        session.commit()
    return Session


def test_duplicate_insert_is_detected_at_flush_and_savepoint_keeps_session_usable(tmp_path: Path) -> None:
    Session = _empty_database(tmp_path / "duplicates.db")

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
    Session = _empty_database(tmp_path / "strict-duplicates.db")

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
        start_date=date(2026, 7, 1),
        end_date=date(2026, 7, 31),
        accounts=[
            Account(
                account_num="1234",
                start_balance=Decimal("0.00"),
                end_balance=Decimal("0.00"),
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
    monkeypatch.setattr(
        processor,
        "_content_hashes",
        lambda _path: {"sha256": "f" * 64, "md5": "f" * 32},
    )
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


def test_copy_action_commits_then_archives_a_copy_and_retains_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    processor, source, events = _prepare_import(tmp_path, monkeypatch)

    def copy(source_path: Path, destination: Path) -> None:
        events.append("archive-copied")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source_path.read_bytes())

    monkeypatch.setattr(processor, "copy_file_safely", copy)

    assert processor.import_one(source, source_action=SourceFileAction.COPY) == "success"
    assert events == ["database-committed", "archive-copied"]
    assert source.read_bytes() == b"statement"
    assert next(settings.success_dir.iterdir()).read_bytes() == b"statement"


def test_leave_in_place_action_commits_without_touching_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    processor, source, events = _prepare_import(tmp_path, monkeypatch)
    monkeypatch.setattr(
        processor,
        "move_file_safely",
        lambda *_args: pytest.fail("leave-in-place must not move the source"),
    )
    monkeypatch.setattr(
        processor,
        "copy_file_safely",
        lambda *_args: pytest.fail("leave-in-place must not copy the source"),
    )

    assert processor.import_one(source, source_action=SourceFileAction.LEAVE_IN_PLACE) == "success"
    assert events == ["database-committed"]
    assert source.read_bytes() == b"statement"
    assert not settings.success_dir.exists()


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

    outcome = processor.handle_duplicate(source, "Checking_20260701_20260731.pdf")

    recovered = settings.success_dir / "Checking_20260701_20260731.pdf"
    assert outcome == "recovered"
    assert recovered.read_bytes() == b"statement"
    assert not source.exists()


def test_duplicate_copy_recovers_archive_without_removing_original(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "db_path", tmp_path / "parsetrail.db")
    processor = _processor()
    source = tmp_path / "Downloads" / "retry.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"statement")

    outcome = processor.handle_duplicate(
        source,
        "Checking_20260701_20260731.pdf",
        source_action=SourceFileAction.COPY,
    )

    assert outcome == "recovered"
    assert source.read_bytes() == b"statement"
    assert (settings.success_dir / "Checking_20260701_20260731.pdf").read_bytes() == b"statement"


def test_duplicate_copy_retains_original_when_archive_exists(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "db_path", tmp_path / "parsetrail.db")
    processor = _processor()
    archive = settings.success_dir / "Checking_20260701_20260731.pdf"
    archive.parent.mkdir(parents=True)
    archive.write_bytes(b"statement")
    source = tmp_path / "Downloads" / "duplicate.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"statement")

    outcome = processor.handle_duplicate(
        source,
        archive.name,
        source_action=SourceFileAction.COPY,
    )

    assert outcome == "duplicate"
    assert source.read_bytes() == b"statement"
    assert not settings.duplicate_dir.exists()


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
        "statements_with_hashes",
        lambda _session, _hashes: [(10, "shared.pdf"), (11, "shared.pdf")],
    )

    assert processor.file_already_imported({"sha256": "same-file"}) == "shared.pdf"


def test_overlapping_statements_share_transaction_and_keep_both_memberships(tmp_path: Path) -> None:
    Session = _empty_database(tmp_path / "overlap.db")
    manager = SimpleNamespace(
        metadata={
            "csv_fixture": {
                "PLUGIN_NAME": "csv_fixture",
                "VERSION": "1.0.0",
                "SUFFIX": ".csv",
                "COMPANY": "Example",
                "STATEMENT_TYPE": "Checking",
            }
        }
    )
    processor = StatementProcessor(Session, manager)

    def overlapping_statement(filename: str, content_hash: str) -> Statement:
        account = Account(
            account_num="fixture-account",
            start_balance=Decimal("100.00"),
            end_balance=Decimal("112.34"),
            transactions=[
                Transaction(
                    transaction_date=date(2026, 8, 15),
                    posting_date=date(2026, 8, 15),
                    amount=Decimal("12.34"),
                    balance=Decimal("112.34"),
                    desc="Overlapping transaction",
                )
            ],
            account_id=1,
            account_name="Checking",
        )
        account.hash_transactions()
        return Statement(
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 31),
            accounts=[account],
            plugin_name="csv_fixture",
            dpath=tmp_path / filename,
            content_hash=content_hash,
        )

    with Session() as session:
        processor.complete_data_transaction(session, overlapping_statement("first.csv", "a" * 64))
    with Session() as session:
        processor.complete_data_transaction(session, overlapping_statement("second.csv", "b" * 64))

    with Session() as session:
        assert session.scalar(select(func.count()).select_from(Statements)) == 2
        assert session.scalar(select(func.count()).select_from(Transactions)) == 1
        assert session.scalar(select(func.count()).select_from(StatementTransactions)) == 2
        assert session.scalars(select(Statements.TransactionCount)).all() == [1, 1]
