"""Successful synthetic families through signed routing, real workers and storage.

This is source-runtime evidence on the tested platform, never a frozen/installed,
private source parity, complete-capture or accounting acceptance claim. A local
fixture isolates HOME/USERPROFILE and keyring even when run without client tests.
All profile writes below additionally use pytest's disposable tmp_path.
"""

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
from parsetrail.core.v2_source_pipeline import SourcePipelineError

from devtools.parser_engine_pilot.synthetic_family_sources import (
    FamilySource,
    family_sources,
    occu_annotation_source,
    pdf_document,
    text_page,
)

ROOT = Path(__file__).parent
SOURCES = family_sources()


# Independently specified facts printed in the public synthetic inputs. Values
# are integer minor units; expected results never call a parser or decoder.
# Row tuple: date, amount, date provenance, row role, date role.
def row(day, amount, provenance="derived", role="activity", date_role="posting_date"):
    return day, amount, provenance, role, date_role


def summary(day, amount):
    return row(day, amount, role="period_summary", date_role="statement_period_end")


EXPECTED = {
    "chase-card-pilot-definition.json": (
        "chase_card_line_pilot",
        "account_total",
        ((-2500, -3000),),
        (row("2026-03-16", -1000, "assumed"), row("2026-04-01", 500, "assumed")),
    ),
    "happen-savings-pilot-definition.json": (
        "happen_savings_line_pilot",
        "account_total",
        ((10000, 11000),),
        (row("2026-09-20", 1000),),
    ),
    "lendingclub-savings-pilot-definition.json": (
        "lendingclub_savings_line_pilot",
        "account_total",
        ((10000, 11600),),
        (row("2026-09-20", 2000), row("2026-09-22", -500), row("2026-10-15", 100)),
    ),
    "hsa-cash-pilot-definition.json": (
        "hsa_cash_line_pilot",
        "cash_component",
        ((100000, 110010),),
        (
            row("2026-08-10", 20000, "observed"),
            row("2026-08-20", -10000, "observed"),
            row("2026-08-31", 10, "observed"),
        ),
    ),
    "fidelity-hsa-summary-pilot-definition.json": (
        "pdf_fidelityhsa_202001",
        "account_total",
        ((10000, 14500),),
        (summary("2026-01-31", 5000), summary("2026-01-31", -1000), summary("2026-01-31", 500)),
    ),
    "capital-one-loan-pilot-definition.json": (
        "pdf_capitaloneauto_202402",
        "principal_component",
        ((None, 950000),),
        (row("2026-01-15", -22000, "observed", date_role="activity_date"),),
    ),
    "fidelity-401k-summary-pilot-definition.json": (
        "pdf_fidelity401k_201810",
        "account_total",
        ((10000, 14000),),
        (summary("2026-01-31", 5000), summary("2026-01-31", -1000)),
    ),
    "vanguard-summary-pilot-definition.json": (
        "pdf_vanguard_202210",
        "account_total",
        ((10000, 17000),),
        (
            summary("2026-03-31", 5000),
            summary("2026-03-31", 2500),
            summary("2026-03-31", -500),
            summary("2026-03-31", 0),
        ),
    ),
    "occu-bank-pilot-definition.json": (
        "pdf_occubank_201409",
        "account_total",
        ((10000, 11000), (20000, 19500)),
        (row("2026-01-05", 1000), row("2026-01-10", -500)),
    ),
    "occu-card-pilot-definition.json": (
        "pdf_occucc_201904",
        "account_total",
        ((-10000, -9500),),
        (
            row("2026-01-05", -1000),
            row("2026-01-10", 2000),
            row("2026-01-31", -500, role="header_charge", date_role="statement_period_end"),
        ),
    ),
    "legacy-citi-pilot-definition.json": (
        "pdf_citicc_201505",
        "account_total",
        ((-10000, -9000),),
        (row("2026-01-05", 2000, "assumed"), row("2026-01-09", -1000)),
    ),
    "yamaha-card-pilot-definition.json": (
        "pdf_yamahafin_202306",
        "account_total",
        ((-100000, -99000),),
        (row("2026-02-07", -1000), row("2026-02-10", 2000)),
    ),
    "wells-loan-pilot-definition.json": (
        "pdf_wfloanper_202306",
        "principal_component",
        ((-10000, -8000),),
        (
            row("2026-01-15", 100, "observed", date_role="activity_date"),
            row("2026-01-15", 2000, "observed", date_role="activity_date"),
        ),
    ),
    "usbank-rei-card-pilot-definition.json": (
        "pdf_usbankreicc_201405",
        "account_total",
        ((-10000, -9000),),
        (row("2026-01-05", -1000), row("2026-01-10", 2000)),
    ),
    "transamerica-summary-pilot-definition.json": (
        "pdf_transamerica_202104",
        "account_total",
        ((10000, 11500),),
        (
            summary("2026-03-31", 2000),
            summary("2026-03-31", -1000),
            summary("2026-03-31", 0),
            summary("2026-03-31", 500),
        ),
    ),
    "middle-citi-table-pilot-definition.json": (
        "pdf_citicc_202506",
        "account_total",
        ((-10000, -11000),),
        (row("2026-01-02", -1000),),
    ),
    "recent-citi-pilot-definition.json": (
        "pdf_citicc_202511",
        "account_total",
        ((-10000, -11000),),
        (row("2026-01-02", -1000),),
    ),
    "wells-table-pilot-definition.json": (
        "wells_business_table_pilot",
        "account_total",
        ((10000, 10100),),
        (row("2026-10-01", 100),),
    ),
    "wells-personal-table-pilot-definition.json": (
        "pdf_wfbankper_202105",
        "account_total",
        ((10000, 12000),),
        (row("2026-01-05", 2000),),
    ),
    "synchrony-table-pilot-definition.json": (
        "synchrony_amazon_store_card",
        "account_total",
        ((-10000, -11000),),
        (row("2026-01-02", -1000, date_role="activity_date"),),
    ),
    "lendingclub-table-pilot-definition.json": (
        "pdf_lendingclublus_202506",
        "account_total",
        ((10000, 11000),),
        (row("2026-01-05", 1000),),
    ),
    "mohela-account-history-definition.json": (
        "mohela_account_history_export",
        None,
        (),
        (row("2026-10-01", -10000, "observed", date_role="activity_date"),),
    ),
    "mohela-pilot-definition.json": (
        "mohela_detailed_export",
        None,
        (),
        (
            row("2026-10-01", -10000, "observed", date_role="activity_date"),
            row("2026-10-02", -5000, "observed", date_role="activity_date"),
        ),
    ),
}

# Printed statement dates, with explicit derived/unknown exceptions.
PERIODS = {
    "chase_card_line_pilot": ("2026-03-16", "2026-04-15"),
    "happen_savings_line_pilot": ("2026-09-16", "2026-10-15"),
    "lendingclub_savings_line_pilot": ("2026-09-16", "2026-10-15"),
    "hsa_cash_line_pilot": ("2026-08-01", "2026-08-31"),
    "pdf_fidelityhsa_202001": ("2026-01-01", "2026-01-31"),
    "pdf_capitaloneauto_202402": ("2026-01-01", "2026-01-31"),
    "pdf_fidelity401k_201810": ("2026-01-01", "2026-01-31"),
    "pdf_vanguard_202210": ("2026-01-01", "2026-03-31"),
    "pdf_occubank_201409": ("2026-01-01", "2026-01-31"),
    "pdf_occucc_201904": ("2026-01-01", "2026-01-31"),
    "pdf_citicc_201505": ("2026-01-01", "2026-01-31"),
    "pdf_yamahafin_202306": ("2026-02-01", "2026-02-28"),
    "pdf_wfloanper_202306": (None, "2026-01-31"),
    "pdf_usbankreicc_201405": ("2026-01-01", "2026-01-31"),
    "pdf_transamerica_202104": ("2026-01-01", "2026-03-31"),
    "pdf_citicc_202506": ("2026-01-01", "2026-01-31"),
    "pdf_citicc_202511": ("2026-01-01", "2026-01-31"),
    "wells_business_table_pilot": ("2026-10-01", "2026-10-31"),
    "pdf_wfbankper_202105": ("2026-01-01", "2026-01-31"),
    "synchrony_amazon_store_card": ("2026-01-01", "2026-01-31"),
    "pdf_lendingclublus_202506": ("2026-01-01", "2026-01-31"),
}
IDENTITIES = {
    "chase_card_line_pilot": (("1234", "last_four"),),
    "happen_savings_line_pilot": (("1234", "last_four"),),
    "lendingclub_savings_line_pilot": (("1234567890", "full"),),
    "hsa_cash_line_pilot": (("SYNTHETIC-001", "opaque"),),
    "pdf_fidelityhsa_202001": (("123-456789", "full"),),
    "pdf_capitaloneauto_202402": (("1234567890123", "full"),),
    "pdf_fidelity401k_201810": (("My Retirement Plan", "opaque"),),
    "pdf_vanguard_202210": (("123456", "opaque"),),
    "pdf_occubank_201409": (("1234", "last_four"), ("5678", "last_four")),
    "pdf_occucc_201904": (("1234", "last_four"),),
    "pdf_citicc_201505": (("1234", "last_four"),),
    "pdf_yamahafin_202306": (("123456XXXXXX7890", "opaque"),),
    "pdf_wfloanper_202306": (("12345678901234", "full"),),
    "pdf_usbankreicc_201405": (("1234567890123456", "full"),),
    "pdf_transamerica_202104": (("123456", "opaque"),),
    "pdf_citicc_202506": (("1234", "last_four"),),
    "pdf_citicc_202511": (("1234", "last_four"),),
    "wells_business_table_pilot": (("1234567890", "full"),),
    "pdf_wfbankper_202105": (("1234567890", "full"),),
    "synchrony_amazon_store_card": (("1234", "last_four"),),
    "pdf_lendingclublus_202506": (("1234567890", "full"),),
}


def signed_catalog(contents=None):
    """Ephemeral in-memory key; no production trust, activation or key files."""
    definitions = []
    for content in contents or tuple(path.read_bytes() for path in sorted(ROOT.glob("*definition.json"))):
        identity = admit_pilot_definition(content)
        definitions.append(
            {
                "parser_id": identity.parser_id,
                "revision": identity.revision,
                "suffix": identity.suffix,
                "size": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
                "content_base64": base64.b64encode(content).decode("ascii"),
            }
        )
    key = Ed25519PrivateKey.generate()
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    key_id = key_id_for_public_key(public)
    snapshot = json.dumps(
        {
            "schema_version": 1,
            "engine_contract": 1,
            "release_sequence": 1,
            "source_revision": "a" * 40,
            "key_id": key_id,
            "definitions": sorted(definitions, key=lambda item: item["parser_id"]),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return verify_catalog(snapshot, key.sign(snapshot), {key_id: public}, admit_pilot_definition)


@pytest.fixture(scope="module")
def catalog():
    return signed_catalog()


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")


def test_fixture_matrix_equals_all_current_declarations(catalog):
    assert len(SOURCES) == len(EXPECTED) == len(catalog.definitions) == 23
    assert sum(case.suffix == ".pdf" for case in SOURCES) == 21
    assert (
        {case.definition_name for case in SOURCES}
        == set(EXPECTED)
        == {path.name for path in ROOT.glob("*definition.json")}
    )
    assert {item.identity.parser_id for item in catalog.definitions} == {expected[0] for expected in EXPECTED.values()}


@pytest.mark.parametrize("case", SOURCES, ids=lambda case: case.definition_name.removesuffix("-definition.json"))
def test_family_source_routes_decodes_imports_and_reopens(case: FamilySource, catalog, tmp_path):
    definition = (ROOT / case.definition_name).read_bytes()
    expected_id, expected_scope, expected_balances, expected_rows = EXPECTED[case.definition_name]
    profile = tmp_path / "family.db"
    with V2ProfileStore.create(profile) as store:
        result = import_catalog_source(store, case.source, catalog=catalog, suffix=case.suffix)
        assert result.status == "imported"
        evidence = result.evidence
        assert evidence.parser_id == expected_id
        assert evidence.source_sha256 == result.source_sha256 == hashlib.sha256(case.source).hexdigest()
        assert evidence.definition_sha256 == hashlib.sha256(definition).hexdigest()
        assert evidence.definition_revision == json.loads(definition)["revision"]
        payload = evidence.payload
        if case.suffix == ".pdf":
            assert payload.kind == "statement"
            assert payload.capture_verified is False
            assert (payload.start.iso, payload.end.iso) == PERIODS[expected_id]
            start_provenance = "observed"
            if expected_id in {
                "pdf_occucc_201904",
                "pdf_yamahafin_202306",
                "wells_business_table_pilot",
                "pdf_wfbankper_202105",
            }:
                start_provenance = "derived"
            elif expected_id == "pdf_wfloanper_202306":
                start_provenance = "unknown"
            assert (payload.start.provenance, payload.end.provenance) == (start_provenance, "observed")
            assert payload.end.locations
            assert payload.start.locations or start_provenance == "unknown"
            assert (
                tuple((a.source_identity, a.source_identity_form) for a in payload.accounts) == IDENTITIES[expected_id]
            )
            assert (
                tuple((a.opening.minor if a.opening else None, a.closing.minor) for a in payload.accounts)
                == expected_balances
            )
            assert all(a.balance_scope == expected_scope for a in payload.accounts)
            assert all(a.identity_locations for a in payload.accounts)
            assert all(
                value.provenance == "observed" and value.raw and value.locations
                for a in payload.accounts
                for value in (a.opening, a.closing)
                if value is not None
            )
            rows = tuple(r for a in payload.accounts for r in a.rows)
        else:
            assert payload.kind == "activity_export" and payload.coverage_verified is False
            rows = payload.rows
            assert payload.activity_start.iso == "2026-10-01"
            assert payload.activity_end.iso == (
                "2026-10-02" if expected_id == "mohela_detailed_export" else "2026-10-01"
            )
            assert payload.activity_start.provenance == payload.activity_end.provenance == "derived"
        assert (
            tuple((r.date.iso, r.amount.minor, r.date.provenance, r.row_role, r.date_role) for r in rows)
            == expected_rows
        )
        assert len({r.row_id for r in rows}) == len(rows)
        assert all(
            r.amount.provenance == "observed"
            and r.amount.raw
            and r.amount.locations
            and r.date.locations
            and r.fragments
            for r in rows
        )
        assert all(
            fragment.raw_values and fragment.location.kind.startswith("pdf_" if case.suffix == ".pdf" else "csv_")
            for r in rows
            for fragment in r.fragments
        )
        _assert_family_specific_unknowns_and_components(expected_id, payload, rows)
        saved = store.load_import(result.source_sha256)
        assert (saved.source, saved.definition, saved.evidence) == (case.source, definition, evidence)
        assert store.connection.execute("SELECT count(*) FROM SourceObservations").fetchone() == (len(rows),)
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
        assert store.connection.execute("SELECT count(*) FROM JournalAllocations").fetchone() == (0,)
        retry = import_catalog_source(store, case.source, catalog=catalog, suffix=case.suffix)
        assert retry.status == "already_imported" and retry.evidence == evidence
        assert store.connection.execute("SELECT count(*) FROM SourceObservations").fetchone() == (len(rows),)
    with V2ProfileStore.open(profile, read_only=True) as reopened:
        saved = reopened.load_import(result.source_sha256)
        assert (saved.source, saved.definition, saved.evidence) == (case.source, definition, evidence)
        assert reopened.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)


def _assert_family_specific_unknowns_and_components(parser_id, payload, rows):
    if parser_id == "pdf_capitaloneauto_202402":
        assert payload.accounts[0].opening is None
        assert [(p.role, p.amount.minor) for p in rows[0].components] == [("principal", -20000), ("interest", -2000)]
    if parser_id == "pdf_wfloanper_202306":
        assert payload.start.iso is None and payload.start.provenance == "unknown"
        assert [p.role for r in rows for p in r.components] == ["interest", "principal"]
    if parser_id == "hsa_cash_line_pilot":
        assert rows[-1].description.text is None and rows[-1].description.provenance == "unknown"
        assert [r.running_balance.minor for r in rows] == [120000, 110000, 110010]
    if parser_id == "chase_card_line_pilot":
        assert [r.transaction_date.iso for r in rows] == ["2026-03-15", "2026-04-01"]
        assert "dated_auxiliary_uninterpreted" in {d.code for d in payload.dispositions}
    if parser_id == "pdf_usbankreicc_201405":
        assert rows[0].transaction_date.iso == "2026-01-04" and rows[1].transaction_date is None
    if parser_id == "pdf_yamahafin_202306":
        assert [r.transaction_date.iso for r in rows] == ["2026-02-05", "2026-02-09"]
    if parser_id == "pdf_citicc_202511":
        assert [f.channel for f in rows[0].fragments] == ["table", "text"]
    if parser_id == "pdf_lendingclublus_202506":
        assert {d.code for d in payload.dispositions} >= {
            "prior_period_average_balance",
            "summary_values_tail",
            "interest_earned_summary",
            "savings_rate_disclosure",
        }
    if parser_id == "synchrony_amazon_store_card":
        assert rows[0].posting_date_guess.iso == "2026-01-02" and rows[0].posting_date_guess.provenance == "assumed"
    if parser_id.startswith("mohela_"):
        assert [(p.role, p.amount.minor) for p in rows[0].components] == [
            ("principal", -8000),
            ("interest", -2000),
            ("fee", 0),
        ]
        if parser_id == "mohela_account_history_export":
            assert rows[0].source_account is None and rows[0].running_balance is None
        else:
            assert [r.source_account for r in rows] == ["123-1", "456-2"]
            assert rows[0].running_balance.minor == 90000
            assert rows[1].running_balance.minor is None and rows[1].running_balance.provenance == "unknown"


def test_real_pdf_cancelled_and_truncated_admission_leaves_no_source(catalog, tmp_path):
    source = SOURCES[0].source
    with V2ProfileStore.create(tmp_path / "refused.db") as store:
        with pytest.raises(ImportCancelled, match="cancelled"):
            import_catalog_source(store, source, catalog=catalog, suffix=".pdf", cancelled=lambda: True)
        with pytest.raises(CatalogImportError, match="pdf_routing_failed"):
            import_catalog_source(store, source[:100], catalog=catalog, suffix=".pdf")
        assert store.connection.execute("SELECT count(*) FROM Sources").fetchone() == (0,)
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)


def test_actual_pdf_ambiguous_signed_routes_refuse_before_write(tmp_path):
    definition = (ROOT / "happen-savings-pilot-definition.json").read_bytes()
    alternate = json.loads(definition)
    alternate["parser_id"] = "happen_savings_line_alt"
    catalog = signed_catalog((definition, json.dumps(alternate).encode()))
    source = next(case.source for case in SOURCES if case.definition_name == "happen-savings-pilot-definition.json")
    with V2ProfileStore.create(tmp_path / "ambiguous.db") as store:
        with pytest.raises(CatalogImportError, match="catalog_ambiguous_match"):
            import_catalog_source(store, source, catalog=catalog, suffix=".pdf")
        assert store.connection.execute("SELECT count(*) FROM Sources").fetchone() == (0,)


def test_actual_pdf_bad_printed_arithmetic_refuses_before_write(catalog, tmp_path):
    source = next(case.source for case in SOURCES if case.definition_name == "happen-savings-pilot-definition.json")
    # Equal-length mutation preserves valid PDF lengths/offsets, but changes the
    # printed running/closing values independently of the unchanged $10 activity.
    broken = source.replace(b"110.00", b"111.00")
    with V2ProfileStore.create(tmp_path / "bad-equation.db") as store:
        with pytest.raises(SourcePipelineError, match="source_evidence_failed"):
            import_catalog_source(store, broken, catalog=catalog, suffix=".pdf")
        assert store.connection.execute("SELECT count(*) FROM Sources").fetchone() == (0,)
        assert store.connection.execute("SELECT count(*) FROM SourceObservations").fetchone() == (0,)


def test_actual_pdf_equal_activity_occurrences_survive_independently(catalog, tmp_path):
    source = pdf_document(
        (
            text_page(
                "www.chase.com/cardhelp",
                "Transaction Merchant Name or Transaction Description $ Amount",
                "Opening/Closing Date 03/16/26 - 04/15/26",
                "Account Number: XXXX XXXX XXXX 1234",
                "Previous Balance $25.00",
                "New Balance $35.00",
                "04/01  SAME PURCHASE 5.00",
                "04/01  SAME PURCHASE 5.00",
            ),
        ),
        metadata={"Producer": "OpenText Output Transformation Engine"},
    )
    with V2ProfileStore.create(tmp_path / "equal-occurrences.db") as store:
        result = import_catalog_source(store, source, catalog=catalog, suffix=".pdf")
        rows = result.evidence.payload.accounts[0].rows
        assert [(r.date.iso, r.amount.minor, r.occurrence) for r in rows] == [
            ("2026-04-01", -500, 0),
            ("2026-04-01", -500, 1),
        ]
        assert rows[0].row_id != rows[1].row_id
        assert rows[0].fragments[0].location != rows[1].fragments[0].location
        assert store.connection.execute("SELECT count(*) FROM SourceObservations").fetchone() == (2,)
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)


def test_actual_pdf_occu_annotation_fallback_retains_widget_provenance(catalog, tmp_path):
    with V2ProfileStore.create(tmp_path / "annotations.db") as store:
        result = import_catalog_source(store, occu_annotation_source(), catalog=catalog, suffix=".pdf")
        payload = result.evidence.payload
        assert result.evidence.parser_id == "pdf_occubank_201409"
        assert [
            (v.iso, v.provenance, v.locations[0].kind, v.locations[0].ordinal) for v in (payload.start, payload.end)
        ] == [("2026-01-01", "observed", "pdf_annotation", 1), ("2026-01-31", "observed", "pdf_annotation", 2)]
        assert [(r.amount.minor, r.running_balance.minor) for a in payload.accounts for r in a.rows] == [
            (1000, 11000),
            (-500, 19500),
        ]
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
