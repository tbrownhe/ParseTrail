import json
from pathlib import Path
from typing import Any
from urllib.request import Request

from scripts.release_smoke import smoke_release


class _Response:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, maximum: int) -> bytes:
        return self.payload[:maximum]


class _Opener:
    def __init__(self, responses: dict[str, bytes]) -> None:
        self.responses = responses
        self.requests: list[Request] = []

    def __call__(self, request: Request, **_kwargs: Any) -> _Response:
        self.requests.append(request)
        return _Response(self.responses[request.full_url])


def test_smokes_public_plugin_manifest_signature_and_listing(tmp_path: Path) -> None:
    manifest = json.dumps(
        {
            "release_sequence": 4,
            "artifacts": [
                {"plugin_name": "alpha", "filename": "alpha.pyc"},
                {"plugin_name": "beta", "filename": "beta.pyc"},
            ],
        }
    ).encode()
    signature = b"s" * 64
    (tmp_path / "plugin-manifest.json").write_bytes(manifest)
    (tmp_path / "plugin-manifest.sig").write_bytes(signature)
    base = "https://api.example.test/api/v1/plugins"
    opener = _Opener(
        {
            f"{base}/manifest": manifest,
            f"{base}/manifest-signature": signature,
            f"{base}/": json.dumps([{"PLUGIN_NAME": "beta"}, {"PLUGIN_NAME": "alpha"}]).encode(),
        }
    )

    smoke_release(
        release_dir=tmp_path,
        release_kind="plugins",
        api_base_url="https://api.example.test/api/v1",
        opener=opener,
    )


def test_smokes_public_client_installer_range(tmp_path: Path) -> None:
    installer_name = "parsetrail_1.3.0_win64_setup.exe"
    manifest = json.dumps(
        {
            "release_sequence": 5,
            "artifacts": [
                {
                    "filename": installer_name,
                    "platform": "win64",
                    "version": "1.3.0",
                }
            ],
        }
    ).encode()
    signature = b"s" * 64
    (tmp_path / "client-manifest.json").write_bytes(manifest)
    (tmp_path / "client-manifest.sig").write_bytes(signature)
    (tmp_path / installer_name).write_bytes(b"MZ installer")
    base = "https://api.example.test/api/v1/clients/win64"
    opener = _Opener(
        {
            f"{base}/manifest": manifest,
            f"{base}/manifest-signature": signature,
            f"{base}/1.3.0": b"M",
        }
    )

    smoke_release(
        release_dir=tmp_path,
        release_kind="client",
        api_base_url="https://api.example.test/api/v1",
        platform="win64",
        opener=opener,
    )

    assert opener.requests[-1].get_header("Range") == "bytes=0-0"
