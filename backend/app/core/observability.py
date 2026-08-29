"""Privacy-preserving error-reporting configuration."""

from typing import Any


def scrub_error_event(event: dict[str, Any], _hint: dict[str, Any]) -> dict[str, Any]:
    """Remove request payloads and log breadcrumbs from outbound error events."""
    request = event.get("request")
    if isinstance(request, dict):
        for field in ("cookies", "data", "env"):
            request.pop(field, None)
        headers = request.get("headers")
        if isinstance(headers, dict):
            for name in list(headers):
                if name.lower() in {"authorization", "cookie", "x-forwarded-for"}:
                    headers.pop(name, None)

    # Logging can include operator-authored context. Keep it local rather than
    # automatically copying it into a third-party error event.
    event.pop("breadcrumbs", None)
    return event


def sentry_privacy_options() -> dict[str, Any]:
    """Return the mandatory privacy boundary for third-party error reporting."""
    return {
        "before_send": scrub_error_event,
        "enable_tracing": False,
        "include_local_variables": False,
        "max_request_body_size": "never",
        "send_default_pii": False,
    }
