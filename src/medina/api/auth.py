"""Authentication: JWT tokens, password hashing, user management."""
from __future__ import annotations

import logging
import secrets
import uuid
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from fastapi import HTTPException, Request
from pydantic import BaseModel

from medina.config import get_config
from medina.db.engine import get_conn

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Password hashing (bcrypt directly — passlib has compat issues with bcrypt 5)
# ---------------------------------------------------------------------------


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode(), hashed.encode())


# ---------------------------------------------------------------------------
# JWT helpers
# ---------------------------------------------------------------------------
_runtime_secret: str | None = None


def _get_secret() -> str:
    """Return the JWT secret, auto-generating one for dev if not configured."""
    global _runtime_secret
    cfg = get_config()
    if cfg.jwt_secret_key:
        return cfg.jwt_secret_key
    # Dev mode: generate a random secret (survives until server restart)
    if _runtime_secret is None:
        _runtime_secret = secrets.token_hex(32)
        logger.warning("No MEDINA_JWT_SECRET_KEY set — using random dev secret")
    return _runtime_secret


ALGORITHM = "HS256"
COOKIE_NAME = "access_token"


class TokenPayload(BaseModel):
    sub: str  # user_id
    tenant_id: str
    exp: float


def create_access_token(user: User) -> str:
    cfg = get_config()
    expire = datetime.now(timezone.utc) + timedelta(hours=cfg.jwt_expiry_hours)
    payload = {
        "sub": user.id,
        "tenant_id": user.tenant_id,
        "exp": expire,
    }
    return jwt.encode(payload, _get_secret(), algorithm=ALGORITHM)


def decode_access_token(token: str) -> TokenPayload:
    try:
        data = jwt.decode(token, _get_secret(), algorithms=[ALGORITHM])
        return TokenPayload(**data)
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


# ---------------------------------------------------------------------------
# User model
# ---------------------------------------------------------------------------
class User(BaseModel):
    id: str
    email: str
    name: str
    tenant_id: str
    tenant_name: str = ""
    created_at: str = ""


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------
def _load_user_by_id(user_id: str) -> User | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT u.id, u.email, u.name, u.tenant_id, t.name AS tenant_name, u.created_at "
        "FROM users u JOIN tenants t ON u.tenant_id = t.id WHERE u.id = ?",
        (user_id,),
    ).fetchone()
    if not row:
        return None
    return User(
        id=row["id"],
        email=row["email"],
        name=row["name"],
        tenant_id=row["tenant_id"],
        tenant_name=row["tenant_name"],
        created_at=row["created_at"],
    )


def _load_user_by_email(email: str) -> tuple[User, str] | None:
    """Return (User, hashed_password) or None."""
    conn = get_conn()
    row = conn.execute(
        "SELECT u.id, u.email, u.name, u.hashed_password, u.tenant_id, "
        "t.name AS tenant_name, u.created_at "
        "FROM users u JOIN tenants t ON u.tenant_id = t.id WHERE u.email = ?",
        (email.lower().strip(),),
    ).fetchone()
    if not row:
        return None
    user = User(
        id=row["id"],
        email=row["email"],
        name=row["name"],
        tenant_id=row["tenant_id"],
        tenant_name=row["tenant_name"],
        created_at=row["created_at"],
    )
    return user, row["hashed_password"]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def register_user(email: str, password: str, name: str, company_name: str) -> User:
    """Create a new tenant + user. Raises HTTPException on duplicate email."""
    email = email.lower().strip()
    conn = get_conn()

    existing = conn.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone()
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    tenant_id = uuid.uuid4().hex[:12]
    user_id = uuid.uuid4().hex[:12]
    hashed = hash_password(password)
    now = datetime.now(timezone.utc).isoformat()

    conn.execute(
        "INSERT INTO tenants (id, name, created_at) VALUES (?, ?, ?)",
        (tenant_id, company_name.strip(), now),
    )
    conn.execute(
        "INSERT INTO users (id, email, name, hashed_password, tenant_id, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, email, name.strip(), hashed, tenant_id, now),
    )
    conn.commit()

    return User(
        id=user_id,
        email=email,
        name=name.strip(),
        tenant_id=tenant_id,
        tenant_name=company_name.strip(),
        created_at=now,
    )


def authenticate_user(email: str, password: str) -> User | None:
    """Verify credentials. Returns User on success, None on failure."""
    result = _load_user_by_email(email)
    if result is None:
        return None
    user, hashed = result
    if not verify_password(password, hashed):
        return None
    return user


async def get_current_user(request: Request) -> User:
    """FastAPI dependency: extract JWT from cookie, decode, load user."""
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated")
    payload = decode_access_token(token)
    user = _load_user_by_id(payload.sub)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user
