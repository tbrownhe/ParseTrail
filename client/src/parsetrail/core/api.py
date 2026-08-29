import json
from collections.abc import Iterable

import requests

from parsetrail.core.auth import AuthError, AuthManager, auth_manager
from parsetrail.core.client_manifest import INSTALLER_SUFFIXES, MAX_CLIENT_MANIFEST_BYTES
from parsetrail.core.network import UPLOAD_TIMEOUT, HttpTransport, raise_for_response
from parsetrail.core.settings import AppSettings, settings

# API Routes
PLUGIN_PATH = "/plugins"
CLIENT_PATH = "/clients"
KEYS_PATH = "/keys"
STATEMENTS_PATH = "/statements"
MAX_PLUGIN_MANIFEST_BYTES = 1024 * 1024
ED25519_SIGNATURE_BYTES = 64


class ApiClient:
    def __init__(
        self,
        settings: AppSettings,
        auth_manager: AuthManager,
        *,
        transport: HttpTransport | None = None,
    ):
        self.settings = settings
        self.auth = auth_manager
        self.transport = transport or auth_manager.transport

    def _request(self, method: str, path: str, *, auth_required: bool, **kwargs) -> requests.Response:
        url = f"{self.auth.base_url}{path}"
        action = kwargs.pop("action", "contacting the ParseTrail service")
        headers = dict(kwargs.pop("headers", {}))
        timeout = kwargs.pop("timeout", None)

        if auth_required:
            headers.update(self.auth.get_auth_headers())

        resp = self.transport.request(
            method,
            url,
            action=action,
            headers=headers,
            timeout=timeout,
            **kwargs,
        )

        if auth_required and resp.status_code == 401:
            self.auth.clear_token()
            resp.close()
            raise AuthError("The saved login was rejected. Please sign in again.")

        raise_for_response(resp, action)
        return resp

    # Convenience wrappers
    def get(self, path: str, auth_required: bool = True, **kwargs) -> requests.Response:
        return self._request("GET", path, auth_required=auth_required, **kwargs)

    def post(self, path: str, auth_required: bool = True, **kwargs) -> requests.Response:
        return self._request("POST", path, auth_required=auth_required, **kwargs)

    def list_installers(self) -> list[dict]:
        raise NotImplementedError("Unsigned client metadata is not trusted; fetch_client_release_bytes()")

    def list_plugins(self) -> list[dict]:
        raise NotImplementedError("Unsigned plugin metadata is not trusted; fetch_plugin_release_bytes()")

    def _download_stream(
        self, path: str, auth_required: bool = True, chunk_size=8192
    ) -> Iterable[tuple[bytes, int, int]]:
        action = "downloading an authenticated artifact"
        resp = self.get(
            path,
            auth_required=auth_required,
            stream=True,
            action=action,
        )

        total = int(resp.headers.get("Content-Length", 0))
        downloaded = 0

        try:
            for chunk in self.transport.iter_content(
                resp,
                action=action,
                chunk_size=chunk_size,
            ):
                if not chunk:
                    continue
                downloaded += len(chunk)
                yield chunk, downloaded, total
        finally:
            resp.close()

    def _get_bounded_bytes(
        self,
        path: str,
        *,
        maximum_bytes: int,
        auth_required: bool,
    ) -> bytes:
        action = "fetching authenticated release metadata"
        resp = self.get(
            path,
            auth_required=auth_required,
            stream=True,
            action=action,
        )
        try:
            content_length = resp.headers.get("Content-Length")
            if content_length is not None:
                try:
                    advertised_size = int(content_length)
                except ValueError as exc:
                    raise ValueError("Server returned an invalid Content-Length") from exc
                if advertised_size > maximum_bytes:
                    raise ValueError(f"Response exceeds {maximum_bytes} bytes")

            payload = bytearray()
            for chunk in self.transport.iter_content(
                resp,
                action=action,
            ):
                if not chunk:
                    continue
                payload.extend(chunk)
                if len(payload) > maximum_bytes:
                    raise ValueError(f"Response exceeds {maximum_bytes} bytes")
            return bytes(payload)
        finally:
            resp.close()

    def fetch_plugin_release_bytes(self) -> tuple[bytes, bytes]:
        """Fetch bounded, still-untrusted manifest bytes and detached signature."""
        manifest = self._get_bounded_bytes(
            f"{PLUGIN_PATH}/manifest",
            maximum_bytes=MAX_PLUGIN_MANIFEST_BYTES,
            auth_required=False,
        )
        signature = self._get_bounded_bytes(
            f"{PLUGIN_PATH}/manifest-signature",
            maximum_bytes=ED25519_SIGNATURE_BYTES,
            auth_required=False,
        )
        return manifest, signature

    def fetch_client_release_bytes(self, platform: str) -> tuple[bytes, bytes]:
        """Fetch bounded, still-untrusted installer metadata for one platform."""
        if platform not in INSTALLER_SUFFIXES:
            raise ValueError(f"Unsupported client platform: {platform}")
        manifest = self._get_bounded_bytes(
            f"{CLIENT_PATH}/{platform}/manifest",
            maximum_bytes=MAX_CLIENT_MANIFEST_BYTES,
            auth_required=False,
        )
        signature = self._get_bounded_bytes(
            f"{CLIENT_PATH}/{platform}/manifest-signature",
            maximum_bytes=ED25519_SIGNATURE_BYTES,
            auth_required=False,
        )
        return manifest, signature

    def stream_installer(self, platform: str, version: str) -> Iterable[tuple[bytes, int, int]]:
        """
        Usage:
            with fpath.open("wb") as f:
                for chunk, downloaded, total in stream_installer(platform, version):
                    f.write(chunk)
                    dialog.update_progress(downloaded, total)
                    if dialog.was_cancelled():
                        break

        Args:
            platform (str): _description_
            version (str): _description_
            auth_required (bool, optional): _description_. Defaults to False.

        Returns:
            Iterable[Tuple[bytes, int, int]]: _description_
        """
        return self._download_stream(f"{CLIENT_PATH}/{platform}/{version}", auth_required=False)

    def stream_plugin(self, plugin_name: str) -> Iterable[tuple[bytes, int, int]]:
        """
        Usage:
            with fpath.open("wb") as f:
                for chunk, downloaded, total in stream_plugin(plugin_name):
                    f.write(chunk)
                    dialog.update_progress(downloaded, total)
                    if dialog.was_cancelled():
                        break

        Args:
            platform (str): _description_
            version (str): _description_
            auth_required (bool, optional): _description_. Defaults to False.

        Returns:
            Iterable[Tuple[bytes, int, int]]: _description_
        """
        return self._download_stream(f"{PLUGIN_PATH}/{plugin_name}", auth_required=True)

    def get_public_key(self) -> bytes:
        resp = self.get(
            f"{KEYS_PATH}/public-key",
            auth_required=False,
            action="fetching the statement-encryption key",
        )
        return resp.content

    def get_public_key_hash(self) -> str:
        resp = self.get(
            f"{KEYS_PATH}/public-key-hash",
            auth_required=False,
            action="validating the statement-encryption key",
        )
        return resp.json()["hash"]

    def submit_statement(self, encrypted_file: bytes, encrypted_key: str, metadata: dict[str]) -> requests.Response:
        files = {"file": encrypted_file}
        data = {"metadata": json.dumps(metadata), "encrypted_key": encrypted_key}
        return self.post(
            f"{STATEMENTS_PATH}/submit-statement",
            auth_required=True,
            action="submitting the encrypted statement",
            timeout=UPLOAD_TIMEOUT,
            files=files,
            data=data,
        )


api_client = ApiClient(settings, auth_manager)
