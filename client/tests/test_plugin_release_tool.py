import json
import py_compile
from pathlib import Path

import pytest
from parsetrail.core.plugin_manifest import (
    PluginSignatureError,
    load_trusted_plugin_keys,
)
from scripts.plugin_release import (
    CLIENT_ROOT,
    generate_key,
    load_private_key,
    sign_release,
    verify_release,
)


def test_generates_encrypted_private_key_and_public_trust_entry(
    tmp_path: Path,
) -> None:
    private_key_path = tmp_path / "offline" / "plugin-signing-key.pem"
    trust_store_path = tmp_path / "plugin-release-keys.json"
    passphrase = b"a sufficiently long test passphrase"

    key_id = generate_key(private_key_path, trust_store_path, passphrase)

    assert b"BEGIN ENCRYPTED PRIVATE KEY" in private_key_path.read_bytes()
    assert private_key_path.name not in trust_store_path.read_text(encoding="utf-8")
    assert key_id in load_trusted_plugin_keys(trust_store_path)
    assert load_private_key(private_key_path, passphrase)


def test_refuses_private_key_inside_repository() -> None:
    with pytest.raises(ValueError, match="outside the repository"):
        generate_key(
            CLIENT_ROOT / "do-not-create.pem",
            CLIENT_ROOT / "do-not-create.json",
            b"a sufficiently long test passphrase",
        )


def test_refuses_unencrypted_private_key(tmp_path: Path) -> None:
    private_key_path = tmp_path / "unencrypted.pem"
    private_key_path.write_text(
        "-----BEGIN PRIVATE KEY-----\nnot-a-key\n-----END PRIVATE KEY-----\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unencrypted"):
        load_private_key(private_key_path, b"irrelevant but long passphrase")


def test_empty_public_trust_store_fails_closed(tmp_path: Path) -> None:
    trust_store_path = tmp_path / "plugin-release-keys.json"
    trust_store_path.write_text(
        json.dumps({"schema_version": 1, "keys": []}),
        encoding="utf-8",
    )

    with pytest.raises(PluginSignatureError, match="contains no public keys"):
        load_trusted_plugin_keys(trust_store_path)


def test_signs_and_verifies_complete_plugin_directory(tmp_path: Path) -> None:
    passphrase = b"a sufficiently long test passphrase"
    private_key_path = tmp_path / "offline" / "plugin-signing-key.pem"
    trust_store_path = tmp_path / "plugin-release-keys.json"
    plugin_dir = tmp_path / "plugins"
    plugin_dir.mkdir()
    generate_key(private_key_path, trust_store_path, passphrase)

    source_path = plugin_dir / "release_plugin.py"
    source_path.write_text(
        "\n".join(
            [
                "from parsetrail.core.interfaces import IParser",
                "class Parser(IParser):",
                "    PLUGIN_NAME = 'release_plugin'",
                "    VERSION = '2.0.0'",
                "    MIN_CLIENT_VERSION = '1.1.0'",
                "    SUFFIX = '.pdf'",
                "    COMPANY = 'Release Bank'",
                "    STATEMENT_TYPE = 'Release Statement'",
                "    SEARCH_STRING = 'release'",
                "    INSTRUCTIONS = 'Download it.'",
                "    def parse(self, input_data):",
                "        return input_data",
            ]
        ),
        encoding="utf-8",
    )
    compiled_path = plugin_dir / "release_plugin.pyc"
    py_compile.compile(source_path, cfile=compiled_path, doraise=True)

    manifest = sign_release(
        plugin_dir,
        private_key_path,
        trust_store_path,
        passphrase,
        source_commit="a" * 40,
        release_sequence=202607230001,
    )
    verified = verify_release(plugin_dir, trust_store_path)

    assert manifest == verified
    assert manifest.artifacts[0].plugin_name == "release_plugin"
    assert manifest.source_commit == "a" * 40
    assert not list(plugin_dir.glob("*.pem"))
