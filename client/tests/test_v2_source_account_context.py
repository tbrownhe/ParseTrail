"""Choosing a compatible format cannot authenticate a generic CSV's bank."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from parsetrail.core.v2_account_creation import suggest_account_creation
from parsetrail.core.v2_account_matching import LedgerAccountCandidate, match_verified_source_account
from parsetrail.core.v2_batch_account_assignment import plan_account_assignments
from parsetrail.core.v2_catalog_admission import admit_pilot_definition
from parsetrail.core.v2_data_catalog import key_id_for_public_key, verify_catalog
from parsetrail.core.v2_format_recognition import recognize_catalog_source
from parsetrail.core.v2_preferences import V2Preferences
from parsetrail.core.v2_profile_store import FinancialAccount, V2ProfileStore
from parsetrail.core.v2_source_account_context import verified_source_account_context
from parsetrail.core.v2_source_import import import_catalog_source
from parsetrail.core.v2_source_pipeline import build_source_evidence
from scripts.v2_catalog_release import signed_catalog_bytes

from .test_v2_account_creation_context import _catalog as pdf_catalog
from .test_v2_account_creation_context import _evidence as pdf_evidence
from .test_v2_catalog_import import DEFINITION, SOURCE

PILOT = Path(__file__).parents[2] / "devtools/parser_engine_pilot"
MOHELA_SOURCE = (
    b'<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.0 Transitional//EN">'
    b"Date,Description,Principal,Interest,Fees,Total,\n"
    b"10/01/2026,Payment,-$80.00,-$20.00,$0.00,-$100.00,\n"
)
MOHELA_DETAIL_SOURCE = (
    b'<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.0 Transitional//EN">'
    b"Date,LoanName,Description,Principal,Interest,Fees,Total,UnpaidPrincipalBalanceValue,\n"
    b"10/01/2026,123-1 Loan A,Payment,-$80.00,-$20.00,$0.00,-$100.00,$900.00,\n"
)


def _catalog(tmp_path, definitions, *, institution="mohela", kind="liability"):
    tmp_path.mkdir()
    contexts = {}
    for index, definition in enumerate(definitions):
        raw = json.loads(definition)
        (tmp_path / f"{index}-definition.json").write_bytes(definition)
        key = institution[raw["parser_id"]] if isinstance(institution, dict) else institution
        contexts[raw["parser_id"]] = {"institution_key": key, "kind": kind}
    (tmp_path / "account-contexts.json").write_text(json.dumps(contexts))
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    snapshot, signature, _ = signed_catalog_bytes(tmp_path, private, release_sequence=1, source_revision="a" * 40)
    return verify_catalog(snapshot, signature, {key_id_for_public_key(public): public}, admit_pilot_definition)


def _draft(evidence, catalog):
    row = evidence.payload.rows[0]
    return suggest_account_creation(
        evidence,
        catalog=catalog,
        source_identity=row.source_account,
        source_form=row.source_account_form,
    )


@pytest.mark.parametrize("ambiguous", [False, True])
def test_generic_signed_csv_context_stays_unknown_after_valid_format_selection_and_manual_assignment(
    tmp_path, ambiguous
):
    original = DEFINITION.read_bytes()
    alternate = json.loads(original)
    alternate["parser_id"] = "other_generic_csv"
    catalog = _catalog(
        tmp_path / "catalog",
        (original, json.dumps(alternate).encode()) if ambiguous else (original,),
        institution={"synthetic_posted_cash_csv": "citi", "other_generic_csv": "chase"},
        kind="asset",
    )
    recognition = recognize_catalog_source(SOURCE, catalog=catalog, suffix=".csv")
    assert len(recognition.candidates) == (2 if ambiguous else 1)
    assert all(item.institution_key is None and item.account_kind is None for item in recognition.candidates)
    with V2ProfileStore.create(tmp_path / "profile.db") as store:
        result = import_catalog_source(
            store,
            SOURCE,
            catalog=catalog,
            suffix=".csv",
            selection=recognition.selection("synthetic_posted_cash_csv"),
        )
        evidence = result.evidence
        assert verified_source_account_context(evidence, catalog) is None
        draft = _draft(evidence, catalog)
        assert draft.institution_key is None and draft.kind is None and not draft.verified_context
        assert not draft.name.startswith(("Citi", "Chase"))
        # Explicit assignment to an authored account remains available without a
        # bank label; format recognition never creates a ledger interpretation.
        store.add_financial_account(FinancialAccount("manual", "My checking", "asset", None))
        store.bind_source_account(evidence.source_sha256, "Checking A", "opaque", "manual")
        assert store.account_bindings(evidence.source_sha256)[0].ledger_account_id == "manual"
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
        second = SOURCE.replace(b"Groceries", b"Another purchase")
        import_catalog_source(store, second, catalog=catalog, suffix=".csv", parser_id="synthetic_posted_cash_csv")
        plan = plan_account_assignments(store, catalog=catalog, preferences=V2Preferences())
        assert plan.groups
        assert all(group.status == "manual" and group.suggested_account_id is None for group in plan.groups)
        assert all(group.institution_key is None and not group.draft.verified_context for group in plan.groups)
    # Even a candidate identity usable for number matching must remain manual:
    # choosing generic format + catalog bank label supplies no source proof.
    row = evidence.payload.rows[0].model_copy(update={"source_account": "999991234", "source_account_form": "full"})
    full = evidence.model_copy(update={"payload": evidence.payload.model_copy(update={"rows": (row,)})})
    match = match_verified_source_account(
        full,
        "999991234",
        "full",
        catalog=catalog,
        candidates=(LedgerAccountCandidate("bank", "citi", "asset", "999991234"),),
        preferences=V2Preferences(),
    )
    assert match.status == "review" and match.ledger_account_id is None and not match.suggestions


@pytest.mark.parametrize("detailed", [False, True])
def test_reviewed_mohela_component_csv_context_is_preserved(tmp_path, detailed):
    name = "mohela-pilot-definition.json" if detailed else "mohela-account-history-definition.json"
    definition = (PILOT / name).read_bytes()
    source = MOHELA_DETAIL_SOURCE if detailed else MOHELA_SOURCE
    catalog = _catalog(tmp_path / "catalog", (definition,))
    evidence = build_source_evidence(source, definition, suffix=".csv")
    context = verified_source_account_context(evidence, catalog)
    assert context.institution_key == "mohela" and context.kind == "liability"
    draft = _draft(evidence, catalog)
    assert draft.verified_context and draft.institution_key == "mohela" and draft.kind == "liability"
    assert draft.tracking_scope == "principal_component"
    candidate = recognize_catalog_source(source, catalog=catalog, suffix=".csv").candidates[0]
    assert candidate.institution_key == "mohela" and candidate.account_kind == "liability"
    assert tuple(component.role for component in candidate.preview_rows[0].components) == (
        "principal",
        "interest",
        "fee",
    )


@pytest.mark.parametrize("parser_id", ["mohela_account_history_export", "mohela_detailed_export"])
def test_generic_csv_renamed_to_a_reviewed_family_is_not_institution_proof(tmp_path, parser_id):
    raw = json.loads(DEFINITION.read_bytes())
    raw["parser_id"] = parser_id
    definition = json.dumps(raw).encode()
    catalog = _catalog(tmp_path / "catalog", (definition,))
    evidence = build_source_evidence(SOURCE, definition, suffix=".csv")
    assert verified_source_account_context(evidence, catalog) is None
    assert not _draft(evidence, catalog).verified_context
    assert recognize_catalog_source(SOURCE, catalog=catalog, suffix=".csv").candidates[0].institution_key is None


@pytest.mark.parametrize(
    "change",
    [
        "institution",
        "kind",
        "suffix",
        "definition_hash",
        "revision",
        "components",
        "date_provenance",
        "component_provenance",
        "locations",
        "engine",
        "extractor",
    ],
)
def test_mohela_context_refuses_identity_shape_and_provenance_drift(tmp_path, change):
    definition = (PILOT / "mohela-account-history-definition.json").read_bytes()
    catalog = _catalog(tmp_path / "catalog", (definition,))
    evidence = build_source_evidence(MOHELA_SOURCE, definition, suffix=".csv")
    entry = catalog.definitions[0]
    if change in {"institution", "kind"}:
        context = entry.account_context.model_copy(
            update={
                "institution_key" if change == "institution" else "kind": "chase"
                if change == "institution"
                else "asset",
            }
        )
        catalog = replace(catalog, definitions=(replace(entry, account_context=context),))
    elif change == "suffix":
        catalog = replace(catalog, definitions=(replace(entry, identity=replace(entry.identity, suffix=".pdf")),))
    elif change == "definition_hash":
        catalog = replace(catalog, definitions=(replace(entry, content=entry.content + b" "),))
    elif change == "revision":
        evidence = evidence.model_copy(update={"definition_revision": "2"})
    elif change in {"engine", "extractor"}:
        evidence = evidence.model_copy(
            update={"engine_version" if change == "engine" else "extractor_version": "other"}
        )
    else:
        row = evidence.payload.rows[0]
        if change == "components":
            row = row.model_copy(update={"components": ()})
        elif change == "date_provenance":
            row = row.model_copy(update={"date": row.date.model_copy(update={"provenance": "assumed"})})
        elif change == "component_provenance":
            components = (
                row.components[0].model_copy(
                    update={"amount": row.components[0].amount.model_copy(update={"provenance": "derived"})}
                ),
                *row.components[1:],
            )
            row = row.model_copy(update={"components": components})
        else:
            row = row.model_copy(update={"amount": row.amount.model_copy(update={"locations": ()})})
        evidence = evidence.model_copy(update={"payload": evidence.payload.model_copy(update={"rows": (row,)})})
    assert verified_source_account_context(evidence, catalog) is None
    draft = _draft(evidence, catalog)
    assert draft.institution_key is None and draft.kind is None and not draft.verified_context


def test_pdf_exact_signed_context_is_unchanged_and_suffix_drift_is_refused():
    evidence = pdf_evidence()
    catalog = pdf_catalog(evidence)
    assert verified_source_account_context(evidence, catalog).institution_key == "occu"
    entry = catalog.definitions[0]
    assert hashlib.sha256(entry.content).hexdigest() == evidence.definition_sha256
    wrong = replace(catalog, definitions=(replace(entry, identity=replace(entry.identity, suffix=".csv")),))
    assert verified_source_account_context(evidence, wrong) is None
