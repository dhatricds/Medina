"""FastAPI application entry point."""
from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from medina.api.auth import COOKIE_NAME, decode_access_token, _load_user_by_id
from medina.api.routes import (
    auth,
    chat,
    corrections,
    dashboard,
    demo,
    export,
    feedback,
    fix_it,
    pages,
    params,
    positions,
    processing,
    results,
    sources,
    upload,
)
from medina.api.seed import seed_dashboard

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Medina API",
    description="Lighting Fixture Inventory Extraction API",
    version="0.1.0",
)

# ---------------------------------------------------------------------------
# Auth middleware — check JWT on all /api/ routes except public ones
# ---------------------------------------------------------------------------
# Paths under /api/ that do NOT require authentication
_PUBLIC_API_PATHS = {
    "/api/auth/login",
    "/api/auth/register",
    "/api/auth/forgot-password",
    "/api/auth/reset-password",
}
_PUBLIC_API_PREFIXES = (
    "/api/demo/",
)


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Skip auth for non-API routes, public endpoints, and OPTIONS (CORS preflight)
        if (
            request.method == "OPTIONS"
            or not path.startswith("/api/")
            or path in _PUBLIC_API_PATHS
            or any(path.startswith(p) for p in _PUBLIC_API_PREFIXES)
        ):
            return await call_next(request)

        token = request.cookies.get(COOKIE_NAME)
        if not token:
            return Response(content='{"detail":"Not authenticated"}', status_code=401,
                            media_type="application/json")
        try:
            payload = decode_access_token(token)
            user = _load_user_by_id(payload.sub)
            if not user:
                return Response(content='{"detail":"User not found"}', status_code=401,
                                media_type="application/json")
            # Stash user + tenant_id on request state for downstream routes
            request.state.user = user
            request.state.tenant_id = user.tenant_id
        except Exception:
            return Response(content='{"detail":"Invalid token"}', status_code=401,
                            media_type="application/json")

        return await call_next(request)


# CORS for frontend dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Auth middleware (added after CORS so CORS headers are always set)
app.add_middleware(AuthMiddleware)

# Register routers
app.include_router(auth.router)
app.include_router(sources.router)
app.include_router(upload.router)
app.include_router(processing.router)
app.include_router(results.router)
app.include_router(pages.router)
app.include_router(export.router)
app.include_router(corrections.router)
app.include_router(positions.router)
app.include_router(demo.router)
app.include_router(dashboard.router)
app.include_router(feedback.router)
app.include_router(fix_it.router)
app.include_router(chat.router)
app.include_router(params.router)


@app.on_event("startup")
async def startup_event():
    # Initialize database
    from medina.config import get_config
    from medina.db.engine import init_db
    from medina.db.migration import needs_migration, run_migration

    config = get_config()
    project_root = Path(__file__).resolve().parents[2]
    db_path = project_root / config.db_path
    init_db(db_path)

    # Run one-time migration from JSON files if needed
    if needs_migration():
        run_migration()

    # Initialize ChromaDB vector store
    try:
        from medina.db.vector_store import init_vector_store
        chroma_path = project_root / config.chroma_path
        init_vector_store(chroma_path)
    except Exception as e:
        logger.warning("ChromaDB init failed (vector search disabled): %s", e)

    # Seed dashboard from training files
    seed_dashboard()


@app.on_event("shutdown")
async def shutdown_event():
    from medina.db.engine import close_db
    from medina.db.vector_store import close_vector_store
    close_db()
    close_vector_store()


@app.get("/")
async def root():
    return {"name": "Medina API", "version": "0.1.0"}


@app.get("/health")
async def health():
    return {"status": "ok"}
