"""Admitted period summaries share source-value review without becoming cash activity."""

import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from parsetrail.core import v2_bounded_pdf_text as pdf_text
from parsetrail.core import v2_source_pipeline as pipeline
from parsetrail.core.v2_data_catalog import key_id_for_public_key
from parsetrail.core.v2_import_accounts import ImportAccountChoice, prepare_import_accounts
from parsetrail.core.v2_import_warnings import evidence_import_warnings
from parsetrail.core.v2_preferences import V2Preferences
from parsetrail.core.v2_profile_store import FinancialAccount, V2ProfileStore
from parsetrail.core.v2_statement_summary_review import SUMMARY_VALUE_PARSERS
from parsetrail.core.v2_workspace import V2Workspace
from scripts.v2_catalog_release import signed_catalog_bytes

from devtools.parser_engine_pilot.synthetic_family_sources import family_sources, pdf_document, text_page
from devtools.parser_engine_pilot.test_summary_context_roles import chart_source_lines

from .v2_institution_helpers import add_test_financial_account

FAMILIES = (
    ("fidelity-401k-summary-pilot-definition.json", "fidelity", "investment", 14000),
    ("vanguard-summary-pilot-definition.json", "vanguard", "investment", 17000),
    ("fidelity-hsa-summary-pilot-definition.json", "fidelity", "hsa", 14500),
)


def prepare_family(path, name, institution, product, *, tracking_scope="account_total"):
    case = next(item for item in family_sources() if item.definition_name == name)
    definition = (Path(__file__).parents[2] / "devtools/parser_engine_pilot" / name).read_bytes()
    evidence = pipeline.build_source_evidence(case.source, definition, suffix=case.suffix)
    with V2ProfileStore.create(path) as store:
        store.import_source(case.source, definition, evidence, suffix=case.suffix)
        add_test_financial_account(
            store,
            FinancialAccount(
                "value",
                "My statement account",
                "asset",
                institution,
                tracking_scope=tracking_scope,
                product_type=product,
            ),
        )
        account = evidence.payload.accounts[0]
        store.bind_source_account(
            evidence.source_sha256, account.source_identity, account.source_identity_form, "value"
        )
    return case.source, evidence


@pytest.mark.parametrize("name,institution,product,closing", FAMILIES)
def test_supported_summary_records_exact_value_then_reopens_without_posting(
    tmp_path, monkeypatch, name, institution, product, closing
):
    profile = tmp_path / "summary.db"
    source, evidence = prepare_family(profile, name, institution, product)
    assert evidence.parser_id in SUMMARY_VALUE_PARSERS

    def forbidden(*_args, **_kwargs):
        pytest.fail("Saved summary value review parsed or decoded its source")

    monkeypatch.setattr(pdf_text, "run_worker", forbidden)
    with V2ProfileStore.open(profile) as store:
        snapshot = store.statement_summary_snapshot(evidence.source_sha256)
        section = snapshot.sections[0]
        assert not snapshot.complete and section.status == "pending"
        assert section.closing.minor == closing and not section.blockers
        assert all(row.row_role == "period_summary" and row.date_role == "statement_period_end" for row in section.rows)
        assert store.document_summaries()[0].pending_summary_values == 1
        point = store.record_reviewed_source_value(
            section.account_id,
            section.candidate.candidate_id,
            expected_candidate_sha256=section.candidate.version,
            expected_basis_sha256=section.basis_sha256,
            expected_profile_identity=snapshot.profile_identity,
            reference="Reviewed printed statement closing",
            reason="Initial Review",
        )
        assert store.statement_summary_snapshot(evidence.source_sha256).complete
        summary = store.document_summaries()[0]
        assert summary.pending_summary_values == 0 and summary.reviewed_summary_values == 1
        position = store.account_positions(as_of=point.value_date).accounts[0]
        assert position.latest_dated_value.amount_minor == closing
        assert position.position_debit_minor is None and position.recorded_debit_minor == 0
        assert not store.resolution_snapshot(preferences=V2Preferences()).items
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
        assert store._active_consumed() == {}
        frame = store.account_anchor_snapshot("value")
        store.withdraw_reviewed_dated_value(
            "value",
            point.value_id,
            expected_value_version=point.version,
            expected_basis_sha256=frame.basis_sha256,
            reason="Check source value again",
        )
        assert not store.statement_summary_snapshot(evidence.source_sha256).complete
        saved = store.load_import(evidence.source_sha256)
        assert saved.source == source and saved.evidence == evidence


def test_whole_hsa_summary_cannot_be_reinterpreted_as_cash_component(tmp_path):
    profile = tmp_path / "wrong-scope.db"
    _source, evidence = prepare_family(
        profile, "fidelity-hsa-summary-pilot-definition.json", "fidelity", "hsa", tracking_scope="cash_component"
    )
    with V2ProfileStore.open(profile) as store:
        snapshot = store.statement_summary_snapshot(evidence.source_sha256)
        assert snapshot.sections[0].status == "blocked"
        assert "source_value_scope_or_kind_mismatch" in snapshot.sections[0].blockers
        assert store.connection.execute("SELECT count(*) FROM AccountDatedValues").fetchone() == (0,)
    assert "hsa_cash_line_pilot" not in SUMMARY_VALUE_PARSERS


@pytest.mark.parametrize("kind", ["vanguard", "hsa", "unexplained-vanguard"])
def test_signed_catalog_import_automates_only_classified_summary_without_redecoding(tmp_path, monkeypatch, kind):
    name = "fidelity-hsa-summary-pilot-definition.json" if kind == "hsa" else "vanguard-summary-pilot-definition.json"
    pilot = Path(__file__).parents[2] / "devtools/parser_engine_pilot"
    definition = (pilot / name).read_bytes()
    parser_id = json.loads(definition)["parser_id"]
    definitions = tmp_path / "definitions"
    definitions.mkdir()
    (definitions / name).write_bytes(definition)
    contexts = json.loads((pilot / "account-contexts.json").read_bytes())
    (definitions / "account-contexts.json").write_text(json.dumps({parser_id: contexts[parser_id]}))
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    catalog, signature, _ = signed_catalog_bytes(definitions, private, release_sequence=1, source_revision="a" * 40)
    workspace = V2Workspace.create(
        tmp_path / "import.db",
        tmp_path / "catalog",
        trusted_keys={key_id_for_public_key(public): public},
        preferences_path=tmp_path / "preferences.json",
    )
    workspace.catalog_cache.activate(catalog, signature)
    workspace.set_auto_record_statement_values(True)
    workspace.set_import_preview_mode("when_needed")
    source = next(item.source for item in family_sources() if item.definition_name == name)
    if kind == "vanguard":
        source = pdf_document((text_page("vanguard.com", *chart_source_lines()),))
    path = tmp_path / "public-statement.pdf"
    path.write_bytes(source)

    def forbid(*_args, **_kwargs):
        pytest.fail("Confirmation or value automation decoded the prepared PDF again")

    def confirm(_path, review):
        monkeypatch.setattr(pdf_text, "run_worker", forbid)
        account = FinancialAccount(
            "summary",
            "My summary",
            "asset",
            "fidelity" if kind == "hsa" else "vanguard",
            product_type="hsa" if kind == "hsa" else "investment",
        )
        return prepare_import_accounts(
            review,
            tuple(ImportAccountChoice(group.group_id, account.id) for group in review.groups),
            parser_id,
            new_accounts=(account,),
        )

    result = workspace.import_file(path, review_import=confirm)
    assert result.status == "imported"
    warned = any(item.classification == "requires_review" for item in evidence_import_warnings(result.evidence))
    assert warned == (kind == "unexplained-vanguard")
    automatic = result.statement_value_automation
    assert automatic.status == ("needs_review" if warned else "recorded")
    if warned:
        assert automatic.reason_code == "statement_value_auto_source_warning"
    else:
        assert automatic.amount_minor == (14500 if kind == "hsa" else 17000)
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert store.statement_summary_snapshot(result.source_sha256).complete == (not warned)
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
        assert store.connection.execute("SELECT count(*) FROM AccountDatedValues").fetchone() == (int(not warned),)
        assert not store.resolution_snapshot(preferences=workspace.preferences()).items
        assert store.load_import(result.source_sha256).source == source
