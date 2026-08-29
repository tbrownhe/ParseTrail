"""Bounded HTTP transport and user-safe network error translation."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Final

import requests
from requests.adapters import HTTPAdapter
from urllib3 import exceptions as urllib3_exceptions
from urllib3.util.retry import Retry

DEFAULT_TIMEOUT: Final = (5.0, 30.0)
UPLOAD_TIMEOUT: Final = (5.0, 60.0)
IDEMPOTENT_RETRIES: Final = 2
IDEMPOTENT_METHODS: Final = frozenset({"DELETE", "GET", "HEAD", "OPTIONS", "PUT"})
RETRY_STATUS_CODES: Final = frozenset({429, 502, 503, 504})


class NetworkError(RuntimeError):
    """A remote operation failed without exposing its response body."""


class NetworkTimeoutError(NetworkError):
    """A connect, read, or streamed-response deadline expired."""


class NetworkUnavailableError(NetworkError):
    """The remote service could not be reached or disconnected."""


class RemoteServiceError(NetworkError):
    """The server returned an unsuccessful HTTP response."""

    def __init__(self, status_code: int, action: str) -> None:
        self.status_code = status_code
        self.action = action
        super().__init__(f"The server rejected the request while {action} (HTTP {status_code}).")


def _translated_exception(exc: requests.RequestException, action: str) -> NetworkError:
    pending: list[BaseException] = [exc]
    seen: set[int] = set()
    caused_by_timeout = False
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, (requests.Timeout, urllib3_exceptions.TimeoutError)):
            caused_by_timeout = True
            break
        pending.extend(arg for arg in current.args if isinstance(arg, BaseException))
        if current.__cause__ is not None:
            pending.append(current.__cause__)
        if current.__context__ is not None:
            pending.append(current.__context__)

    if caused_by_timeout:
        return NetworkTimeoutError(f"The server timed out while {action}.")
    if isinstance(
        exc,
        (requests.ConnectionError, requests.exceptions.ChunkedEncodingError),
    ):
        return NetworkUnavailableError(f"The server connection failed while {action}.")
    return NetworkError(f"The network request failed while {action}.")


def raise_for_response(response: requests.Response, action: str) -> None:
    """Raise a stable error containing status only, never an untrusted body."""
    if response.status_code >= 400:
        status_code = response.status_code
        response.close()
        raise RemoteServiceError(status_code, action)


class HttpTransport:
    """Requests transport with bounded idempotent retries and explicit timeouts."""

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        timeout: tuple[float, float] = DEFAULT_TIMEOUT,
        retries: int = IDEMPOTENT_RETRIES,
    ) -> None:
        self.session = session or requests.Session()
        self.timeout = timeout
        retry_policy = Retry(
            total=retries,
            connect=retries,
            read=retries,
            status=retries,
            allowed_methods=IDEMPOTENT_METHODS,
            status_forcelist=RETRY_STATUS_CODES,
            backoff_factor=0.2,
            respect_retry_after_header=True,
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry_policy)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def request(
        self,
        method: str,
        url: str,
        *,
        action: str,
        timeout: tuple[float, float] | None = None,
        **kwargs,
    ) -> requests.Response:
        try:
            return self.session.request(
                method,
                url,
                timeout=timeout or self.timeout,
                **kwargs,
            )
        except requests.RequestException as exc:
            raise _translated_exception(exc, action) from exc

    @staticmethod
    def iter_content(
        response: requests.Response,
        *,
        action: str,
        chunk_size: int = 8192,
    ) -> Iterator[bytes]:
        """Translate failures that happen after streamed response headers arrive."""
        try:
            yield from response.iter_content(chunk_size=chunk_size)
        except requests.RequestException as exc:
            raise _translated_exception(exc, action) from exc
