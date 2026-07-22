from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlmodel import Session

from app import crud
from app.core.config import settings
from app.core.security import verify_password
from app.models import UserCreate
from app.tests.utils.utils import random_email, random_lower_string
from app.utils import (
    generate_email_verification_token,
    generate_password_reset_token,
)


def test_get_access_token(client: TestClient) -> None:
    login_data = {
        "username": settings.FIRST_SUPERUSER,
        "password": settings.FIRST_SUPERUSER_PASSWORD,
    }
    r = client.post(f"{settings.API_V1_STR}/login/access-token", data=login_data)
    tokens = r.json()
    assert r.status_code == 200
    assert "access_token" in tokens
    assert tokens["access_token"]


def test_get_access_token_incorrect_password(client: TestClient) -> None:
    login_data = {
        "username": settings.FIRST_SUPERUSER,
        "password": "incorrect",
    }
    r = client.post(f"{settings.API_V1_STR}/login/access-token", data=login_data)
    assert r.status_code == 400


def test_use_access_token(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    r = client.post(
        f"{settings.API_V1_STR}/login/test-token",
        headers=superuser_token_headers,
    )
    result = r.json()
    assert r.status_code == 200
    assert "email" in result


def test_recovery_password(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    with patch("app.api.routes.login.send_email") as send_email_mock:
        email = settings.EMAIL_TEST_USER
        r = client.post(
            f"{settings.API_V1_STR}/password-recovery/{email}",
            headers=normal_user_token_headers,
        )
        assert r.status_code == 200
        assert r.json() == {"message": "Password recovery email sent"}
        send_email_mock.assert_called_once()


def test_recovery_password_user_not_exits(
    client: TestClient, normal_user_token_headers: dict[str, str]
) -> None:
    email = "jVgQr@example.com"
    r = client.post(
        f"{settings.API_V1_STR}/password-recovery/{email}",
        headers=normal_user_token_headers,
    )
    assert r.status_code == 404


def test_reset_password(client: TestClient, db: Session) -> None:
    email = random_email()
    password = random_lower_string()
    user = crud.create_user(
        session=db,
        user_create=UserCreate(email=email, password=password),
    )
    token = generate_password_reset_token(email=email)
    data = {"new_password": "changethis", "token": token}
    r = client.post(
        f"{settings.API_V1_STR}/reset-password/",
        json=data,
    )
    assert r.status_code == 200
    assert r.json() == {"message": "Password updated successfully"}

    db.refresh(user)
    assert verify_password(data["new_password"], user.hashed_password)


def test_reset_password_invalid_token(
    client: TestClient, superuser_token_headers: dict[str, str]
) -> None:
    data = {"new_password": "changethis", "token": "invalid"}
    r = client.post(
        f"{settings.API_V1_STR}/reset-password/",
        headers=superuser_token_headers,
        json=data,
    )
    response = r.json()

    assert "detail" in response
    assert r.status_code == 400
    assert response["detail"] == "Invalid token"


def test_verify_email_success(client: TestClient, db: Session) -> None:
    email = random_email()
    password = random_lower_string()
    user_in = UserCreate(email=email, password=password, is_active=False)
    user = crud.create_user(session=db, user_create=user_in)

    token = generate_email_verification_token(email=email)
    response = client.post(
        f"{settings.API_V1_STR}/verify-email/",
        json={"token": token},
    )

    assert response.status_code == 200
    assert response.json() == {"message": "Account verified successfully"}
    db.refresh(user)
    assert user.is_active is True


def test_verify_email_invalid_token(client: TestClient) -> None:
    response = client.post(
        f"{settings.API_V1_STR}/verify-email/",
        json={"token": "invalid"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid token"


def test_verify_email_user_not_found(client: TestClient) -> None:
    token = generate_email_verification_token(email="missing@example.com")
    response = client.post(
        f"{settings.API_V1_STR}/verify-email/",
        json={"token": token},
    )
    assert response.status_code == 404
    assert (
        response.json()["detail"]
        == "The user with this email does not exist in the system."
    )
