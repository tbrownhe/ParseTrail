"""Recognized formats remain previews until one bound declaration is imported."""

from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError, replace
from datetime import date

import pytest
from parsetrail.core import v2_pdf_routing, v2_source_pipeline
from parsetrail.core.v2_bounded_pdf_text import DecodedPDFText
from parsetrail.core.v2_format_recognition import (
    CatalogImportError,
    ImportCancelled,
    recognize_catalog_source,
)
from parsetrail.core.v2_profile_store import V2ProfileStore
from parsetrail.core.v2_source_import import import_catalog_source
from parsetrail.core.v2_source_pipeline import SourcePipelineError, build_source_evidence

from .test_v2_catalog_import import DEFINITION, SOURCE, _verified_catalog


def _alternate(*, change_mapping=False):
    alternate = json.loads(DEFINITION.read_bytes())
    alternate["parser_id"] = "synthetic_other_csv"
    if change_mapping:
        alternate["columns"]["total"], alternate["columns"]["balance"] = (
            alternate["columns"]["balance"],
            alternate["columns"]["total"],
        )
    return json.dumps(alternate).encode()


def test_discovery_is_read_only_and_preview_preserves_exact_values_and_locations(tmp_path, monkeypatch):
    source = b"Date,Account,Description,Amount,ReportedBalance\n" + b"".join(
        f"10/{day:02d}/2026,Checking A,Repeated purchase,-$4.01,$995.99\n".encode() for day in range(1, 11)
    )
    profile = tmp_path / "empty.db"
    with V2ProfileStore.create(profile):
        pass
    before = profile.read_bytes()

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Recognition must not open a profile")

    monkeypatch.setattr(V2ProfileStore, "open", forbidden)
    result = recognize_catalog_source(source, catalog=_verified_catalog(), suffix=".csv")
    assert result.source_sha256 == hashlib.sha256(source).hexdigest()
    assert len(result.candidates) == 1 and profile.read_bytes() == before
    candidate = result.candidates[0]
    assert candidate.institution_key is None  # A generic CSV does not identify a bank.
    assert candidate.row_count == 10 and len(candidate.preview_rows) == 5
    assert candidate.start.iso == "2026-10-01" and candidate.end.iso == "2026-10-10"
    assert dict(candidate.column_mapping)["total"] == "Amount"
    first = candidate.preview_rows[0]
    assert first.amount.minor == -401 and first.amount.raw == "-$4.01"
    assert first.running_balance.minor == 99599
    assert first.date.iso == "2026-10-01" and first.date.raw == "10/01/2026"
    assert first.locations[0].row == 2 and first.amount.locations[0].column == 4
    assert len({row.row_id for row in candidate.preview_rows}) == 5
    assert not hasattr(candidate, "evidence")
    with pytest.raises(FrozenInstanceError):
        candidate.row_count = 9


def test_ambiguous_candidates_show_different_interpretations_and_import_only_chosen(tmp_path):
    catalog = _verified_catalog((DEFINITION.read_bytes(), _alternate(change_mapping=True)))
    recognition = recognize_catalog_source(SOURCE, catalog=catalog, suffix=".csv")
    assert len(recognition.candidates) == 2
    candidates = {candidate.parser_id: candidate for candidate in recognition.candidates}
    usual = candidates["synthetic_posted_cash_csv"]
    other = candidates["synthetic_other_csv"]
    assert usual.preview_rows[0].amount.minor == 120000
    assert other.preview_rows[0].amount.minor == 220000
    assert dict(other.column_mapping)["total"] == "ReportedBalance"
    calls = []

    def parse(source, definition, *, suffix, cancelled=None):
        calls.append(json.loads(definition)["parser_id"])
        return build_source_evidence(source, definition, suffix=suffix, cancelled=cancelled)

    with V2ProfileStore.create(tmp_path / "selected.db") as store:
        assert not store.source_ids()
        result = import_catalog_source(
            store,
            SOURCE,
            catalog=catalog,
            suffix=".csv",
            selection=recognition.selection("synthetic_posted_cash_csv"),
            parse=parse,
        )
        assert calls == ["synthetic_posted_cash_csv"]
        assert result.evidence.payload.rows[0].amount.minor == 120000
        assert store.load_import(result.source_sha256).definition == DEFINITION.read_bytes()
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
        assert store.account_bindings(result.source_sha256)[0].ledger_account_id is None
        # The choice made from the format preview has not assigned any accounts.
        assert not store.financial_accounts()


@pytest.mark.parametrize("source", [b"Wrong,Header\n1,2\n", SOURCE.replace(b"-$57.43", b"not-money")])
def test_header_or_later_row_failure_produces_no_candidate(source):
    result = recognize_catalog_source(source, catalog=_verified_catalog(), suffix=".csv")
    assert result.candidates == ()
    with pytest.raises(CatalogImportError, match="catalog_definition_unavailable"):
        result.selection("synthetic_posted_cash_csv")


@pytest.mark.parametrize(
    "header",
    [
        b"Account,Date,Description,Amount,ReportedBalance",  # same names, different order
        b"Date,Account,Description,TransactionAmount,ReportedBalance",
        b"Date,Account,Description,Amount,ReportedBalance,Extra",
        b"Date,Account,Description,Amount",
        b"Date,Account,Description,amount,ReportedBalance",
        b"Date,Account,Description, Amount,ReportedBalance",
        b"Date,Account,Description,Amount,Amount",
    ],
)
def test_csv_routing_requires_exact_declared_ordered_headers(header):
    source = header + b"\n" + SOURCE.split(b"\n", 1)[1]
    recognition = recognize_catalog_source(source, catalog=_verified_catalog(), suffix=".csv")
    assert recognition.candidates == ()


def test_preview_cancellation_checks_before_and_after_candidate_parse():
    catalog = _verified_catalog()
    with pytest.raises(ImportCancelled):
        recognize_catalog_source(SOURCE, catalog=catalog, suffix=".csv", cancelled=lambda: True)
    state = {"cancelled": False}

    def parse(source, definition, *, suffix, cancelled=None):
        evidence = build_source_evidence(source, definition, suffix=suffix, cancelled=cancelled)
        state["cancelled"] = True
        return evidence

    with pytest.raises(ImportCancelled):
        recognize_catalog_source(
            SOURCE,
            catalog=catalog,
            suffix=".csv",
            parse=parse,
            cancelled=lambda: state["cancelled"],
        )


@pytest.mark.parametrize(
    "field,value", [("source_sha256", "0" * 64), ("definition_revision", "2"), ("parser_id", "wrong_parser")]
)
def test_preview_refuses_changed_evidence_identity(field, value):
    def parse(source, definition, *, suffix, cancelled=None):
        return build_source_evidence(source, definition, suffix=suffix, cancelled=cancelled).model_copy(
            update={field: value}
        )

    with pytest.raises(CatalogImportError, match="catalog_evidence_mismatch"):
        recognize_catalog_source(SOURCE, catalog=_verified_catalog(), suffix=".csv", parse=parse)


@pytest.mark.parametrize("change", ["source", "catalog", "parser", "revision", "definition", "suffix"])
def test_stale_or_changed_selection_refuses_before_write_and_before_saved_retry(tmp_path, change):
    catalog = _verified_catalog()
    selection = recognize_catalog_source(SOURCE, catalog=catalog, suffix=".csv").selection("synthetic_posted_cash_csv")
    source = SOURCE
    if change == "source":
        source = SOURCE.replace(b"Groceries", b"Food")
    elif change == "catalog":
        catalog = _verified_catalog()  # Another valid signed snapshot, even with the same definition.
    else:
        field, value = {
            "parser": ("parser_id", "wrong_parser"),
            "revision": ("revision", "2"),
            "definition": ("definition_sha256", "0" * 64),
            "suffix": ("suffix", ".pdf"),
        }[change]
        selection = replace(selection, **{field: value})
    with V2ProfileStore.create(tmp_path / "fresh.db") as store:
        with pytest.raises(CatalogImportError, match="catalog_selection_"):
            import_catalog_source(store, source, catalog=catalog, suffix=".csv", selection=selection)
        assert not store.source_ids()
        import_catalog_source(store, SOURCE, catalog=catalog, suffix=".csv")
        before = store.load_import(hashlib.sha256(SOURCE).hexdigest())
        with pytest.raises(CatalogImportError, match="catalog_selection_"):
            import_catalog_source(store, source, catalog=catalog, suffix=".csv", selection=selection)
        assert store.load_import(before.evidence.source_sha256) == before


def test_selected_commit_revalidates_contents_and_cancel_does_not_write(tmp_path):
    catalog = _verified_catalog()
    selection = recognize_catalog_source(SOURCE, catalog=catalog, suffix=".csv").selection("synthetic_posted_cash_csv")

    def refused(*_args, **_kwargs):
        raise SourcePipelineError("synthetic_refusal")

    with V2ProfileStore.create(tmp_path / "fresh.db") as store:
        with pytest.raises(SourcePipelineError, match="synthetic_refusal"):
            import_catalog_source(store, SOURCE, catalog=catalog, suffix=".csv", selection=selection, parse=refused)
        with pytest.raises(ImportCancelled):
            import_catalog_source(
                store, SOURCE, catalog=catalog, suffix=".csv", selection=selection, cancelled=lambda: True
            )
        assert not store.source_ids()


def test_pdf_preview_uses_unique_signed_route_and_selection_still_checks_route(tmp_path, monkeypatch):
    from devtools.parser_engine_pilot.test_savings_lines import pages

    definitions = tuple(
        (DEFINITION.parents[1] / "parser_engine_pilot" / name).read_bytes()
        for name in ("happen-savings-pilot-definition.json", "lendingclub-savings-pilot-definition.json")
    )
    catalog = _verified_catalog(definitions)
    decoded = DecodedPDFText(
        ("Summary of Accounts\n" + pages()[0], pages()[1]), (("Creator", "VCTransaction"), ("Title", "StmtAPISvc"))
    )
    monkeypatch.setattr(v2_pdf_routing, "decode_pdf", lambda _source, *, cancelled=None: decoded)
    monkeypatch.setattr(v2_source_pipeline, "decode_pdf", lambda _source, *, cancelled=None: decoded)
    recognition = recognize_catalog_source(b"%PDF-synthetic", catalog=catalog, suffix=".pdf")
    candidate = recognition.candidates[0]
    assert len(recognition.candidates) == 1 and candidate.parser_id == "happen_savings_line_pilot"
    assert candidate.header == () and candidate.column_mapping == ()
    assert candidate.start.iso is not None and date.fromisoformat(candidate.start.iso)
    assert candidate.preview_rows[0].locations[0].kind == "pdf_line"
    selection = recognition.selection(candidate.parser_id)
    with V2ProfileStore.create(tmp_path / "fresh.db") as store:
        other = next(item for item in catalog.definitions if item.identity.parser_id != candidate.parser_id)
        wrong = replace(
            selection,
            parser_id=other.identity.parser_id,
            revision=other.identity.revision,
            definition_sha256=other.sha256,
        )
        with pytest.raises(CatalogImportError, match="catalog_selected_route_mismatch"):
            import_catalog_source(store, b"%PDF-synthetic", catalog=catalog, suffix=".pdf", selection=wrong)
        assert not store.source_ids()
        imported = import_catalog_source(store, b"%PDF-synthetic", catalog=catalog, suffix=".pdf", selection=selection)
        assert imported.evidence.parser_id == candidate.parser_id


def test_xlsx_is_not_admitted_by_recognition():
    with pytest.raises(SourcePipelineError, match="unsupported_source_kind"):
        recognize_catalog_source(b"xlsx-like", catalog=_verified_catalog(), suffix=".xlsx")
