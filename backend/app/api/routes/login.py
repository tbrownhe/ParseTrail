import uuid
from datetime import timedelta
from time import monotonic, sleep
from typing import Annotated, Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel import select

from app import crud
from app.api.deps import CurrentUser, SessionDep, get_current_active_superuser
from app.core import security
from app.core.browser_session import (
    clear_browser_session_cookie,
    require_frontend_origin,
    set_browser_session_cookie,
)
from app.core.config import settings
from app.core.security import get_password_hash
from app.models import Message, NewPassword, Token, User, UserPublic, VerificationToken
from app.utils import (
    generate_password_reset_token,
    generate_reset_password_email,
    send_email,
    verify_email_verification_token,
    verify_password_reset_token,
)

router = APIRouter()
PASSWORD_RECOVERY_MIN_RESPONSE_SECONDS = 0.25


def _authenticate_user(session: SessionDep, form_data: OAuth2PasswordRequestForm) -> User:
    user = crud.authenticate(session=session, email=form_data.username, password=form_data.password)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=401,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def _create_user_access_token(user: User) -> str:
    return security.create_access_token(
        user.id,
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        session_version=user.session_version,
    )


@router.post("/login/access-token")
def login_access_token(session: SessionDep, form_data: Annotated[OAuth2PasswordRequestForm, Depends()]) -> Token:
    """
    OAuth2 compatible token login, get an access token for future requests
    """
    user = _authenticate_user(session, form_data)
    return Token(access_token=_create_user_access_token(user))


@router.post("/login/browser-session", response_model=UserPublic)
def login_browser_session(
    request: Request,
    response: Response,
    session: SessionDep,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> User:
    """Authenticate the dashboard without exposing its JWT to JavaScript."""
    require_frontend_origin(request)
    user = _authenticate_user(session, form_data)
    set_browser_session_cookie(response, _create_user_access_token(user))
    return user


@router.post("/login/logout", response_model=Message)
def logout_browser_session(request: Request, response: Response) -> Message:
    """Clear the dashboard cookie even if its token is already invalid."""
    require_frontend_origin(request)
    clear_browser_session_cookie(response)
    return Message(message="Logged out successfully")


@router.post("/login/test-token", response_model=UserPublic)
def test_token(current_user: CurrentUser) -> Any:
    """
    Test access token
    """
    return current_user


@router.post("/password-recovery/{email}")
def recover_password(
    email: str,
    session: SessionDep,
    background_tasks: BackgroundTasks,
) -> Message:
    """
    Password Recovery
    """
    started_at = monotonic()
    user = crud.get_user_by_email(session=session, email=email, for_update=True)
    eligible_user = user if user is not None and user.is_active else None
    if eligible_user is not None:
        eligible_user.password_reset_version += 1
        session.add(eligible_user)
        session.commit()
        session.refresh(eligible_user)
        user_id = eligible_user.id
        reset_version = eligible_user.password_reset_version
    else:
        user_id = uuid.uuid4()
        reset_version = 0

    password_reset_token = generate_password_reset_token(
        user_id=user_id,
        reset_version=reset_version,
    )
    email_data = generate_reset_password_email(
        email_to=email,
        email=email,
        token=password_reset_token,
    )
    if eligible_user is not None and settings.emails_enabled:
        background_tasks.add_task(
            send_email,
            email_to=eligible_user.email,
            subject=email_data.subject,
            html_content=email_data.html_content,
        )
    remaining = PASSWORD_RECOVERY_MIN_RESPONSE_SECONDS - (monotonic() - started_at)
    if remaining > 0:
        sleep(remaining)
    return Message(message="If the account exists, a password recovery email has been sent")


@router.post("/reset-password/")
def reset_password(session: SessionDep, body: NewPassword) -> Message:
    """
    Reset password
    """
    claims = verify_password_reset_token(token=body.token)
    if claims is None:
        raise HTTPException(status_code=400, detail="Invalid or expired token")
    user = session.exec(select(User).where(User.id == claims.user_id).with_for_update()).one_or_none()
    if user is None or not user.is_active or user.password_reset_version != claims.version:
        raise HTTPException(status_code=400, detail="Invalid or expired token")
    hashed_password = get_password_hash(password=body.new_password)
    user.hashed_password = hashed_password
    user.password_reset_version += 1
    user.session_version += 1
    session.add(user)
    session.commit()
    return Message(message="Password updated successfully")


@router.post(
    "/password-recovery-html-content/{email}",
    dependencies=[Depends(get_current_active_superuser)],
    response_class=HTMLResponse,
)
def recover_password_html_content(email: str, session: SessionDep) -> Any:
    """
    HTML Content for Password Recovery
    """
    user = crud.get_user_by_email(session=session, email=email, for_update=True)

    if not user:
        raise HTTPException(
            status_code=404,
            detail="The user with this username does not exist in the system.",
        )
    user.password_reset_version += 1
    session.add(user)
    session.commit()
    session.refresh(user)
    password_reset_token = generate_password_reset_token(
        user_id=user.id,
        reset_version=user.password_reset_version,
    )
    email_data = generate_reset_password_email(email_to=user.email, email=email, token=password_reset_token)

    return HTMLResponse(content=email_data.html_content, headers={"subject:": email_data.subject})


@router.post("/verify-email/")
def verify_email(session: SessionDep, body: VerificationToken) -> Message:
    """
    Verify user email from a token.
    """
    claims = verify_email_verification_token(token=body.token)
    if claims is None:
        raise HTTPException(status_code=400, detail="Invalid or expired token")

    user = session.exec(select(User).where(User.id == claims.user_id).with_for_update()).one_or_none()
    if user is None or user.email_verification_version != claims.version:
        raise HTTPException(status_code=400, detail="Invalid or expired token")

    if user.pending_email is not None:
        if user.pending_email != claims.email:
            raise HTTPException(status_code=400, detail="Invalid or expired token")
        if crud.email_is_claimed(
            session=session,
            email=claims.email,
            excluding_user_id=user.id,
        ):
            raise HTTPException(status_code=409, detail="Email address is no longer available")
        user.email = claims.email
        user.pending_email = None
        message = "Email address verified successfully"
    elif not user.is_active and user.email == claims.email:
        user.is_active = True
        message = "Account verified successfully"
    else:
        raise HTTPException(status_code=400, detail="Invalid or expired token")

    user.email_verification_version += 1
    user.session_version += 1
    session.add(user)
    session.commit()
    return Message(message=message)
