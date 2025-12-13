import json
from typing import Iterable, Tuple

import requests
from loguru import logger
from parsetrail.core.auth import AuthError, AuthManager, auth_manager
from parsetrail.core.settings import AppSettings, settings

# API Routes
PLUGIN_PATH = "/plugins"
CLIENT_PATH = "/clients"
KEYS_PATH = "/keys"
MODEL_PATH = "/models"
STATEMENTS_PATH = "/statements"


class ApiClient:
    def __init__(self, settings: AppSettings, auth_manager: AuthManager):
        self.settings = settings
        self.auth = auth_manager

    def _request(self, method: str, path: str, *, auth_required: bool, **kwargs) -> requests.Response:
        url = f"{self.auth.base_url}{path}"

        headers = kwargs.pop("headers", {})

        if auth_required:
            # may auto-login via UI
            headers.update(self.auth.get_auth_headers())

        resp = requests.request(method, url, headers=headers, **kwargs)

        if auth_required and resp.status_code == 401:
            # only treat 401 as "auth broken" if we actually used auth
            self.auth.clear_token()
            raise AuthError("Token rejected by server")

        return resp

    # Convenience wrappers
    def get(self, path: str, auth_required: bool = True, **kwargs) -> requests.Response:
        return self._request("GET", path, auth_required=auth_required, **kwargs)

    def post(self, path: str, auth_required: bool = True, **kwargs) -> requests.Response:
        return self._request("POST", path, auth_required=auth_required, **kwargs)

    def _get_list(self, path: str, name: str) -> list[dict]:
        try:
            resp = self.get(path, auth_required=False, stream=False)
            resp.raise_for_status()
            data = resp.json()

            if isinstance(data, list):
                return data

            raise ValueError(f"{name} endpoint returned {type(data).__name__}, expected list[dict].")
        except requests.RequestException as e:
            logger.error(f"Error fetching {name} list: {e}")
            raise

    def list_installers(self) -> list[dict]:
        return self._get_list(f"{CLIENT_PATH}", "client")

    def list_plugins(self) -> list[dict]:
        return self._get_list(f"{PLUGIN_PATH}", "plugin")

    def list_models(self) -> list[dict]:
        raise NotImplementedError("Model listing not implemented yet")
        # return self._get_list(f"{MODEL_PATH}", "model")

    def _download_stream(
        self, path: str, auth_required: bool = True, chunk_size=8192
    ) -> Iterable[Tuple[bytes, int, int]]:
        resp = self.get(path, auth_required=auth_required, stream=True)
        resp.raise_for_status()

        total = int(resp.headers.get("Content-Length", 0))
        downloaded = 0

        try:
            for chunk in resp.iter_content(chunk_size=chunk_size):
                if not chunk:
                    continue
                downloaded += len(chunk)
                yield chunk, downloaded, total
        finally:
            resp.close()

    def stream_installer(self, platform: str, version: str) -> Iterable[Tuple[bytes, int, int]]:
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

    def stream_plugin(self, plugin_name) -> Iterable[Tuple[bytes, int, int]]:
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

    def stream_model(self, model_name) -> Iterable[Tuple[bytes, int, int]]:
        """
        Usage:
            with fpath.open("wb") as f:
                for chunk, downloaded, total in stream_model(model_name):
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
        return self._download_stream(f"{MODEL_PATH}/{model_name}", auth_required=True)

    def get_public_key(self) -> bytes:
        resp = self.get(f"{KEYS_PATH}/public-key", auth_required=False)
        resp.raise_for_status()
        return resp.content

    def get_public_key_hash(self) -> str:
        resp = self.get(f"{KEYS_PATH}/public-key-hash", auth_required=False)
        resp.raise_for_status()
        return resp.json()["hash"]

    def submit_statement(self, encrypted_file: bytes, encrypted_key: str, metadata: dict[str]) -> requests.Response:
        files = {"file": encrypted_file}
        data = {"metadata": json.dumps(metadata), "encrypted_key": encrypted_key}
        return self.post(
            f"{STATEMENTS_PATH}/submit-statement",
            auth_required=True,
            files=files,
            data=data,
        )


api_client = ApiClient(settings, auth_manager)
