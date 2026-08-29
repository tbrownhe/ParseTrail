import uuid
from typing import Any

from sqlalchemy import or_
from sqlmodel import Session, col, select

from app.core.security import get_password_hash, verify_and_update_password
from app.models import Item, ItemCreate, User, UserCreate, UserUpdate

# Make an unknown email perform the same expensive password-hash work as a known
# email. The value is process-local and deliberately cannot authenticate a user.
DUMMY_PASSWORD_HASH = get_password_hash("parsetrail-login-timing-placeholder")


def create_user(*, session: Session, user_create: UserCreate) -> User:
    db_obj = User.model_validate(user_create, update={"hashed_password": get_password_hash(user_create.password)})
    session.add(db_obj)
    session.commit()
    session.refresh(db_obj)
    return db_obj


def update_user(*, session: Session, db_user: User, user_in: UserUpdate) -> Any:
    user_data = user_in.model_dump(exclude_unset=True)
    user_data.pop("email", None)
    extra_data = {}
    security_changed = False
    if "password" in user_data:
        password = user_data.pop("password")
        hashed_password = get_password_hash(password)
        extra_data["hashed_password"] = hashed_password
        db_user.password_reset_version += 1
        security_changed = True
    for field in ("is_active", "is_superuser"):
        if field in user_data and user_data[field] != getattr(db_user, field):
            security_changed = True
    if security_changed:
        db_user.session_version += 1
    db_user.sqlmodel_update(user_data, update=extra_data)
    session.add(db_user)
    session.commit()
    session.refresh(db_user)
    return db_user


def get_user_by_email(*, session: Session, email: str, for_update: bool = False) -> User | None:
    statement = select(User).where(User.email == email)
    if for_update:
        statement = statement.with_for_update()
    session_user = session.exec(statement).first()
    return session_user


def email_is_claimed(
    *,
    session: Session,
    email: str,
    excluding_user_id: uuid.UUID | None = None,
) -> bool:
    statement = select(User.id).where(or_(col(User.email) == email, col(User.pending_email) == email))
    if excluding_user_id is not None:
        statement = statement.where(User.id != excluding_user_id)
    return session.exec(statement).first() is not None


def authenticate(*, session: Session, email: str, password: str) -> User | None:
    db_user = get_user_by_email(session=session, email=email)
    if not db_user:
        verify_and_update_password(password, DUMMY_PASSWORD_HASH)
        return None
    valid, updated_hash = verify_and_update_password(password, db_user.hashed_password)
    if not valid:
        return None
    if updated_hash is not None:
        db_user.hashed_password = updated_hash
        session.add(db_user)
        session.commit()
        session.refresh(db_user)
    return db_user


def create_item(*, session: Session, item_in: ItemCreate, owner_id: uuid.UUID) -> Item:
    db_item = Item.model_validate(item_in, update={"owner_id": owner_id})
    session.add(db_item)
    session.commit()
    session.refresh(db_item)
    return db_item
