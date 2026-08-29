import uuid
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlmodel import col, delete, func, select

from app import crud
from app.api.deps import CurrentUser, SessionDep, get_current_active_superuser
from app.core.config import settings
from app.core.security import get_password_hash, verify_password
from app.models import (
    Item,
    Message,
    UpdatePassword,
    User,
    UserCreate,
    UserPublic,
    UserRegister,
    UsersPublic,
    UserUpdate,
    UserUpdateMe,
)
from app.utils import (
    generate_email_verification_token,
    generate_new_account_email,
    send_email,
)

router = APIRouter()


def _queue_verification_email(
    *,
    background_tasks: BackgroundTasks,
    user: User,
    target_email: str,
) -> None:
    if not settings.emails_enabled:
        return
    verification_token = generate_email_verification_token(
        user_id=user.id,
        email=target_email,
        verification_version=user.email_verification_version,
    )
    email_data = generate_new_account_email(
        email_to=target_email,
        username=target_email,
        token=verification_token,
    )
    background_tasks.add_task(
        send_email,
        email_to=target_email,
        subject=email_data.subject,
        html_content=email_data.html_content,
    )


def _request_email_change(
    *,
    session: SessionDep,
    background_tasks: BackgroundTasks,
    user: User,
    target_email: str,
) -> None:
    if target_email == user.email:
        if user.pending_email is not None:
            user.pending_email = None
            user.email_verification_version += 1
            session.add(user)
            session.commit()
            session.refresh(user)
        return
    if crud.email_is_claimed(
        session=session,
        email=target_email,
        excluding_user_id=user.id,
    ):
        raise HTTPException(status_code=409, detail="Email address is already in use")
    if not settings.emails_enabled:
        raise HTTPException(status_code=503, detail="Email changes are temporarily unavailable")
    user.pending_email = target_email
    user.email_verification_version += 1
    session.add(user)
    session.commit()
    session.refresh(user)
    _queue_verification_email(
        background_tasks=background_tasks,
        user=user,
        target_email=target_email,
    )


@router.get(
    "/",
    dependencies=[Depends(get_current_active_superuser)],
    response_model=UsersPublic,
)
def read_users(session: SessionDep, skip: int = 0, limit: int = 100) -> Any:
    """
    Retrieve users.
    """

    count_statement = select(func.count()).select_from(User)
    count = session.exec(count_statement).one()

    statement = select(User).offset(skip).limit(limit)
    users = session.exec(statement).all()

    return UsersPublic(data=users, count=count)


@router.post("/", dependencies=[Depends(get_current_active_superuser)], response_model=UserPublic)
def create_user(
    *,
    session: SessionDep,
    user_in: UserCreate,
    background_tasks: BackgroundTasks,
) -> Any:
    """
    Create new user.
    """
    if crud.email_is_claimed(session=session, email=str(user_in.email)):
        raise HTTPException(
            status_code=400,
            detail="The user with this email already exists in the system.",
        )

    user_in.is_active = False
    user = crud.create_user(session=session, user_create=user_in)
    user.email_verification_version += 1
    session.add(user)
    session.commit()
    session.refresh(user)
    _queue_verification_email(
        background_tasks=background_tasks,
        user=user,
        target_email=user.email,
    )
    return user


@router.patch("/me", response_model=UserPublic)
def update_user_me(
    *,
    session: SessionDep,
    user_in: UserUpdateMe,
    current_user: CurrentUser,
    background_tasks: BackgroundTasks,
) -> Any:
    """
    Update own user.
    """

    user_data = user_in.model_dump(exclude_unset=True)
    requested_email = user_data.pop("email", None)
    if requested_email is not None:
        _request_email_change(
            session=session,
            background_tasks=background_tasks,
            user=current_user,
            target_email=str(requested_email),
        )
    current_user.sqlmodel_update(user_data)
    session.add(current_user)
    session.commit()
    session.refresh(current_user)
    return current_user


@router.patch("/me/password", response_model=Message)
def update_password_me(*, session: SessionDep, body: UpdatePassword, current_user: CurrentUser) -> Any:
    """
    Update own password.
    """
    if not verify_password(body.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Incorrect password")
    if body.current_password == body.new_password:
        raise HTTPException(status_code=400, detail="New password cannot be the same as the current one")
    hashed_password = get_password_hash(body.new_password)
    current_user.hashed_password = hashed_password
    current_user.password_reset_version += 1
    current_user.session_version += 1
    session.add(current_user)
    session.commit()
    return Message(message="Password updated successfully")


@router.get("/me", response_model=UserPublic)
def read_user_me(current_user: CurrentUser) -> Any:
    """
    Get current user.
    """
    return current_user


@router.delete("/me", response_model=Message)
def delete_user_me(session: SessionDep, current_user: CurrentUser) -> Any:
    """
    Delete own user.
    """
    if current_user.is_superuser:
        raise HTTPException(status_code=403, detail="Super users are not allowed to delete themselves")
    statement = delete(Item).where(col(Item.owner_id) == current_user.id)
    session.exec(statement)
    session.delete(current_user)
    session.commit()
    return Message(message="User deleted successfully")


@router.post("/signup", response_model=UserPublic)
def register_user(
    session: SessionDep,
    user_in: UserRegister,
    background_tasks: BackgroundTasks,
) -> Any:
    """
    Create new user without the need to be logged in.
    """
    if crud.email_is_claimed(session=session, email=str(user_in.email)):
        raise HTTPException(
            status_code=400,
            detail="The user with this email already exists in the system",
        )
    user_create = UserCreate.model_validate(user_in, update={"is_active": False})
    user = crud.create_user(session=session, user_create=user_create)
    user.email_verification_version += 1
    session.add(user)
    session.commit()
    session.refresh(user)
    _queue_verification_email(
        background_tasks=background_tasks,
        user=user,
        target_email=user.email,
    )
    return user


@router.get("/{user_id}", response_model=UserPublic)
def read_user_by_id(user_id: uuid.UUID, session: SessionDep, current_user: CurrentUser) -> Any:
    """
    Get a specific user by id.
    """
    user = session.get(User, user_id)
    if user == current_user:
        return user
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=403,
            detail="The user doesn't have enough privileges",
        )
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.patch(
    "/{user_id}",
    dependencies=[Depends(get_current_active_superuser)],
    response_model=UserPublic,
)
def update_user(
    *,
    session: SessionDep,
    user_id: uuid.UUID,
    user_in: UserUpdate,
    background_tasks: BackgroundTasks,
) -> Any:
    """
    Update a user.
    """

    db_user = session.get(User, user_id)
    if not db_user:
        raise HTTPException(
            status_code=404,
            detail="The user with this id does not exist in the system",
        )
    if user_in.email is not None:
        _request_email_change(
            session=session,
            background_tasks=background_tasks,
            user=db_user,
            target_email=str(user_in.email),
        )

    db_user = crud.update_user(session=session, db_user=db_user, user_in=user_in)
    return db_user


@router.delete("/{user_id}", dependencies=[Depends(get_current_active_superuser)])
def delete_user(session: SessionDep, current_user: CurrentUser, user_id: uuid.UUID) -> Message:
    """
    Delete a user.
    """
    user = session.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user == current_user:
        raise HTTPException(status_code=403, detail="Super users are not allowed to delete themselves")
    statement = delete(Item).where(col(Item.owner_id) == user_id)
    session.exec(statement)
    session.delete(user)
    session.commit()
    return Message(message="User deleted successfully")
