"""Routine imports can skip display, while validation and explicit opt-in remain authoritative."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from parsetrail.core.source_evidence import SourceDisposition
from parsetrail.core.v2_data_catalog import key_id_for_public_key
from parsetrail.core.v2_format_recognition import candidate_from_evidence, recognize_catalog_source
from parsetrail.core.v2_import_accounts import automatic_import_plan, build_import_account_review
from parsetrail.core.v2_preferences import V2Preferences, load_preferences, save_preferences
from parsetrail.core.v2_profile_store import FinancialAccount, V2ProfileStore
from parsetrail.core.v2_workspace import ImportSkipped, V2Workspace
from scripts.v2_catalog_release import signed_catalog_bytes

from devtools.parser_engine_pilot.synthetic_family_sources import family_sources


@pytest.fixture
def known_pdf(tmp_path):
    pilot = Path(__file__).resolve().parents[2] / "devtools/parser_engine_pilot"
    case = next(item for item in family_sources() if item.definition_name == "happen-savings-pilot-definition.json")
    definitions = tmp_path / "definitions"
    definitions.mkdir()
    (definitions / case.definition_name).write_bytes((pilot / case.definition_name).read_bytes())
    contexts = json.loads((pilot / "account-contexts.json").read_bytes())
    parser_id = json.loads((pilot / case.definition_name).read_bytes())["parser_id"]
    (definitions / "account-contexts.json").write_text(json.dumps({parser_id: contexts[parser_id]}))
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    snapshot, signature, _catalog = signed_catalog_bytes(
        definitions, private, release_sequence=1, source_revision="a" * 40
    )
    workspace = V2Workspace.create(
        tmp_path / "review.db",
        tmp_path / "catalog",
        trusted_keys={key_id_for_public_key(public): public},
        preferences_path=tmp_path / "preferences.json",
    )
    release = tmp_path / "release"
    release.mkdir()
    (release / "catalog.json").write_bytes(snapshot)
    (release / "catalog.sig").write_bytes(signature)
    workspace.install_catalog_release(release)
    with V2ProfileStore.open(workspace.profile_path) as store:
        store.add_financial_account(
            FinancialAccount("savings", "My savings", "asset", "happen", product_type="savings")
        )
    first = tmp_path / "first.pdf"
    first.write_bytes(case.source)
    result = workspace.import_file(first)
    with V2ProfileStore.open(workspace.profile_path) as store:
        section = result.evidence.payload.accounts[0]
        store.bind_source_account(
            result.source_sha256, section.source_identity, section.source_identity_form, "savings"
        )
    second = tmp_path / "second.pdf"
    second.write_bytes(case.source + b"\n% another synthetic export\n")
    return workspace, second


def review_for(workspace, source):
    catalog = workspace.catalog_cache.load_current()
    recognition = recognize_catalog_source(source.read_bytes(), catalog=catalog, suffix=".pdf")
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        return build_import_account_review(store, recognition, catalog, preferences=workspace.preferences())


def test_remembered_partial_identity_obeys_preference_without_inventing_full_number(known_pdf):
    workspace, source = known_pdf
    review = review_for(workspace, source)
    assert review.groups[0].suggested_account_id == "savings"
    assert not review.groups[0].automatic and review.groups[0].offer_enable_abbreviated_matching
    workspace.set_allow_abbreviated_account_matching(True)
    review = review_for(workspace, source)
    assert review.groups[0].automatic and review.groups[0].suggested_account_id == "savings"
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert store.financial_accounts()[0].full_account_number is None


def test_opted_in_routine_import_skips_dialog_and_posts_no_money(known_pdf):
    workspace, source = known_pdf
    workspace.set_allow_abbreviated_account_matching(True)
    workspace.set_import_preview_mode("when_needed")
    review = review_for(workspace, source)
    assert not review.recognition.candidates[0].attention_codes
    assert automatic_import_plan(review) is not None

    def unexpected(*_args):
        raise AssertionError("Routine import should not request an import preview")

    result = workspace.import_file(source, review_import=unexpected)
    assert result.status == "imported"
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert len(store.source_ids()) == 2
        assert store.source_account_bindings(result.source_sha256)[0].ledger_account_id == "savings"
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)


def test_attention_projection_checks_all_rows_and_parser_warning_suffixes(known_pdf):
    workspace, _source = known_pdf
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        evidence = store.load_import(store.source_ids()[0]).evidence
    original = evidence.payload.accounts[0]
    row = original.rows[0]
    rows = tuple(row.model_copy(update={"row_id": f"{index:064x}", "occurrence": index}) for index in range(6))
    rows = (
        *rows[:5],
        rows[5].model_copy(update={"date": row.date.model_copy(update={"raw": None, "provenance": "assumed"})}),
    )
    codes = ("summary_window_unclassified", "summary_window_tail_unclassified", "unresolved_after_stop")
    payload = evidence.payload.model_copy(
        update={
            "accounts": (original.model_copy(update={"rows": rows}),),
            "dispositions": tuple(SourceDisposition(code=code, location=row.fragments[0].location) for code in codes),
        }
    )
    catalog = workspace.catalog_cache.load_current()
    item = next(item for item in catalog.definitions if item.identity.parser_id == evidence.parser_id)
    candidate = candidate_from_evidence(item, evidence.model_copy(update={"payload": payload}), catalog)
    assert len(candidate.preview_rows) == 5
    assert set(codes) | {"source_activity_date_assumed"} <= set(candidate.attention_codes)


def test_current_suffix_match_conflicting_with_confirmed_association_requires_choice(known_pdf):
    workspace, source = known_pdf
    workspace.set_allow_abbreviated_account_matching(True)
    workspace.set_import_preview_mode("when_needed")
    with V2ProfileStore.open(workspace.profile_path) as store:
        store.add_financial_account(
            FinancialAccount("second", "Other savings", "asset", "happen", "99991234", product_type="savings")
        )
    review = review_for(workspace, source)
    assert review.groups[0].matching_ambiguous
    assert not review.groups[0].automatic and review.groups[0].suggested_account_id is None
    assert automatic_import_plan(review) is None


def test_preview_policy_requires_attention_for_new_unknown_ambiguous_and_warnings(known_pdf):
    workspace, source = known_pdf
    workspace.set_allow_abbreviated_account_matching(True)
    workspace.set_import_preview_mode("when_needed")
    review = review_for(workspace, source)
    assert automatic_import_plan(review) is not None
    candidate = review.recognition.candidates[0]
    for changed in (
        replace(review, import_preview_mode="always"),
        replace(review, recovery_notice="Inputs changed"),
        replace(review, groups=(replace(review.groups[0], automatic=False),)),
        replace(review, groups=(replace(review.groups[0], suggested_account_id=None),)),
        replace(review, recognition=replace(review.recognition, candidates=(candidate, candidate))),
        replace(
            review,
            recognition=replace(
                review.recognition, candidates=(replace(candidate, attention_codes=("unclassified_monetary_line",)),)
            ),
        ),
    ):
        assert automatic_import_plan(changed) is None


def test_live_preference_change_during_parse_forces_preview_without_partial_import(known_pdf, monkeypatch):
    from parsetrail.core import v2_workspace as module

    workspace, source = known_pdf
    workspace.set_allow_abbreviated_account_matching(True)
    workspace.set_import_preview_mode("when_needed")
    original = module.prepare_catalog_source

    def preference_changed(*args, **kwargs):
        result = original(*args, **kwargs)
        workspace.set_import_preview_mode("always")
        return result

    monkeypatch.setattr(module, "prepare_catalog_source", preference_changed)
    asked = []

    def cancel(_path, review):
        asked.append(review.recovery_notice)
        return None

    with pytest.raises(ImportSkipped):
        workspace.import_file(source, review_import=cancel)
    assert len(asked) == 1 and "needs attention" in asked[0]
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert len(store.source_ids()) == 1
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)


@pytest.mark.parametrize("bad", [None, [], {}, True, "never"])
def test_preview_preferences_validate_shape_and_keep_old_default(tmp_path, bad):
    path = tmp_path / "prefs.json"
    path.write_text(json.dumps({"allow_abbreviated_account_matching": False}))
    assert load_preferences(path).import_preview_mode == "always"
    path.write_text(json.dumps({"allow_abbreviated_account_matching": False, "import_preview_mode": bad}))
    with pytest.raises(ValueError, match="v2_preferences_shape"):
        load_preferences(path)
    save_preferences(path, V2Preferences(import_preview_mode="when_needed"))
    assert load_preferences(path).import_preview_mode == "when_needed"
