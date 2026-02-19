"""FastAPI application entry point."""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from medina.api.routes import (
    corrections,
    dashboard,
    demo,
    export,
    feedback,
    pages,
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

app = FastAPI(
    title="Medina API",
    description="Lighting Fixture Inventory Extraction API",
    version="0.1.0",
)

# CORS for frontend dev server
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:3000",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register routers
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


@app.on_event("startup")
async def startup_event():
    seed_dashboard()


@app.get("/")
async def root():
    return {"name": "Medina API", "version": "0.1.0"}


@app.get("/health")
async def health():
    return {"status": "ok"}
