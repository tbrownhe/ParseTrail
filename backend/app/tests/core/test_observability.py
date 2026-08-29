from collections.abc import Generator

import pytest
from app.core.observability import scrub_error_event, sentry_privacy_options


@pytest.fixture(scope="module", autouse=True)
def db() -> Generator[None, None, None]:
    """Error-event scrubbing is independent of database integration."""
    yield


def test_error_event_scrubs_request_payload_and_log_breadcrumbs() -> None:
    event = {
        "request": {
            "data": {"metadata": "bank-statement.pdf", "encrypted_key": "secret"},
            "cookies": {"session": "secret"},
            "env": {"REMOTE_ADDR": "192.0.2.1"},
            "headers": {
                "Authorization": "Bearer secret",
                "Cookie": "session=secret",
                "Content-Type": "multipart/form-data",
                "X-Forwarded-For": "192.0.2.1",
            },
        },
        "breadcrumbs": {
            "values": [{"message": "parser extracted private statement text"}],
        },
        "message": "safe failure summary",
    }

    scrubbed = scrub_error_event(event, {})

    assert scrubbed == {
        "request": {"headers": {"Content-Type": "multipart/form-data"}},
        "message": "safe failure summary",
    }


def test_sentry_privacy_options_disable_automatic_sensitive_context() -> None:
    options = sentry_privacy_options()

    assert options["before_send"] is scrub_error_event
    assert options["enable_tracing"] is False
    assert options["include_local_variables"] is False
    assert options["max_request_body_size"] == "never"
    assert options["send_default_pii"] is False
