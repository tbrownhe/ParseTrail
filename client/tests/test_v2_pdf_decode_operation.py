"""Bounded PDF reuse ends with the confirmed synchronous import operation."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError

import pytest
from parsetrail.core import v2_bounded_pdf_text as module
from parsetrail.core.v2_worker_limits import WorkerError, WorkerLimits


@pytest.fixture
def worker(monkeypatch):
    calls = []

    def run(mode, source, **kwargs):
        calls.append((mode, source, kwargs["limits"]))
        return b'{"pages":["Public synthetic text"],"metadata":{"Title":"Synthetic"}}'

    monkeypatch.setattr(module, "run_worker", run)
    return calls


def test_reuses_only_exact_source_mode_and_limits_inside_operation(worker):
    with module.pdf_decode_operation():
        first = module.decode_pdf(b"synthetic one")
        assert module.decode_pdf(b"synthetic one") is first
        module.decode_pdf(b"synthetic two")
        module.decode_pdf_layout(b"synthetic one")
        module.decode_pdf_default_layout(b"synthetic one")
        module.decode_pdf(b"synthetic one", WorkerLimits(wall_seconds=10))
        with pytest.raises(FrozenInstanceError):
            first.pages = ("changed",)
    assert len(worker) == 5
    module.decode_pdf(b"synthetic one")
    module.decode_pdf(b"synthetic one")
    assert len(worker) == 7
    assert module._operation_decodes.get() is None


def test_cancellation_is_checked_before_cached_return_and_after_worker(worker):
    with module.pdf_decode_operation():
        module.decode_pdf(b"synthetic")
        with pytest.raises(WorkerError, match="cancelled"):
            module.decode_pdf(b"synthetic", cancelled=lambda: True)
        assert len(worker) == 1
        hit_checks = iter((False, True))
        with pytest.raises(WorkerError, match="cancelled"):
            module.decode_pdf(b"synthetic", cancelled=lambda: next(hit_checks))
        assert len(worker) == 1
        checks = iter((False, True))
        with pytest.raises(WorkerError, match="cancelled"):
            module.decode_pdf(b"new synthetic", cancelled=lambda: next(checks))
        assert len(worker) == 2
        module.decode_pdf(b"new synthetic")
        assert len(worker) == 3  # Cancelled output was not retained.


def test_refused_output_and_failures_are_never_cached(worker, monkeypatch):
    good = module.run_worker
    with module.pdf_decode_operation():
        monkeypatch.setattr(module, "run_worker", lambda *_a, **_k: b'{"pages":[],"metadata":{}}')
        with pytest.raises(WorkerError, match="invalid_output"):
            module.decode_pdf(b"synthetic")
        monkeypatch.setattr(module, "run_worker", good)
        module.decode_pdf(b"synthetic")
    assert len(worker) == 1


@pytest.mark.parametrize("failure", [RuntimeError("failure"), WorkerError("cancelled")])
def test_operation_clears_references_and_resets_context_on_failure(worker, failure):
    held = None
    with pytest.raises(type(failure)):
        with module.pdf_decode_operation():
            module.decode_pdf(b"synthetic")
            held = module._operation_decodes.get()
            raise failure
    assert held == {}
    assert module._operation_decodes.get() is None
    with module.pdf_decode_operation():
        module.decode_pdf(b"synthetic")
    assert len(worker) == 2


def test_nested_operations_and_threads_are_isolated(worker):
    with module.pdf_decode_operation():
        first = module.decode_pdf(b"synthetic")
        with module.pdf_decode_operation():
            assert module.decode_pdf(b"synthetic") is not first
        assert module.decode_pdf(b"synthetic") is first
        with ThreadPoolExecutor(max_workers=1) as pool:
            other = pool.submit(module.decode_pdf, b"synthetic").result()
            assert other is not first
    assert len(worker) == 3


def test_confirmed_capital_auto_import_rechecks_share_one_bounded_child(tmp_path, monkeypatch):
    import json

    # Build an isolated catalog from the public Capital Auto declaration.
    from pathlib import Path

    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from parsetrail.core.v2_data_catalog import key_id_for_public_key
    from parsetrail.core.v2_import_accounts import ImportAccountChoice, prepare_import_accounts
    from parsetrail.core.v2_profile_store import FinancialAccount, V2ProfileStore
    from parsetrail.core.v2_workspace import V2Workspace
    from scripts.v2_catalog_release import signed_catalog_bytes

    from devtools.parser_engine_pilot.synthetic_family_sources import family_sources

    pilot = Path(__file__).resolve().parents[2] / "devtools/parser_engine_pilot"
    case = next(c for c in family_sources() if c.definition_name == "capital-one-loan-pilot-definition.json")
    definitions = tmp_path / "definitions"
    definitions.mkdir()
    (definitions / case.definition_name).write_bytes((pilot / case.definition_name).read_bytes())
    (definitions / "account-contexts.json").write_text(
        json.dumps({"pdf_capitaloneauto_202402": {"institution_key": "capital_one", "kind": "liability"}})
    )
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    snapshot, signature, _ = signed_catalog_bytes(definitions, private, release_sequence=1, source_revision="a" * 40)
    workspace = V2Workspace.create(
        tmp_path / "profile.db",
        tmp_path / "catalog",
        trusted_keys={key_id_for_public_key(public): public},
        preferences_path=tmp_path / "preferences.json",
    )
    workspace.catalog_cache.activate(snapshot, signature)
    source = tmp_path / "public-synthetic.pdf"
    source.write_bytes(case.source)
    run_worker = module.run_worker
    calls = []

    def run(*args, **kwargs):
        calls.append(args[0])
        return run_worker(*args, **kwargs)

    monkeypatch.setattr(module, "run_worker", run)
    seen = []

    def review(_path, proposed):
        seen.append(proposed)
        calls.clear()  # Start at the confirmed review boundary.
        account = FinancialAccount(
            "loan",
            "Synthetic Auto Loan",
            "liability",
            "capital_one",
            tracking_scope="principal_component",
            product_type="loan",
        )
        return prepare_import_accounts(
            proposed,
            tuple(ImportAccountChoice(g.group_id, account.id) for g in proposed.groups),
            proposed.recognition.candidates[0].parser_id,
            new_accounts=(account,),
        )

    result = workspace.import_file(source, review_import=review)
    assert len(seen) == 1 and calls == ["pdf_text_simple"]
    assert module._operation_decodes.get() is None
    with V2ProfileStore.open(workspace.profile_path, read_only=True) as store:
        assert store.load_import(result.source_sha256).source == case.source
        assert store.source_account_bindings(result.source_sha256)[0].ledger_account_id == "loan"
        assert store.connection.execute("SELECT count(*) FROM JournalEntries").fetchone() == (0,)
