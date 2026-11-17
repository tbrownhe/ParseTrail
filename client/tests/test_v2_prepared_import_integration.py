"""Interactive choices save the reviewed complete payload without another source parse."""

import hashlib

import pytest
from parsetrail.core import v2_source_pipeline as pipeline
from parsetrail.core.v2_import_accounts import ImportAccountChoice, prepare_import_accounts
from parsetrail.core.v2_profile_store import FinancialAccount, V2ProfileStore

from .test_v2_workspace_recognition import workspace_with_choices


def seven_rows(path):
    source = b"Date,Account,Description,Amount,ReportedBalance\n" + b"".join(
        f"10/0{i}/2026,Checking A,Purchase {i},-$1.00,${1000 - i}.00\n".encode() for i in range(1, 8)
    )
    path.write_bytes(source)
    return source


@pytest.mark.parametrize("parser", ["synthetic_activity_csv", "synthetic_posted_csv"])
def test_complete_selected_evidence_is_saved_then_queried_without_parsing(tmp_path, monkeypatch, parser):
    workspace, path, _ = workspace_with_choices(tmp_path, account_routing=True)
    source = seven_rows(path)
    catalog = workspace.catalog_cache.load_current()
    definition = next(item for item in catalog.definitions if item.identity.parser_id == parser)
    expected = pipeline.build_source_evidence(source, definition.content, suffix=".csv")
    parsed = []
    parse = pipeline.parse_csv

    def counted(definition, *args, **kwargs):
        parsed.append(hashlib.sha256(definition).hexdigest())
        return parse(definition, *args, **kwargs)

    def forbidden(*_args, **_kwargs):
        pytest.fail("A confirmed import, saved retry or evidence read parsed the source again")

    monkeypatch.setattr(pipeline, "parse_csv", counted)
    product = "savings" if parser == "synthetic_activity_csv" else "checking"
    account = FinancialAccount("selected", "Selected account", "asset", "chase", product_type=product)
    seen = []

    def choose(_path, review):
        seen.append(review)
        assert len(review.recognition.candidates) == 2
        assert len(parsed) == 2 and len(set(parsed)) == 2
        plan = prepare_import_accounts(
            review,
            tuple(ImportAccountChoice(group.group_id, account.id) for group in review.groups),
            parser,
            new_accounts=(account,),
        )
        monkeypatch.setattr(pipeline, "parse_csv", forbidden)
        return plan

    result = workspace.import_file(path, review_import=choose)
    assert len(seen) == 1 and len(parsed) == 2 and result.evidence == expected
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        saved = store.load_import(result.source_sha256)
        assert saved.source == source and saved.definition == definition.content and saved.evidence == expected
        assert saved.evidence.payload.rows[-1].description.text == "Purchase 7"
        assert len(store.source_interpretation_snapshot(result.source_sha256, kind="cash").rows) == 7
        assert store.document_summaries()[0].row_count == 7
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
    assert workspace.import_file(path, review_import=forbidden).status == "already_imported"
    assert len(parsed) == 2


def test_explicit_format_selection_also_uses_the_prepared_nonfirst_output(tmp_path, monkeypatch):
    workspace, path, _ = workspace_with_choices(tmp_path)
    source = seven_rows(path)
    catalog = workspace.catalog_cache.load_current()
    parser = "synthetic_posted_csv"
    definition = next(item for item in catalog.definitions if item.identity.parser_id == parser)
    expected = pipeline.build_source_evidence(source, definition.content, suffix=".csv")
    seen = []

    def forbidden(*_args, **_kwargs):
        pytest.fail("Explicit format confirmation triggered source parsing")

    def choose(_path, recognition):
        seen.append(recognition)
        assert recognition.candidates[-1].parser_id == parser
        monkeypatch.setattr(pipeline, "parse_csv", forbidden)
        return recognition.selection(parser)

    result = workspace.import_file(path, review_format=choose)
    assert result.evidence == expected and len(seen) == 1
    assert workspace.import_file(path, review_format=forbidden).status == "already_imported"
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert store.load_import(result.source_sha256).evidence == expected
        assert store.financial_accounts() == ()
