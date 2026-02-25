"""Authentication API endpoints: register, login, logout, me."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, EmailStr

from medina.api.auth import (
    COOKIE_NAME,
    User,
    authenticate_user,
    create_access_token,
    create_reset_token,
    get_current_user,
    register_user,
    reset_password,
)
from medina.config import get_config

import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------
class RegisterRequest(BaseModel):
    email: str
    password: str
    name: str
    company_name: str


class LoginRequest(BaseModel):
    email: str
    password: str


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


class UserResponse(BaseModel):
    id: str
    email: str
    name: str
    tenant_id: str
    tenant_name: str


# ---------------------------------------------------------------------------
# Cookie helper
# ---------------------------------------------------------------------------
def _set_auth_cookie(response: Response, token: str) -> None:
    cfg = get_config()
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        httponly=True,
        samesite="lax",
        path="/",
        max_age=cfg.jwt_expiry_hours * 3600,
        # secure=True in production (behind HTTPS)
    )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@router.post("/register", response_model=UserResponse)
async def register(body: RegisterRequest, response: Response):
    """Create a new account + tenant. Sets JWT cookie on success."""
    user = register_user(body.email, body.password, body.name, body.company_name)
    token = create_access_token(user)
    _set_auth_cookie(response, token)
    return UserResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        tenant_id=user.tenant_id,
        tenant_name=user.tenant_name,
    )


@router.post("/login", response_model=UserResponse)
async def login(body: LoginRequest, response: Response):
    """Verify credentials and set JWT cookie."""
    from fastapi import HTTPException

    user = authenticate_user(body.email, body.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    token = create_access_token(user)
    _set_auth_cookie(response, token)
    return UserResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        tenant_id=user.tenant_id,
        tenant_name=user.tenant_name,
    )


@router.post("/logout")
async def logout(response: Response):
    """Clear the JWT cookie."""
    response.delete_cookie(key=COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me", response_model=UserResponse)
async def me(user: User = Depends(get_current_user)):
    """Return the current authenticated user."""
    return UserResponse(
        id=user.id,
        email=user.email,
        name=user.name,
        tenant_id=user.tenant_id,
        tenant_name=user.tenant_name,
    )


@router.post("/forgot-password")
async def forgot_password(body: ForgotPasswordRequest):
    """Request a password reset. Always returns success (no email enumeration)."""
    token = create_reset_token(body.email)
    if token:
        logger.info("Password reset token for %s: %s", body.email, token)
    return {
        "ok": True,
        "message": "If an account with that email exists, a reset link has been sent.",
    }


@router.post("/reset-password")
async def do_reset_password(body: ResetPasswordRequest):
    """Reset password using a valid token."""
    from fastapi import HTTPException

    if len(body.new_password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    success = reset_password(body.token, body.new_password)
    if not success:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")
    return {"ok": True, "message": "Password has been reset. You can now sign in."}
