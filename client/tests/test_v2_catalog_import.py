"""A verified definition reaches the pending source store without ledger effects."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from parsetrail.core.v2_catalog_admission import admit_pilot_definition
from parsetrail.core.v2_data_catalog import key_id_for_public_key, verify_catalog
from parsetrail.core.v2_profile_store import V2ProfileStore
from parsetrail.core.v2_source_import import CatalogImportError, ImportCancelled, import_catalog_source
from parsetrail.core.v2_source_pipeline import build_source_evidence

DEFINITION = Path(__file__).parents[2] / "devtools" / "v2_fresh_slice" / "synthetic-posted-cash-definition.json"
SOURCE = (
    b"Date,Account,Description,Amount,ReportedBalance\n"
    b"10/01/2026,Checking A,Paycheck,$1200.00,$2200.00\n"
    b"10/02/2026,Checking A,Groceries,-$57.43,$2142.57\n"
)


def _verified_catalog(contents: tuple[bytes, ...] | None = None):
    contents = contents or (DEFINITION.read_bytes(),)
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    key_id = key_id_for_public_key(public_key)
    snapshot = json.dumps(
        {
            "schema_version": 1,
            "engine_contract": 1,
            "release_sequence": 1,
            "source_revision": "a" * 40,
            "key_id": key_id,
            "definitions": sorted(
                (
                    {
                        "parser_id": identity.parser_id,
                        "revision": identity.revision,
                        "suffix": identity.suffix,
                        "size": len(content),
                        "sha256": hashlib.sha256(content).hexdigest(),
                        "content_base64": base64.b64encode(content).decode("ascii"),
                    }
                    for content in contents
                    for identity in (admit_pilot_definition(content),)
                ),
                key=lambda item: item["parser_id"],
            ),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return verify_catalog(snapshot, private_key.sign(snapshot), {key_id: public_key}, admit_pilot_definition)


def test_verified_catalog_definition_imports_once_and_reopens_exact_snapshot(tmp_path: Path) -> None:
    catalog = _verified_catalog()
    calls = 0

    def parse(source: bytes, definition: bytes, *, suffix: str, cancelled=None):
        nonlocal calls
        calls += 1
        return build_source_evidence(source, definition, suffix=suffix, cancelled=cancelled)

    with V2ProfileStore.create(tmp_path / "fresh.db") as store:
        first = import_catalog_source(
            store,
            SOURCE,
            catalog=catalog,
            parser_id="synthetic_posted_cash_csv",
            suffix=".csv",
            parse=parse,
        )
        second = import_catalog_source(
            store,
            SOURCE,
            catalog=catalog,
            parser_id="synthetic_posted_cash_csv",
            suffix=".csv",
            parse=parse,
        )
        saved = store.load_import(first.source_sha256)
        assert first.status == "imported"
        assert second.status == "already_imported"
        assert calls == 1
        assert saved.source == SOURCE
        assert saved.definition == DEFINITION.read_bytes()
        assert saved.evidence == first.evidence == second.evidence
        assert store.connection.execute("SELECT count(*) FROM SourceObservations").fetchone() == (2,)


def test_verified_catalog_uses_installed_parser_by_default(tmp_path: Path) -> None:
    with V2ProfileStore.create(tmp_path / "fresh.db") as store:
        result = import_catalog_source(
            store,
            SOURCE,
            catalog=_verified_catalog(),
            parser_id="synthetic_posted_cash_csv",
            suffix=".csv",
        )
        assert result.status == "imported"
        assert len(result.evidence.payload.rows) == 2
        assert store.load_import(result.source_sha256).evidence == result.evidence


def test_unique_csv_auto_selection_and_ambiguous_refusal(tmp_path: Path) -> None:
    original = DEFINITION.read_bytes()
    alternate = json.loads(original)
    alternate["parser_id"] = "synthetic_posted_cash_csv_alt"
    alternate_bytes = json.dumps(alternate).encode()
    with V2ProfileStore.create(tmp_path / "fresh.db") as store:
        selected = import_catalog_source(store, SOURCE, catalog=_verified_catalog(), suffix=".csv")
        assert selected.status == "imported"
        assert selected.evidence.parser_id == "synthetic_posted_cash_csv"
    with V2ProfileStore.create(tmp_path / "ambiguous.db") as store:
        with pytest.raises(CatalogImportError, match="catalog_ambiguous_match"):
            import_catalog_source(store, SOURCE, catalog=_verified_catalog((original, alternate_bytes)), suffix=".csv")
        assert store.connection.execute("SELECT count(*) FROM Sources").fetchone() == (0,)


def test_auto_selection_refuses_missing_csv_match_and_pdf_without_rule(tmp_path: Path) -> None:
    with V2ProfileStore.create(tmp_path / "fresh.db") as store:
        with pytest.raises(CatalogImportError, match="catalog_no_match"):
            import_catalog_source(store, b"Wrong,Header\n1,2\n", catalog=_verified_catalog(), suffix=".csv")
        with pytest.raises(CatalogImportError, match="automatic_pdf_routing_unavailable"):
            import_catalog_source(store, b"%PDF-1.4\n", catalog=_verified_catalog(), suffix=".pdf")
        assert store.connection.execute("SELECT count(*) FROM Sources").fetchone() == (0,)


def test_both_current_mohela_csv_formats_select_their_own_definition(tmp_path: Path) -> None:
    definitions = tuple(
        (Path(__file__).parents[2] / "devtools" / "parser_engine_pilot" / name).read_bytes()
        for name in ("mohela-account-history-definition.json", "mohela-pilot-definition.json")
    )
    catalog = _verified_catalog(definitions)
    sources = (
        (
            b'<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.0 Transitional//EN">'
            b"Date,Description,Principal,Interest,Fees,Total,\n"
            b"10/01/2026,Payment,-$80.00,-$20.00,$0.00,-$100.00,\n",
            "mohela_account_history_export",
        ),
        (
            b'<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.0 Transitional//EN">'
            b"Date,LoanName,Description,Principal,Interest,Fees,Total,UnpaidPrincipalBalanceValue,\n"
            b"10/01/2026,123-1 Loan A,Payment,-$80.00,-$20.00,$0.00,-$100.00,$900.00,\n",
            "mohela_detailed_export",
        ),
    )
    for index, (source, expected_id) in enumerate(sources):
        with V2ProfileStore.create(tmp_path / f"mohela-{index}.db") as store:
            result = import_catalog_source(store, source, catalog=catalog, suffix=".csv")
            assert result.evidence.parser_id == expected_id
            assert len(result.evidence.payload.rows) == 1
            assert store.load_import(result.source_sha256).evidence == result.evidence


def test_catalog_selection_and_evidence_identity_refuse_before_write(tmp_path: Path) -> None:
    catalog = _verified_catalog()
    with V2ProfileStore.create(tmp_path / "fresh.db") as store:
        with pytest.raises(CatalogImportError, match="catalog_definition_unavailable"):
            import_catalog_source(
                store,
                SOURCE,
                catalog=catalog,
                parser_id="wrong_parser",
                suffix=".csv",
                parse=build_source_evidence,
            )
        with pytest.raises(CatalogImportError, match="catalog_definition_unavailable"):
            import_catalog_source(
                store,
                SOURCE,
                catalog=catalog,
                parser_id="synthetic_posted_cash_csv",
                suffix=".pdf",
                parse=build_source_evidence,
            )

        def changed_identity(source: bytes, definition: bytes, *, suffix: str, cancelled=None):
            evidence = build_source_evidence(source, definition, suffix=suffix, cancelled=cancelled)
            return evidence.model_copy(update={"parser_id": "wrong_parser"})

        with pytest.raises(CatalogImportError, match="catalog_evidence_mismatch"):
            import_catalog_source(
                store,
                SOURCE,
                catalog=catalog,
                parser_id="synthetic_posted_cash_csv",
                suffix=".csv",
                parse=changed_identity,
            )
        assert store.connection.execute("SELECT count(*) FROM Sources").fetchone() == (0,)


@pytest.mark.parametrize("parser_id", [None, "synthetic_posted_cash_csv"])
def test_catalog_import_cancelled_during_parser_keeps_profile_empty(tmp_path: Path, parser_id: str | None) -> None:
    catalog = _verified_catalog()
    parsing = False

    def cancelled() -> bool:
        return parsing

    def parse(source: bytes, definition: bytes, *, suffix: str, cancelled=None):
        nonlocal parsing
        parsing = True
        return build_source_evidence(source, definition, suffix=suffix, cancelled=cancelled)

    with V2ProfileStore.create(tmp_path / "fresh.db") as store:
        with pytest.raises(ImportCancelled, match="cancelled"):
            import_catalog_source(
                store,
                SOURCE,
                catalog=catalog,
                parser_id=parser_id,
                suffix=".csv",
                parse=parse,
                cancelled=cancelled,
            )
        assert store.connection.execute("SELECT count(*) FROM Sources").fetchone() == (0,)
