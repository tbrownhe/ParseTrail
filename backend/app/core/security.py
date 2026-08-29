from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError
from pwdlib.hashers.argon2 import Argon2Hasher
from pwdlib.hashers.bcrypt import BcryptHasher

from app.core.config import settings

password_hash = PasswordHash((Argon2Hasher(), BcryptHasher()))


ALGORITHM = "HS256"


def create_access_token(
    subject: str | Any,
    expires_delta: timedelta,
    *,
    session_version: int,
) -> str:
    now = datetime.now(timezone.utc)
    expire = now + expires_delta
    to_encode = {
        "exp": expire,
        "iat": now,
        "sub": str(subject),
        "scope": "access",
        "session_version": session_version,
    }
    encoded_jwt = jwt.encode(to_encode, settings.SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return password_hash.verify(plain_password, hashed_password)
    except (UnknownHashError, ValueError):
        return False


def verify_and_update_password(
    plain_password: str,
    hashed_password: str,
) -> tuple[bool, str | None]:
    try:
        return password_hash.verify_and_update(plain_password, hashed_password)
    except (UnknownHashError, ValueError):
        return False, None


def get_password_hash(password: str) -> str:
    return password_hash.hash(password)
