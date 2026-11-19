"""Business product defaults require the printed product from the audited engine."""

from dataclasses import replace

import pytest
from parsetrail.core.v2_account_creation import suggest_account_creation
from parsetrail.core.v2_data_catalog import (
    CatalogAccountContext,
    DefinitionIdentity,
    VerifiedCatalog,
    VerifiedDefinition,
)
from parsetrail.core.v2_format_recognition import FormatRecognition, candidate_from_evidence, catalog_digest
from parsetrail.core.v2_import_accounts import build_import_account_review
from parsetrail.core.v2_pdf_lines import page_lines
from parsetrail.core.v2_profile_store import V2ProfileStore
from parsetrail.core.v2_source_account_context import source_account_profiles, verified_source_account_context
from parsetrail.core.v2_wells_statement_output import from_wells_business
from parsetrail.core.v2_wells_table import extract_table_rows
from parsetrail.gui.v2_batch_import import ImportAccountReviewRequest
from parsetrail.gui.v2_import_account_review import V2ImportAccountReview
from PySide6.QtCore import Qt

from devtools.parser_engine_pilot.test_wells_statement_output import DEFINITION, SOURCE, statement_text, table_cells
from devtools.parser_engine_pilot.test_wells_table import FakePage

from .qt_journey_helpers import JourneyArtifacts, choose_combo
from .test_v2_statement_summary_desktop import dispose


def printed_business(label):
    table = extract_table_rows(DEFINITION, SOURCE, [FakePage(table_cells())], extraction_library="synthetic-pdf-1")
    text = statement_text()
    if label:
        text[0] = label + "\n" + text[0]
    return from_wells_business(DEFINITION, table, page_lines(SOURCE, text, extraction_library="synthetic-pdf-1"))


def catalog_for(evidence):
    entry = VerifiedDefinition(
        DefinitionIdentity(evidence.parser_id, evidence.definition_revision, ".pdf"),
        DEFINITION,
        evidence.definition_sha256,
        CatalogAccountContext(institution_key="wellsfargo", kind="asset"),
    )
    return VerifiedCatalog(1, "a" * 40, "synthetic", b"", b"", (entry,))


@pytest.mark.parametrize(
    "label,product",
    [
        ("Initiate Business Checking SM ", "checking"),
        ("Business Market Rate Savings", "savings"),
    ],
)
@pytest.mark.parametrize("engine", ["wells-table-pilot-2+statement-v2", "wells-table-pilot-2+statement-v3"])
def test_printed_product_defaults_without_changing_the_evidence(label, product, engine):
    evidence = printed_business(label)
    evidence = evidence.model_copy(update={"engine_version": engine})
    catalog = catalog_for(evidence)
    before = evidence.model_dump_json()
    context = verified_source_account_context(evidence, catalog)
    assert context.product_type == product
    assert {profile.product_type for profile in source_account_profiles(evidence, catalog)} == {product}
    section = evidence.payload.accounts[0]
    draft = suggest_account_creation(
        evidence, catalog=catalog, source_identity=section.source_identity, source_form=section.source_identity_form
    )
    assert draft.name == "Wells Fargo 7890" and draft.product_type == product
    assert draft.verified_context and draft.full_account_number == section.source_identity
    assert evidence.model_dump_json() == before


@pytest.mark.parametrize(
    "change", ["missing", "old_engine", "unreviewed_engine", "unknown", "duplicate", "wrong_page", "stale_catalog"]
)
def test_route_or_filename_alone_cannot_identify_the_business_product(change):
    evidence = printed_business(None if change == "missing" else "Initiate Business Checking SM")
    catalog = catalog_for(evidence)
    if change == "old_engine":
        evidence = evidence.model_copy(update={"engine_version": "wells-table-pilot-1+statement-v1"})
    if change == "unreviewed_engine":
        evidence = evidence.model_copy(update={"engine_version": "wells-table-pilot-2+statement-v99"})
    if change in {"unknown", "duplicate", "wrong_page"}:
        roles = list(evidence.payload.dispositions)
        index = next(index for index, item in enumerate(roles) if item.code == "wells_account_product")
        if change == "unknown":
            roles[index] = roles[index].model_copy(update={"raw_values": ("Other business product",)})
        elif change == "wrong_page":
            roles[index] = roles[index].model_copy(
                update={"location": roles[index].location.model_copy(update={"page": 2})}
            )
        else:
            roles.append(roles[index])
        evidence = evidence.model_copy(
            update={"payload": evidence.payload.model_copy(update={"dispositions": tuple(roles)})}
        )
    if change == "stale_catalog":
        catalog = replace(catalog, definitions=(replace(catalog.definitions[0], sha256="0" * 64),))
    context = verified_source_account_context(evidence, catalog)
    assert context is None or context.product_type is None


def test_business_account_creation_prefills_nickname_and_product(qtbot, qapp, tmp_path, journey_artifacts):
    evidence = printed_business("Initiate Business Checking SM")
    catalog = catalog_for(evidence)
    candidate = candidate_from_evidence(catalog.definitions[0], evidence, catalog)
    recognition = FormatRecognition(evidence.source_sha256, ".pdf", catalog_digest(catalog), (candidate,))
    with V2ProfileStore.create(tmp_path / "empty.db") as store:
        review = build_import_account_review(store, recognition, catalog)
    request = ImportAccountReviewRequest(tmp_path / "Public-business.pdf", review, 1, 1)
    dialog = V2ImportAccountReview(review.institutions)
    qtbot.addWidget(dialog)
    dialog.resize(1050, 700)
    dialog.present(request)
    choose_combo(qtbot, dialog.account_choice, "__create_new_account__")
    qapp.processEvents()
    assert dialog.name.text() == "Wells Fargo 7890"
    assert dialog.product.currentData().product_type == "checking" and not dialog.product.isEnabled()
    assert not dialog.institution.isEnabled()
    assert not request.decided.is_set()
    JourneyArtifacts(journey_artifacts, qapp, (1050, 700)).capture("01-wells-business-defaults", dialog)
    qtbot.keyClick(dialog.name, Qt.Key_End)
    dialog.finish_queue()
    dispose(qtbot, dialog)
