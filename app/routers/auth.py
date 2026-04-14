"""
app/routers/auth.py — Authentication endpoints (register, login, logout, me).

Endpoints:
    POST /auth/register — Create a new user account (username + password).
    POST /auth/login    — Authenticate and receive a JWT access token.
    POST /auth/logout   — Invalidate the current token (blacklist it).
    GET  /auth/me       — Return the current user's profile (requires auth).

Security model:
- Passwords are hashed with bcrypt before storage.
- Login returns a short-lived JWT (default 30 min).
- Logout adds the token to an in-memory blacklist.
- Protected endpoints use the `get_current_user` dependency.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User
from ..schemas import UserRegister, UserLogin, TokenResponse, UserRead
from ..auth import (
    hash_password,
    verify_password,
    create_access_token,
    blacklist_token,
    get_current_user,
    oauth2_scheme,
)

router = APIRouter(prefix="/auth", tags=["Authentication"])


# ---------------------------------------------------------------------------
# POST /auth/register
# ---------------------------------------------------------------------------

@router.post(
    "/register",
    response_model=UserRead,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new user",
    responses={409: {"description": "Username already taken"}},
)
def register(payload: UserRegister, db: Session = Depends(get_db)):
    """
    Create a new user account.

    - **username**: 3–50 characters, must be unique.
    - **password**: 6–100 characters, stored as a bcrypt hash.

    Returns the created user (without the password hash).
    """
    # Check for duplicate username
    existing = db.query(User).filter(User.username == payload.username).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Username '{payload.username}' is already taken",
        )

    user = User(
        username=payload.username,
        hashed_password=hash_password(payload.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# ---------------------------------------------------------------------------
# POST /auth/login
# ---------------------------------------------------------------------------

@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Login and get a JWT token",
    responses={401: {"description": "Invalid credentials"}},
)
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """
    Authenticate with username and password.

    Returns a Bearer JWT token valid for 30 minutes (configurable via
    the `TOKEN_EXPIRE_MINUTES` environment variable).

    Use the token in the `Authorization: Bearer <token>` header for
    protected endpoints.
    """
    user = db.query(User).filter(User.username == form_data.username).first()

    if not user or not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(data={"sub": user.username})
    return TokenResponse(
        access_token=access_token,
        token_type="bearer",
        username=user.username,
    )


# ---------------------------------------------------------------------------
# POST /auth/logout
# ---------------------------------------------------------------------------

@router.post(
    "/logout",
    status_code=status.HTTP_200_OK,
    summary="Logout (invalidate token)",
)
def logout(
    token: str = Depends(oauth2_scheme),
    _current_user: User = Depends(get_current_user),
):
    """
    Invalidate the current JWT token by adding it to the blacklist.

    After logout, the same token cannot be used for authenticated requests.
    A new token must be obtained via `/auth/login`.
    """
    blacklist_token(token)
    return {"detail": "Successfully logged out"}


# ---------------------------------------------------------------------------
# GET /auth/me
# ---------------------------------------------------------------------------

@router.get(
    "/me",
    response_model=UserRead,
    summary="Get current user profile",
)
def get_me(current_user: User = Depends(get_current_user)):
    """
    Return the profile of the currently authenticated user.

    Requires a valid Bearer token in the Authorization header.
    """
    return current_user
