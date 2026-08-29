import uuid
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from app import crud
from app.core.config import settings
from app.core.security import verify_password
from app.models import User, UserCreate
from app.tests.utils.user import user_authentication_headers
from app.tests.utils.utils import random_email, random_lower_string
from app.utils import generate_email_verification_token


def test_get_users_superuser_me(client: TestClient, superuser_token_headers: dict[str, str]) -> None:
    r = client.get(f"{settings.API_V1_STR}/users/me", headers=superuser_token_headers)
    current_user = r.json()
    assert current_user
    assert current_user["is_active"] is True
    assert current_user["is_superuser"]
    assert current_user["email"] == settings.FIRST_SUPERUSER


def test_get_users_normal_user_me(client: TestClient, normal_user_token_headers: dict[str, str]) -> None:
    r = client.get(f"{settings.API_V1_STR}/users/me", headers=normal_user_token_headers)
    current_user = r.json()
    assert current_user
    assert current_user["is_active"] is True
    assert current_user["is_superuser"] is False
    assert current_user["email"] == settings.EMAIL_TEST_USER


def test_create_user_new_email(client: TestClient, superuser_token_headers: dict[str, str], db: Session) -> None:
    with (
        patch("app.utils.send_email", return_value=None),
        patch("app.core.config.settings.SMTP_HOST", "smtp.example.com"),
        patch("app.core.config.settings.SMTP_USER", "admin@example.com"),
    ):
        username = random_email()
        password = random_lower_string()
        data = {"email": username, "password": password}
        r = client.post(
            f"{settings.API_V1_STR}/users/",
            headers=superuser_token_headers,
            json=data,
        )
        assert 200 <= r.status_code < 300
        created_user = r.json()
        user = crud.get_user_by_email(session=db, email=username)
        assert user
        assert user.email == created_user["email"]
        assert user.is_active is False


def test_get_existing_user(client: TestClient, superuser_token_headers: dict[str, str], db: Session) -> None:
    username = random_email()
    password = random_lower_string()
    user_in = UserCreate(email=username, password=password)
    user = crud.create_user(session=db, user_create=user_in)
    user_id = user.id
    r = client.get(
        f"{settings.API_V1_STR}/users/{user_id}",
        headers=superuser_token_headers,
    )
    assert 200 <= r.status_code < 300
    api_user = r.json()
    existing_user = crud.get_user_by_email(session=db, email=username)
    assert existing_user
    assert existing_user.email == api_user["email"]


def test_get_existing_user_current_user(client: TestClient, db: Session) -> None:
    username = random_email()
    password = random_lower_string()
    user_in = UserCreate(email=username, password=password)
    user = crud.create_user(session=db, user_create=user_in)
    user_id = user.id

    login_data = {
        "username": username,
        "password": password,
    }
    r = client.post(f"{settings.API_V1_STR}/login/access-token", data=login_data)
    tokens = r.json()
    a_token = tokens["access_token"]
    headers = {"Authorization": f"Bearer {a_token}"}

    r = client.get(
        f"{settings.API_V1_STR}/users/{user_id}",
        headers=headers,
    )
    assert 200 <= r.status_code < 300
    api_user = r.json()
    existing_user = crud.get_user_by_email(session=db, email=username)
    assert existing_user
    assert existing_user.email == api_user["email"]


def test_get_existing_user_permissions_error(client: TestClient, normal_user_token_headers: dict[str, str]) -> None:
    r = client.get(
        f"{settings.API_V1_STR}/users/{uuid.uuid4()}",
        headers=normal_user_token_headers,
    )
    assert r.status_code == 403
    assert r.json() == {"detail": "The user doesn't have enough privileges"}


def test_create_user_existing_username(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    username = random_email()
    # username = email
    password = random_lower_string()
    user_in = UserCreate(email=username, password=password)
    crud.create_user(session=db, user_create=user_in)
    data = {"email": username, "password": password}
    r = client.post(
        f"{settings.API_V1_STR}/users/",
        headers=superuser_token_headers,
        json=data,
    )
    created_user = r.json()
    assert r.status_code == 400
    assert "_id" not in created_user


def test_create_user_by_normal_user(client: TestClient, normal_user_token_headers: dict[str, str]) -> None:
    username = random_email()
    password = random_lower_string()
    data = {"email": username, "password": password}
    r = client.post(
        f"{settings.API_V1_STR}/users/",
        headers=normal_user_token_headers,
        json=data,
    )
    assert r.status_code == 403


def test_retrieve_users(client: TestClient, superuser_token_headers: dict[str, str], db: Session) -> None:
    username = random_email()
    password = random_lower_string()
    user_in = UserCreate(email=username, password=password)
    crud.create_user(session=db, user_create=user_in)

    username2 = random_email()
    password2 = random_lower_string()
    user_in2 = UserCreate(email=username2, password=password2)
    crud.create_user(session=db, user_create=user_in2)

    r = client.get(f"{settings.API_V1_STR}/users/", headers=superuser_token_headers)
    all_users = r.json()

    assert len(all_users["data"]) > 1
    assert "count" in all_users
    for item in all_users["data"]:
        assert "email" in item


def test_update_user_me_requires_email_verification(
    client: TestClient,
    db: Session,
) -> None:
    original_email = random_email()
    password = random_lower_string()
    user = crud.create_user(
        session=db,
        user_create=UserCreate(email=original_email, password=password),
    )
    headers = user_authentication_headers(
        client=client,
        email=original_email,
        password=password,
    )
    full_name = "Updated Name"
    new_email = random_email()
    with (
        patch("app.api.routes.users.send_email") as send_email_mock,
        patch.object(settings, "SMTP_HOST", "smtp.example.test"),
        patch.object(settings, "EMAILS_FROM_EMAIL", "noreply@example.test"),
    ):
        r = client.patch(
            f"{settings.API_V1_STR}/users/me",
            headers=headers,
            json={"full_name": full_name, "email": new_email},
        )
    assert r.status_code == 200
    updated_user = r.json()
    assert updated_user["email"] == original_email
    assert updated_user["pending_email"] == new_email
    assert updated_user["full_name"] == full_name
    send_email_mock.assert_called_once()

    db.refresh(user)
    assert user.email == original_email
    assert user.pending_email == new_email
    token = generate_email_verification_token(
        user_id=user.id,
        email=new_email,
        verification_version=user.email_verification_version,
    )
    verified = client.post(
        f"{settings.API_V1_STR}/verify-email/",
        json={"token": token},
    )

    assert verified.status_code == 200
    db.refresh(user)
    assert user.email == new_email
    assert user.pending_email is None
    assert user.full_name == full_name
    assert client.get(f"{settings.API_V1_STR}/users/me", headers=headers).status_code == 401
    assert user_authentication_headers(
        client=client,
        email=new_email,
        password=password,
    )


def test_update_password_me_revokes_existing_session(
    client: TestClient,
    db: Session,
) -> None:
    email = random_email()
    old_password = random_lower_string()
    user = crud.create_user(
        session=db,
        user_create=UserCreate(email=email, password=old_password),
    )
    old_headers = user_authentication_headers(
        client=client,
        email=email,
        password=old_password,
    )
    new_password = random_lower_string()
    data = {
        "current_password": old_password,
        "new_password": new_password,
    }
    r = client.patch(
        f"{settings.API_V1_STR}/users/me/password",
        headers=old_headers,
        json=data,
    )
    assert r.status_code == 200
    updated_user = r.json()
    assert updated_user["message"] == "Password updated successfully"

    db.refresh(user)
    assert verify_password(new_password, user.hashed_password)
    assert client.get(f"{settings.API_V1_STR}/users/me", headers=old_headers).status_code == 401

    new_headers = user_authentication_headers(
        client=client,
        email=email,
        password=new_password,
    )
    revert_data = {
        "current_password": new_password,
        "new_password": old_password,
    }
    r = client.patch(
        f"{settings.API_V1_STR}/users/me/password",
        headers=new_headers,
        json=revert_data,
    )
    db.refresh(user)

    assert r.status_code == 200
    assert verify_password(old_password, user.hashed_password)
    assert client.get(f"{settings.API_V1_STR}/users/me", headers=new_headers).status_code == 401


def test_update_password_me_incorrect_password(client: TestClient, superuser_token_headers: dict[str, str]) -> None:
    new_password = random_lower_string()
    data = {"current_password": new_password, "new_password": new_password}
    r = client.patch(
        f"{settings.API_V1_STR}/users/me/password",
        headers=superuser_token_headers,
        json=data,
    )
    assert r.status_code == 400
    updated_user = r.json()
    assert updated_user["detail"] == "Incorrect password"


def test_update_user_me_email_exists(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    username = random_email()
    password = random_lower_string()
    user_in = UserCreate(email=username, password=password)
    user = crud.create_user(session=db, user_create=user_in)

    data = {"email": user.email}
    r = client.patch(
        f"{settings.API_V1_STR}/users/me",
        headers=normal_user_token_headers,
        json=data,
    )
    assert r.status_code == 409
    assert r.json()["detail"] == "Email address is already in use"


def test_update_password_me_same_password_error(client: TestClient, superuser_token_headers: dict[str, str]) -> None:
    data = {
        "current_password": settings.FIRST_SUPERUSER_PASSWORD,
        "new_password": settings.FIRST_SUPERUSER_PASSWORD,
    }
    r = client.patch(
        f"{settings.API_V1_STR}/users/me/password",
        headers=superuser_token_headers,
        json=data,
    )
    assert r.status_code == 400
    updated_user = r.json()
    assert updated_user["detail"] == "New password cannot be the same as the current one"


def test_register_user(client: TestClient, db: Session) -> None:
    username = random_email()
    password = random_lower_string()
    full_name = random_lower_string()
    data = {"email": username, "password": password, "full_name": full_name}
    r = client.post(
        f"{settings.API_V1_STR}/users/signup",
        json=data,
    )
    assert r.status_code == 200
    created_user = r.json()
    assert created_user["email"] == username
    assert created_user["full_name"] == full_name

    user_query = select(User).where(User.email == username)
    user_db = db.exec(user_query).first()
    assert user_db
    assert user_db.email == username
    assert user_db.full_name == full_name
    assert user_db.is_active is False
    assert verify_password(password, user_db.hashed_password)


def test_register_user_already_exists_error(client: TestClient) -> None:
    password = random_lower_string()
    full_name = random_lower_string()
    data = {
        "email": settings.FIRST_SUPERUSER,
        "password": password,
        "full_name": full_name,
    }
    r = client.post(
        f"{settings.API_V1_STR}/users/signup",
        json=data,
    )
    assert r.status_code == 400
    assert r.json()["detail"] == "The user with this email already exists in the system"


def test_register_user_rejects_another_users_pending_email(
    client: TestClient,
    db: Session,
) -> None:
    pending_email = random_email()
    user = crud.create_user(
        session=db,
        user_create=UserCreate(email=random_email(), password=random_lower_string()),
    )
    user.pending_email = pending_email
    db.add(user)
    db.commit()

    response = client.post(
        f"{settings.API_V1_STR}/users/signup",
        json={"email": pending_email, "password": random_lower_string()},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "The user with this email already exists in the system"


def test_update_user(client: TestClient, superuser_token_headers: dict[str, str], db: Session) -> None:
    username = random_email()
    password = random_lower_string()
    user_in = UserCreate(email=username, password=password)
    user = crud.create_user(session=db, user_create=user_in)

    data = {"full_name": "Updated_full_name"}
    r = client.patch(
        f"{settings.API_V1_STR}/users/{user.id}",
        headers=superuser_token_headers,
        json=data,
    )
    assert r.status_code == 200
    updated_user = r.json()

    assert updated_user["full_name"] == "Updated_full_name"

    user_query = select(User).where(User.email == username)
    user_db = db.exec(user_query).first()
    db.refresh(user_db)
    assert user_db
    assert user_db.full_name == "Updated_full_name"


def test_update_user_not_exists(client: TestClient, superuser_token_headers: dict[str, str]) -> None:
    data = {"full_name": "Updated_full_name"}
    r = client.patch(
        f"{settings.API_V1_STR}/users/{uuid.uuid4()}",
        headers=superuser_token_headers,
        json=data,
    )
    assert r.status_code == 404
    assert r.json()["detail"] == "The user with this id does not exist in the system"


def test_update_user_email_exists(client: TestClient, superuser_token_headers: dict[str, str], db: Session) -> None:
    username = random_email()
    password = random_lower_string()
    user_in = UserCreate(email=username, password=password)
    user = crud.create_user(session=db, user_create=user_in)

    username2 = random_email()
    password2 = random_lower_string()
    user_in2 = UserCreate(email=username2, password=password2)
    user2 = crud.create_user(session=db, user_create=user_in2)

    data = {"email": user2.email}
    r = client.patch(
        f"{settings.API_V1_STR}/users/{user.id}",
        headers=superuser_token_headers,
        json=data,
    )
    assert r.status_code == 409
    assert r.json()["detail"] == "Email address is already in use"


def test_privilege_change_revokes_existing_session(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    email = random_email()
    password = random_lower_string()
    user = crud.create_user(
        session=db,
        user_create=UserCreate(email=email, password=password),
    )
    old_headers = user_authentication_headers(
        client=client,
        email=email,
        password=password,
    )

    response = client.patch(
        f"{settings.API_V1_STR}/users/{user.id}",
        headers=superuser_token_headers,
        json={"is_superuser": True},
    )

    assert response.status_code == 200
    assert client.get(f"{settings.API_V1_STR}/users/me", headers=old_headers).status_code == 401
    new_headers = user_authentication_headers(
        client=client,
        email=email,
        password=password,
    )
    assert client.get(f"{settings.API_V1_STR}/users/", headers=new_headers).status_code == 200


def test_deactivation_revokes_session_and_uses_generic_login_rejection(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
) -> None:
    email = random_email()
    password = random_lower_string()
    user = crud.create_user(
        session=db,
        user_create=UserCreate(email=email, password=password),
    )
    headers = user_authentication_headers(client=client, email=email, password=password)

    response = client.patch(
        f"{settings.API_V1_STR}/users/{user.id}",
        headers=superuser_token_headers,
        json={"is_active": False},
    )

    assert response.status_code == 200
    assert client.get(f"{settings.API_V1_STR}/users/me", headers=headers).status_code == 401
    login = client.post(
        f"{settings.API_V1_STR}/login/access-token",
        data={"username": email, "password": password},
    )
    assert login.status_code == 401
    assert login.json() == {"detail": "Incorrect email or password"}


def test_delete_user_me(client: TestClient, db: Session) -> None:
    username = random_email()
    password = random_lower_string()
    user_in = UserCreate(email=username, password=password)
    user = crud.create_user(session=db, user_create=user_in)
    user_id = user.id

    login_data = {
        "username": username,
        "password": password,
    }
    r = client.post(f"{settings.API_V1_STR}/login/access-token", data=login_data)
    tokens = r.json()
    a_token = tokens["access_token"]
    headers = {"Authorization": f"Bearer {a_token}"}

    r = client.delete(
        f"{settings.API_V1_STR}/users/me",
        headers=headers,
    )
    assert r.status_code == 200
    deleted_user = r.json()
    assert deleted_user["message"] == "User deleted successfully"
    result = db.exec(select(User).where(User.id == user_id)).first()
    assert result is None

    user_query = select(User).where(User.id == user_id)
    user_db = db.execute(user_query).first()
    assert user_db is None
    assert client.get(f"{settings.API_V1_STR}/users/me", headers=headers).status_code == 401


def test_delete_user_me_as_superuser(client: TestClient, superuser_token_headers: dict[str, str]) -> None:
    r = client.delete(
        f"{settings.API_V1_STR}/users/me",
        headers=superuser_token_headers,
    )
    assert r.status_code == 403
    response = r.json()
    assert response["detail"] == "Super users are not allowed to delete themselves"


def test_delete_user_super_user(client: TestClient, superuser_token_headers: dict[str, str], db: Session) -> None:
    username = random_email()
    password = random_lower_string()
    user_in = UserCreate(email=username, password=password)
    user = crud.create_user(session=db, user_create=user_in)
    user_id = user.id
    r = client.delete(
        f"{settings.API_V1_STR}/users/{user_id}",
        headers=superuser_token_headers,
    )
    assert r.status_code == 200
    deleted_user = r.json()
    assert deleted_user["message"] == "User deleted successfully"
    result = db.exec(select(User).where(User.id == user_id)).first()
    assert result is None


def test_delete_user_not_found(client: TestClient, superuser_token_headers: dict[str, str]) -> None:
    r = client.delete(
        f"{settings.API_V1_STR}/users/{uuid.uuid4()}",
        headers=superuser_token_headers,
    )
    assert r.status_code == 404
    assert r.json()["detail"] == "User not found"


def test_delete_user_current_super_user_error(
    client: TestClient, superuser_token_headers: dict[str, str], db: Session
) -> None:
    super_user = crud.get_user_by_email(session=db, email=settings.FIRST_SUPERUSER)
    assert super_user
    user_id = super_user.id

    r = client.delete(
        f"{settings.API_V1_STR}/users/{user_id}",
        headers=superuser_token_headers,
    )
    assert r.status_code == 403
    assert r.json()["detail"] == "Super users are not allowed to delete themselves"


def test_delete_user_without_privileges(
    client: TestClient, normal_user_token_headers: dict[str, str], db: Session
) -> None:
    username = random_email()
    password = random_lower_string()
    user_in = UserCreate(email=username, password=password)
    user = crud.create_user(session=db, user_create=user_in)

    r = client.delete(
        f"{settings.API_V1_STR}/users/{user.id}",
        headers=normal_user_token_headers,
    )
    assert r.status_code == 403
    assert r.json()["detail"] == "The user doesn't have enough privileges"
