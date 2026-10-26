"""Unsigned catalog review never authenticates a release or opens a signing key."""

from __future__ import annotations

import errno
import hashlib
import json
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from parsetrail.core.v2_catalog_admission import admit_pilot_definition
from parsetrail.core.v2_data_catalog import (
    MAX_CATALOG_BYTES,
    CatalogCache,
    CatalogError,
    CatalogRollbackError,
    key_id_for_public_key,
)

from scripts import v2_catalog_prepare as prepare
from scripts import v2_catalog_release as release

DEFINITIONS = Path(__file__).parents[2] / "devtools/parser_engine_pilot"


@pytest.fixture
def keys():
    private = Ed25519PrivateKey.generate()
    public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return private, public, {key_id_for_public_key(public): public}


def _bytes(public, *, sequence=3):
    return release.unsigned_catalog_bytes(DEFINITIONS, public, release_sequence=sequence, source_revision="a" * 40)


def _json_bytes(data):
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode()


def test_prepare_is_exact_deterministic_public_review_and_signed_api_compatible(tmp_path, keys):
    private, public, trusted = keys
    expected, signature, verified = release.signed_catalog_bytes(
        DEFINITIONS, private, release_sequence=3, source_revision="a" * 40
    )
    prepared = prepare.prepare_catalog(
        DEFINITIONS, public, tmp_path / "unsigned", release_sequence=3, source_revision="a" * 40
    )
    assert prepared.snapshot == expected == _bytes(public)
    assert prepared.sha256 == hashlib.sha256(expected).hexdigest()
    assert len(prepared.envelope.definitions) == 23
    assert (tmp_path / "unsigned/catalog.json").read_bytes() == expected
    assert not (tmp_path / "unsigned/catalog.sig").exists()
    review = json.loads((tmp_path / "unsigned/review.json").read_bytes())
    assert review["unsigned"] is True and review["definition_count"] == 23
    assert review["catalog_sha256"] == prepared.sha256
    assert all("content_base64" not in item and item["account_context"] is not None for item in review["definitions"])
    assert "detached signature" in review["activation"]
    assert (tmp_path / "unsigned/catalog.sha256").read_text() == prepared.sha256 + "  catalog.json\n"
    assert release.sign_prepared_catalog(expected, private, expected_sha256=prepared.sha256) == (
        expected,
        signature,
        verified,
    )
    cache = CatalogCache(tmp_path / "cache", trusted, admit_pilot_definition)
    with pytest.raises(CatalogError):
        cache.activate_directory(tmp_path / "unsigned")
    assert not cache.root.exists()
    with pytest.raises(CatalogError, match="invalid_signature"):
        cache.activate(expected, bytes(64))
    assert not cache.root.exists()


def test_exact_prepared_signing_is_independent_of_mutable_definition_directory(tmp_path, keys):
    private, public, trusted = keys
    definitions = tmp_path / "definitions"
    definitions.mkdir()
    source = DEFINITIONS / "synchrony-table-pilot-definition.json"
    destination = definitions / source.name
    destination.write_bytes(source.read_bytes())
    prepared = prepare.prepare_catalog(
        definitions, public, tmp_path / "unsigned", release_sequence=3, source_revision="a" * 40
    )
    destination.write_bytes(b'{"operation":"python_eval"}')
    verified = release.write_prepared_release(
        prepared.snapshot, private, tmp_path / "signed", expected_sha256=prepared.sha256
    )
    assert verified.snapshot == prepared.snapshot
    assert (tmp_path / "signed/catalog.json").read_bytes() == prepared.snapshot
    cache = CatalogCache(tmp_path / "cache", trusted, admit_pilot_definition)
    assert cache.activate_directory(tmp_path / "signed") == verified
    assert cache.load_current() == verified
    old, old_signature, _ = release.sign_prepared_catalog(
        _bytes(public, sequence=2), private, expected_sha256=hashlib.sha256(_bytes(public, sequence=2)).hexdigest()
    )
    pointer = (cache.root / "current.json").read_bytes()
    with pytest.raises(CatalogRollbackError):
        cache.activate(old, old_signature)
    assert (cache.root / "current.json").read_bytes() == pointer


@pytest.mark.parametrize(
    "change",
    [
        {"schema_version": True},
        {"engine_contract": True},
        {"release_sequence": True},
        {"schema_version": 2},
        {"engine_contract": 2},
        {"release_sequence": 0},
        {"source_revision": "unknown"},
        {"key_id": "unknown"},
        {"extra": True},
        {"definitions": []},
    ],
)
def test_prepared_metadata_refuses_untyped_unsupported_or_unknown_fields(keys, change):
    data = json.loads(_bytes(keys[1]))
    data.update(change)
    with pytest.raises(ValueError):
        release.validate_prepared_catalog(_json_bytes(data))


@pytest.mark.parametrize(
    "change",
    [
        {"size": 1},
        {"sha256": "0" * 64},
        {"parser_id": "other_parser"},
        {"revision": "other_revision"},
        {"suffix": ".csv"},
        {"content_base64": "!invalid!"},
        {"account_context": {"institution_key": "citi", "kind": "equity"}},
        {"unexpected": "field"},
    ],
)
def test_prepared_definition_refuses_changed_identity_hash_context_and_fields(keys, change):
    data = json.loads(_bytes(keys[1]))
    # A one-definition input isolates identity checking from the sorted-ID guard.
    data["definitions"] = [data["definitions"][0]]
    data["definitions"][0].update(change)
    with pytest.raises(ValueError):
        release.validate_prepared_catalog(_json_bytes(data))


@pytest.mark.parametrize(
    "raw",
    [b"", b"{}", b"{", b"\xff", b"{" * 11000 + b"}" * 11000, b"x" * (MAX_CATALOG_BYTES + 1)],
    ids=["empty", "missing-fields", "truncated", "non-utf8", "overdeep", "oversized"],
)
def test_prepared_malformed_oversized_and_deep_inputs_are_controlled(raw):
    with pytest.raises(ValueError):
        release.validate_prepared_catalog(raw)


def test_duplicate_keys_and_duplicate_definitions_are_refused(keys):
    raw = _bytes(keys[1])
    with pytest.raises(ValueError):
        release.validate_prepared_catalog(raw.replace(b'"schema_version":1', b'"schema_version":1,"schema_version":1'))
    data = json.loads(raw)
    data["definitions"] = [data["definitions"][0], data["definitions"][0]]
    with pytest.raises(ValueError):
        release.validate_prepared_catalog(_json_bytes(data))


def test_signing_refuses_wrong_review_digest_or_different_public_key_before_sign(keys):
    private, public, _ = keys
    snapshot = _bytes(public)
    sha = hashlib.sha256(snapshot).hexdigest()
    for digest in (None, "", "0" * 64):
        with pytest.raises(ValueError):
            release.sign_prepared_catalog(snapshot, private, expected_sha256=digest)
    with pytest.raises(ValueError, match="key_mismatch"):
        release.sign_prepared_catalog(snapshot, Ed25519PrivateKey.generate(), expected_sha256=sha)


def test_prepare_cli_uses_only_shipped_public_key_without_prompt_or_key_load(tmp_path, keys, monkeypatch, capsys):
    _private, public, trusted = keys
    monkeypatch.setattr(prepare, "load_trusted_catalog_keys", lambda: trusted)
    monkeypatch.setattr(release, "load_offline_key", lambda *_: pytest.fail("Preparation loaded a private key"))
    monkeypatch.setattr(release.getpass, "getpass", lambda *_: pytest.fail("Preparation requested a passphrase"))
    argv = [
        "--definitions-dir",
        str(DEFINITIONS),
        "--key-id",
        key_id_for_public_key(public),
        "--output-dir",
        str(tmp_path / "prepared"),
        "--release-sequence",
        "3",
        "--source-revision",
        "a" * 40,
    ]
    assert prepare.main(argv) == 0
    assert "UNSIGNED" in capsys.readouterr().out
    argv[3] = "data-ed25519-" + "0" * 32
    with pytest.raises(SystemExit):
        prepare.main(argv)


def test_prepared_sign_cli_validates_bytes_digest_and_public_identity_before_key_prompt(tmp_path, keys, monkeypatch):
    _private, public, trusted = keys
    source = tmp_path / "catalog.json"
    snapshot = _bytes(public)
    source.write_bytes(snapshot)
    monkeypatch.setattr(release, "load_trusted_catalog_keys", lambda *_: trusted)
    monkeypatch.setattr(release, "load_offline_key", lambda *_: pytest.fail("Invalid prepared input loaded key"))
    monkeypatch.setattr(release.getpass, "getpass", lambda *_: pytest.fail("Invalid prepared input prompted"))
    argv = [
        "--prepared-catalog",
        str(source),
        "--private-key",
        str(tmp_path / "unused.pem"),
        "--output-dir",
        str(tmp_path / "signed"),
        "--expected-sha256",
        "0" * 64,
    ]
    with pytest.raises(SystemExit):
        release.main(argv)
    argv[-1] = hashlib.sha256(snapshot).hexdigest()
    monkeypatch.setattr(release, "load_trusted_catalog_keys", lambda: {})
    with pytest.raises(ValueError, match="key_not_shipped"):
        release.main(argv)
    source.write_bytes(b'{"unexpected":"field"}')
    with pytest.raises(ValueError):
        release.main(argv)
    assert not (tmp_path / "signed").exists()


def test_prepared_sign_cli_uses_only_in_memory_fixture_key_and_exact_reviewed_bytes(tmp_path, keys, monkeypatch):
    private, public, trusted = keys
    source = tmp_path / "catalog.json"
    snapshot = _bytes(public)
    source.write_bytes(snapshot)
    unused_key_path = tmp_path / "fixture-key-never-read.pem"
    calls = []
    monkeypatch.setattr(release, "load_trusted_catalog_keys", lambda *_: trusted)
    monkeypatch.setattr(release.getpass, "getpass", lambda *_: "fixture-only")
    monkeypatch.setattr(release, "load_offline_key", lambda path, password: calls.append((path, password)) or private)
    assert (
        release.main(
            [
                "--prepared-catalog",
                str(source),
                "--private-key",
                str(unused_key_path),
                "--output-dir",
                str(tmp_path / "signed"),
                "--expected-sha256",
                hashlib.sha256(snapshot).hexdigest(),
            ]
        )
        == 0
    )
    assert calls == [(unused_key_path, b"fixture-only")] and not unused_key_path.exists()
    assert (tmp_path / "signed/catalog.json").read_bytes() == snapshot
    cache = CatalogCache(tmp_path / "cache", trusted, admit_pilot_definition)
    assert cache.activate_directory(tmp_path / "signed").snapshot == snapshot


def test_prepare_refuses_existing_output_and_cleans_failed_publication(tmp_path, keys, monkeypatch):
    output = tmp_path / "existing"
    output.mkdir()
    (output / "sentinel").write_bytes(b"keep")
    with pytest.raises(FileExistsError):
        prepare.prepare_catalog(DEFINITIONS, keys[1], output, release_sequence=3, source_revision="a" * 40)
    assert (output / "sentinel").read_bytes() == b"keep"
    original = Path.write_bytes

    def fail_review(path, data):
        if path.name == "review.json":
            raise OSError("Synthetic publication failure")
        return original(path, data)

    monkeypatch.setattr(Path, "write_bytes", fail_review)
    with pytest.raises(OSError):
        prepare.prepare_catalog(DEFINITIONS, keys[1], tmp_path / "failed", release_sequence=3, source_revision="a" * 40)
    assert not (tmp_path / "failed").exists()
    assert not list(tmp_path.glob("v2-catalog-*"))


def test_prepared_selected_symlink_refused(tmp_path, keys):
    source = tmp_path / "catalog.json"
    source.write_bytes(_bytes(keys[1]))
    selected = tmp_path / "link.json"
    try:
        selected.symlink_to(source)
    except OSError:
        pytest.skip("Native symlink creation unavailable")
    with pytest.raises(ValueError, match="prepared_catalog_file"):
        release.read_prepared_catalog(selected)
    output = tmp_path / "output-link"
    output.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match="output_symlink"):
        prepare.prepare_catalog(DEFINITIONS, keys[1], output, release_sequence=3, source_revision="a" * 40)


def test_context_read_stays_bounded_if_file_grows_after_stat(tmp_path, keys, monkeypatch):
    definitions = tmp_path / "definitions"
    definitions.mkdir()
    source = DEFINITIONS / "synchrony-table-pilot-definition.json"
    (definitions / source.name).write_bytes(source.read_bytes())
    context = definitions / "account-contexts.json"
    small = b'{"synchrony_amazon_store_card":{"institution_key":"synchrony","kind":"liability"}}'
    context.write_bytes(small)
    original = Path.open

    def grow_before_read(path, *args, **kwargs):
        if path == context and args == ("rb",):
            with original(path, "wb") as stream:
                stream.write(small + b" " * (20 * 1024))
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", grow_before_read)
    with pytest.raises(ValueError, match="account_context_manifest_shape"):
        prepare.prepare_catalog(
            definitions, keys[1], tmp_path / "refused", release_sequence=3, source_revision="a" * 40
        )
    assert not (tmp_path / "refused").exists()


def test_racing_empty_output_is_not_replaced_and_staging_is_cleaned(tmp_path, keys, monkeypatch):
    output = tmp_path / "raced"
    rename = release._rename_directory_no_replace

    def race(source, destination):
        destination.mkdir()
        rename(source, destination)

    monkeypatch.setattr(release, "_rename_directory_no_replace", race)
    with pytest.raises(FileExistsError):
        prepare.prepare_catalog(DEFINITIONS, keys[1], output, release_sequence=3, source_revision="a" * 40)
    assert output.is_dir() and list(output.iterdir()) == []
    assert not list(tmp_path.glob("v2-catalog-*"))


@pytest.mark.parametrize("platform,flags", [("darwin", 4), ("linux", 1)])
@pytest.mark.parametrize("code", [0, errno.EEXIST, errno.ENOTSUP])
def test_native_publication_uses_no_replace_flags_and_preserves_errors(tmp_path, monkeypatch, platform, flags, code):
    calls = []

    class NativeCall:
        def __call__(self, *args):
            calls.append(args)
            return -1 if code else 0

    call = NativeCall()

    class Library:
        renamex_np = call
        renameat2 = call

    monkeypatch.setattr(release.sys, "platform", platform)
    monkeypatch.setattr(release.ctypes, "CDLL", lambda *args, **kwargs: Library())
    monkeypatch.setattr(release.ctypes, "get_errno", lambda: code)
    source, target = tmp_path / "source", tmp_path / "target"
    if code:
        with pytest.raises(OSError) as error:
            release._rename_directory_no_replace(source, target)
        assert error.value.errno == code
    else:
        release._rename_directory_no_replace(source, target)
    assert calls[0][-1] == flags
    assert len(calls[0]) == (3 if platform == "darwin" else 5)
    assert calls[0][-2] == bytes(target)


def test_missing_exclusive_primitive_refuses_without_fallback(tmp_path, monkeypatch):
    monkeypatch.setattr(release.sys, "platform", "darwin")
    monkeypatch.setattr(release.ctypes, "CDLL", lambda *args, **kwargs: object())
    with pytest.raises(OSError, match="exclusive_directory_publication_unavailable"):
        release._rename_directory_no_replace(tmp_path / "source", tmp_path / "target")
