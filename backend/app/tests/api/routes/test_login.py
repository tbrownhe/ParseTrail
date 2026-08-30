import uuid
from concurrent.futures import ThreadPoolExecutor
from time import perf_counter
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from app import crud
from app.core.browser_session import BROWSER_SESSION_COOKIE
from app.core.config import settings
from app.core.security import verify_password
from app.main import app
from app.models import UserCreate
from app.tests.utils.user import user_authentication_headers
from app.tests.utils.utils import random_email, random_lower_string
from app.utils import (
    EmailData,
    generate_email_verification_token,
    generate_password_reset_token,
)

RECOVERY_RESPONSE = {"message": "If the account exists, a password recovery email has been sent"}


def test_get_access_token(client: TestClient) -> None:
    login_data = {
        "username": settings.FIRST_SUPERUSER,
        "password": settings.FIRST_SUPERUSER_PASSWORD,
    }
    response = client.post(f"{settings.API_V1_STR}/login/access-token", data=login_data)
    tokens = response.json()
    assert response.status_code == 200
    assert tokens["access_token"]
    assert BROWSER_SESSION_COOKIE not in response.cookies


def test_browser_session_uses_httponly_cookie_and_enforces_origin() -> None:
    login_data = {
        "username": settings.FIRST_SUPERUSER,
        "password": settings.FIRST_SUPERUSER_PASSWORD,
    }
    with TestClient(app) as browser:
        missing_origin = browser.post(
            f"{settings.API_V1_STR}/login/browser-session",
            data=login_data,
        )
        assert missing_origin.status_code == 403
        assert BROWSER_SESSION_COOKIE not in browser.cookies

        wrong_origin = browser.post(
            f"{settings.API_V1_STR}/login/browser-session",
            data=login_data,
            headers={"Origin": "https://attacker.example"},
        )
        assert wrong_origin.status_code == 403
        assert BROWSER_SESSION_COOKIE not in browser.cookies

        login = browser.post(
            f"{settings.API_V1_STR}/login/browser-session",
            data=login_data,
            headers={"Origin": settings.FRONTEND_HOST},
        )
        assert login.status_code == 200
        assert login.json()["email"] == settings.FIRST_SUPERUSER
        assert "access_token" not in login.json()
        set_cookie = login.headers["set-cookie"]
        assert f"{BROWSER_SESSION_COOKIE}=" in set_cookie
        assert "HttpOnly" in set_cookie
        assert "SameSite=strict" in set_cookie
        assert "Path=/" in set_cookie

        current_user = browser.get(f"{settings.API_V1_STR}/users/me")
        assert current_user.status_code == 200
        assert current_user.json()["email"] == settings.FIRST_SUPERUSER

        csrf_attempt = browser.post(f"{settings.API_V1_STR}/login/test-token")
        assert csrf_attempt.status_code == 403
        assert csrf_attempt.json() == {"detail": "Cross-site request rejected"}

        permitted_mutation = browser.post(
            f"{settings.API_V1_STR}/login/test-token",
            headers={"Origin": settings.FRONTEND_HOST},
        )
        assert permitted_mutation.status_code == 200

        rejected_logout = browser.post(
            f"{settings.API_V1_STR}/login/logout",
            headers={"Origin": "https://attacker.example"},
        )
        assert rejected_logout.status_code == 403
        assert BROWSER_SESSION_COOKIE in browser.cookies

        logout = browser.post(
            f"{settings.API_V1_STR}/login/logout",
            headers={"Origin": settings.FRONTEND_HOST},
        )
        assert logout.status_code == 200
        assert logout.json() == {"message": "Logged out successfully"}
        assert BROWSER_SESSION_COOKIE not in browser.cookies
        assert browser.get(f"{settings.API_V1_STR}/users/me").status_code == 401


def test_bearer_auth_remains_origin_independent(
    client: TestClient,
    superuser_token_headers: dict[str, str],
) -> None:
    response = client.post(
        f"{settings.API_V1_STR}/login/test-token",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200


def test_dashboard_origin_can_preflight_authenticated_patch(client: TestClient) -> None:
    response = client.options(
        f"{settings.API_V1_STR}/users/me",
        headers={
            "Origin": settings.FRONTEND_HOST,
            "Access-Control-Request-Method": "PATCH",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == settings.FRONTEND_HOST
    assert response.headers["access-control-allow-credentials"] == "true"
    assert "PATCH" in response.headers["access-control-allow-methods"]


@pytest.mark.parametrize(
    "email",
    [settings.FIRST_SUPERUSER, "missing@example.com"],
)
def test_login_rejection_does_not_disclose_account_state(client: TestClient, email: str) -> None:
    response = client.post(
        f"{settings.API_V1_STR}/login/access-token",
        data={"username": email, "password": "incorrect"},
    )
    assert response.status_code == 401
    assert response.json() == {"detail": "Incorrect email or password"}
    assert response.headers["www-authenticate"] == "Bearer"


def test_use_access_token(client: TestClient, superuser_token_headers: dict[str, str]) -> None:
    response = client.post(
        f"{settings.API_V1_STR}/login/test-token",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200
    assert "email" in response.json()


def test_recovery_response_and_timing_do_not_disclose_user(client: TestClient) -> None:
    timings = []
    responses = []
    for email in (settings.EMAIL_TEST_USER, random_email()):
        started = perf_counter()
        response = client.post(f"{settings.API_V1_STR}/password-recovery/{email}")
        timings.append(perf_counter() - started)
        responses.append(response)

    assert all(response.status_code == 200 for response in responses)
    assert all(response.json() == RECOVERY_RESPONSE for response in responses)
    assert all(elapsed >= 0.20 for elapsed in timings)
    assert abs(timings[0] - timings[1]) < 0.10


def test_recovery_schedules_email_only_for_existing_active_user(
    client: TestClient,
    db: Session,
) -> None:
    email = random_email()
    crud.create_user(
        session=db,
        user_create=UserCreate(email=email, password=random_lower_string()),
    )
    with (
        patch("app.api.routes.login.send_email") as send_email_mock,
        patch.object(settings, "SMTP_HOST", "smtp.example.test"),
        patch.object(settings, "EMAILS_FROM_EMAIL", "noreply@example.test"),
    ):
        existing = client.post(f"{settings.API_V1_STR}/password-recovery/{email}")
        missing = client.post(f"{settings.API_V1_STR}/password-recovery/{random_email()}")

    assert existing.json() == missing.json() == RECOVERY_RESPONSE
    send_email_mock.assert_called_once()


def test_reset_password_is_one_time_and_revokes_existing_session(
    client: TestClient,
    db: Session,
) -> None:
    email = random_email()
    password = random_lower_string()
    user = crud.create_user(
        session=db,
        user_create=UserCreate(email=email, password=password),
    )
    old_headers = user_authentication_headers(client=client, email=email, password=password)
    user.password_reset_version += 1
    db.add(user)
    db.commit()
    db.refresh(user)
    token = generate_password_reset_token(
        user_id=user.id,
        reset_version=user.password_reset_version,
    )
    new_password = random_lower_string()

    response = client.post(
        f"{settings.API_V1_STR}/reset-password/",
        json={"new_password": new_password, "token": token},
    )

    assert response.status_code == 200
    db.refresh(user)
    assert verify_password(new_password, user.hashed_password)
    assert client.get(f"{settings.API_V1_STR}/users/me", headers=old_headers).status_code == 401
    replay = client.post(
        f"{settings.API_V1_STR}/reset-password/",
        json={"new_password": random_lower_string(), "token": token},
    )
    assert replay.status_code == 400
    assert replay.json() == {"detail": "Invalid or expired token"}


def test_concurrent_recovery_requests_leave_only_one_valid_link(
    client: TestClient,
    db: Session,
) -> None:
    email = random_email()
    password = random_lower_string()
    crud.create_user(session=db, user_create=UserCreate(email=email, password=password))
    issued_tokens: list[str] = []

    def capture_email(*, email_to: str, email: str, token: str) -> EmailData:
        del email_to, email
        issued_tokens.append(token)
        return EmailData(html_content="reset", subject="reset")

    with patch(
        "app.api.routes.login.generate_reset_password_email",
        side_effect=capture_email,
    ):
        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(
                executor.map(
                    lambda _: client.post(f"{settings.API_V1_STR}/password-recovery/{email}"),
                    range(2),
                )
            )

    assert all(response.status_code == 200 for response in responses)
    assert len(issued_tokens) == 2
    link_responses = [
        client.post(
            f"{settings.API_V1_STR}/reset-password/",
            json={"new_password": random_lower_string(), "token": token},
        )
        for token in issued_tokens
    ]
    assert sorted(response.status_code for response in link_responses) == [200, 400]


def test_concurrent_reset_replay_succeeds_once(client: TestClient, db: Session) -> None:
    email = random_email()
    user = crud.create_user(
        session=db,
        user_create=UserCreate(email=email, password=random_lower_string()),
    )
    user.password_reset_version += 1
    db.add(user)
    db.commit()
    db.refresh(user)
    token = generate_password_reset_token(
        user_id=user.id,
        reset_version=user.password_reset_version,
    )

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(
            executor.map(
                lambda _: client.post(
                    f"{settings.API_V1_STR}/reset-password/",
                    json={"new_password": random_lower_string(), "token": token},
                ),
                range(2),
            )
        )

    assert sorted(response.status_code for response in responses) == [200, 400]


def test_reset_password_invalid_token(client: TestClient) -> None:
    response = client.post(
        f"{settings.API_V1_STR}/reset-password/",
        json={"new_password": random_lower_string(), "token": "invalid"},
    )
    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid or expired token"}


def test_verify_email_is_one_time(client: TestClient, db: Session) -> None:
    email = random_email()
    user = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=email,
            password=random_lower_string(),
            is_active=False,
        ),
    )
    user.email_verification_version += 1
    db.add(user)
    db.commit()
    db.refresh(user)
    token = generate_email_verification_token(
        user_id=user.id,
        email=email,
        verification_version=user.email_verification_version,
    )

    response = client.post(
        f"{settings.API_V1_STR}/verify-email/",
        json={"token": token},
    )

    assert response.status_code == 200
    assert response.json() == {"message": "Account verified successfully"}
    db.refresh(user)
    assert user.is_active is True
    replay = client.post(
        f"{settings.API_V1_STR}/verify-email/",
        json={"token": token},
    )
    assert replay.status_code == 400


def test_verify_email_invalid_or_deleted_user_is_indistinguishable(
    client: TestClient,
    db: Session,
) -> None:
    deleted_user = crud.create_user(
        session=db,
        user_create=UserCreate(
            email=random_email(),
            password=random_lower_string(),
            is_active=False,
        ),
    )
    deleted_user.email_verification_version += 1
    db.add(deleted_user)
    db.commit()
    deleted_token = generate_email_verification_token(
        user_id=deleted_user.id,
        email=deleted_user.email,
        verification_version=deleted_user.email_verification_version,
    )
    db.delete(deleted_user)
    db.commit()
    missing_token = generate_email_verification_token(
        user_id=uuid.uuid4(),
        email="missing@example.com",
        verification_version=1,
    )
    for token in ("invalid", missing_token, deleted_token):
        response = client.post(
            f"{settings.API_V1_STR}/verify-email/",
            json={"token": token},
        )
        assert response.status_code == 400
        assert response.json() == {"detail": "Invalid or expired token"}
