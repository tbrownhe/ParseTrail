"""Account-first previews preserve all source groups and separate compatibility."""

from __future__ import annotations

import json
from dataclasses import replace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from parsetrail.core import v2_pdf_routing, v2_source_pipeline
from parsetrail.core.v2_account_products import AccountProductProfile
from parsetrail.core.v2_bounded_pdf_text import DecodedPDFText
from parsetrail.core.v2_catalog_admission import admit_pilot_definition
from parsetrail.core.v2_data_catalog import CatalogError, key_id_for_public_key, verify_catalog
from parsetrail.core.v2_format_recognition import (
    CatalogImportError,
    ImportCancelled,
    candidate_from_evidence,
    recognize_catalog_source,
)
from parsetrail.core.v2_institutions import catalog_institutions
from parsetrail.core.v2_profile_store import V2ProfileStore
from parsetrail.core.v2_source_account_context import verified_source_account_context
from parsetrail.core.v2_source_import import prepare_catalog_source
from parsetrail.core.v2_source_pipeline import SourcePipelineError, build_source_evidence
from scripts.v2_catalog_release import signed_catalog_bytes

from .test_v2_account_creation_context import _catalog as pdf_catalog
from .test_v2_account_creation_context import _evidence as pdf_evidence
from .test_v2_catalog_import import DEFINITION, SOURCE, _verified_catalog


def _profile_catalog(tmp_path, profiles, *, context=None):
    tmp_path.mkdir()
    (tmp_path / "cash-definition.json").write_bytes(DEFINITION.read_bytes())
    (tmp_path / "account-profiles.json").write_text(json.dumps({"synthetic_posted_cash_csv": profiles}))
    if context is not None:
        (tmp_path / "account-contexts.json").write_text(json.dumps({"synthetic_posted_cash_csv": context}))
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    snapshot, signature, _ = signed_catalog_bytes(tmp_path, private, release_sequence=1, source_revision="a" * 40)
    return verify_catalog(snapshot, signature, {key_id_for_public_key(public): public}, admit_pilot_definition), public


def test_generic_csv_profiles_are_signed_compatibility_and_never_source_identity(tmp_path):
    profiles = [
        {"institution_key": bank, "product_type": "checking", "tracking_scope": "account_total"}
        for bank in ("chase", "citi", "synthetic_bank")
    ]
    catalog, public = _profile_catalog(
        tmp_path / "definitions",
        profiles,
        context={"institution_key": "chase", "kind": "asset", "product_type": "checking"},
    )
    recognition = recognize_catalog_source(SOURCE, catalog=catalog, suffix=".csv")
    candidate = recognition.candidates[0]
    assert candidate.institution_key is None and candidate.account_kind is None
    assert candidate.identifying_product_type is None
    assert candidate.account_profiles == tuple(
        AccountProductProfile(bank, "checking", "account_total") for bank in ("chase", "citi", "synthetic_bank")
    )
    evidence = build_source_evidence(SOURCE, DEFINITION.read_bytes(), suffix=".csv")
    assert verified_source_account_context(evidence, catalog) is None
    assert "synthetic_bank" in {bank.id for bank in catalog_institutions(catalog)}
    changed = json.loads(catalog.snapshot)
    changed["definitions"][0]["account_profiles"][0]["institution_key"] = "wellsfargo"
    with pytest.raises(CatalogError, match="invalid_signature"):
        verify_catalog(
            json.dumps(changed).encode(),
            catalog.signature,
            {key_id_for_public_key(public): public},
            admit_pilot_definition,
        )


@pytest.mark.parametrize(
    "profile",
    [
        {"institution_key": "chase", "product_type": "invented", "tracking_scope": "account_total"},
        {"institution_key": "chase", "product_type": "checking", "tracking_scope": "principal_component"},
        {"institution_key": "not a stable id", "product_type": "checking", "tracking_scope": "account_total"},
    ],
)
def test_invalid_signed_product_profile_is_refused_before_catalog_creation(tmp_path, profile):
    with pytest.raises(ValueError):
        _profile_catalog(tmp_path / "definitions", [profile])


def test_generic_csv_cannot_claim_liability_interpretation_through_metadata(tmp_path):
    catalog, _ = _profile_catalog(
        tmp_path / "definitions",
        [
            {"institution_key": "chase", "product_type": "credit_card", "tracking_scope": "account_total"},
        ],
    )
    candidate = recognize_catalog_source(SOURCE, catalog=catalog, suffix=".csv").candidates[0]
    assert candidate.account_profiles == ()
    assert candidate.account_kind is None and candidate.institution_key is None


def test_complete_source_groups_are_not_limited_to_five_preview_rows():
    raw = b"Date,Account,Description,Amount,ReportedBalance\n" + b"".join(
        f"10/01/2026,Account {index},Synthetic purchase,-$4.01,$995.99\n".encode() for index in range(8)
    )
    candidate = recognize_catalog_source(raw, catalog=_verified_catalog(), suffix=".csv").candidates[0]
    assert len(candidate.preview_rows) == 5
    assert [account.source_identity for account in candidate.source_accounts] == [
        f"Account {index}" for index in range(8)
    ]
    assert all(
        account.row_count == 1 and account.source_scope == "account_total" for account in candidate.source_accounts
    )
    assert candidate.source_accounts[-1].locations[0].row == 9
    assert candidate.account_profiles == tuple(
        AccountProductProfile(None, product, "account_total") for product in ("checking", "savings", "cash")
    )


def test_excess_source_groups_refuse_instead_of_silently_omitting_accounts():
    raw = b"Date,Account,Description,Amount,ReportedBalance\n" + b"".join(
        f"10/01/2026,Account {index},Synthetic purchase,-$4.01,$995.99\n".encode() for index in range(101)
    )
    with pytest.raises(SourcePipelineError, match="source_account_group_limit"):
        recognize_catalog_source(raw, catalog=_verified_catalog(), suffix=".csv")


def test_pdf_sections_include_empty_accounts_and_unknown_product_is_not_invented():
    evidence = pdf_evidence()
    section = evidence.payload.accounts[1].model_copy(update={"rows": ()})
    evidence = evidence.model_copy(
        update={
            "payload": evidence.payload.model_copy(
                update={
                    "accounts": (evidence.payload.accounts[0], section),
                    "independent_balance_verified": False,
                }
            )
        }
    )
    catalog = pdf_catalog(evidence)
    candidate = candidate_from_evidence(catalog.definitions[0], evidence, catalog)
    assert len(candidate.source_accounts) == 2 and candidate.source_accounts[-1].row_count == 0
    assert candidate.source_accounts[-1].locations == section.identity_locations
    assert candidate.institution_key == "occu" and candidate.account_kind == "asset"
    assert candidate.identifying_product_type is None
    assert {profile.product_type for profile in candidate.account_profiles} == {"checking", "savings"}


def test_prepare_is_read_only_exact_and_rejects_changed_source_catalog_and_cancellation(monkeypatch):
    catalog = _verified_catalog()
    recognition = recognize_catalog_source(SOURCE, catalog=catalog, suffix=".csv")
    selection = recognition.selection("synthetic_posted_cash_csv")

    def forbidden(*_args, **_kwargs):
        raise AssertionError("Preparation must not open a profile")

    monkeypatch.setattr(V2ProfileStore, "open", forbidden)
    prepared = prepare_catalog_source(SOURCE, catalog=catalog, suffix=".csv", selection=selection)
    assert prepared.source == SOURCE and prepared.definition == DEFINITION.read_bytes()
    assert prepared.candidate == recognition.candidates[0]
    assert prepared.evidence.payload.rows[1].amount.minor == -5743
    with pytest.raises(CatalogImportError, match="source_changed"):
        prepare_catalog_source(SOURCE + b"\n", catalog=catalog, suffix=".csv", selection=selection)
    with pytest.raises(CatalogImportError, match="catalog_changed"):
        prepare_catalog_source(
            SOURCE, catalog=replace(catalog, snapshot=catalog.snapshot + b" "), suffix=".csv", selection=selection
        )
    with pytest.raises(ImportCancelled):
        prepare_catalog_source(SOURCE, catalog=catalog, suffix=".csv", selection=selection, cancelled=lambda: True)
    state = {"cancelled": False}

    def parse(source, definition, **kwargs):
        evidence = build_source_evidence(source, definition, **kwargs)
        state["cancelled"] = True
        return evidence

    with pytest.raises(ImportCancelled):
        prepare_catalog_source(
            SOURCE,
            catalog=catalog,
            suffix=".csv",
            selection=selection,
            parse=parse,
            cancelled=lambda: state["cancelled"],
        )


def test_pdf_preparation_keeps_unique_route_and_identified_product(monkeypatch):
    from devtools.parser_engine_pilot.test_savings_lines import pages

    definitions = tuple(
        (DEFINITION.parents[1] / "parser_engine_pilot" / name).read_bytes()
        for name in ("happen-savings-pilot-definition.json", "lendingclub-savings-pilot-definition.json")
    )
    catalog = _verified_catalog(definitions)
    # Supply signed-context read models after independently exercised catalog
    # authentication; this synthetic decoder is not installed/native coverage.
    from parsetrail.core.v2_data_catalog import CatalogAccountContext

    catalog = replace(
        catalog,
        definitions=tuple(
            replace(
                entry,
                account_context=CatalogAccountContext(
                    institution_key="happen" if entry.identity.parser_id.startswith("happen") else "lendingclub",
                    kind="asset",
                ),
            )
            for entry in catalog.definitions
        ),
    )
    decoded = DecodedPDFText(
        ("Summary of Accounts\n" + pages()[0], pages()[1]), (("Creator", "VCTransaction"), ("Title", "StmtAPISvc"))
    )
    monkeypatch.setattr(v2_pdf_routing, "decode_pdf", lambda _source, *, cancelled=None: decoded)
    monkeypatch.setattr(v2_source_pipeline, "decode_pdf", lambda _source, *, cancelled=None: decoded)
    recognition = recognize_catalog_source(b"%PDF-synthetic", catalog=catalog, suffix=".pdf")
    candidate = recognition.candidates[0]
    assert candidate.identifying_product_type == "savings" and candidate.institution_key == "happen"
    selection = recognition.selection(candidate.parser_id)
    prepared = prepare_catalog_source(b"%PDF-synthetic", catalog=catalog, suffix=".pdf", selection=selection)
    assert prepared.candidate == candidate
    other = next(entry for entry in catalog.definitions if entry.identity.parser_id != candidate.parser_id)
    wrong = replace(
        selection, parser_id=other.identity.parser_id, revision=other.identity.revision, definition_sha256=other.sha256
    )
    with pytest.raises(CatalogImportError, match="selected_route_mismatch"):
        prepare_catalog_source(b"%PDF-synthetic", catalog=catalog, suffix=".pdf", selection=wrong)
