"""Runtime parameter API routes."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Any

from medina.runtime_params import PARAM_REGISTRY, get_effective_params, validate_param

router = APIRouter(prefix="/api", tags=["params"])


class ParamUpdate(BaseModel):
    params: dict[str, Any]
    scope: str = "project_id"  # or "global", "source_key"


@router.get("/params/registry")
async def get_registry():
    """Return the full parameter registry with metadata."""
    return {"params": PARAM_REGISTRY}


@router.get("/projects/{project_id}/params")
async def get_project_params(project_id: str, source_key: str = ""):
    """Get effective parameters for a project."""
    params = get_effective_params(source_key=source_key, project_id=project_id)
    return {"params": params}


@router.patch("/projects/{project_id}/params")
async def update_params(project_id: str, body: ParamUpdate):
    """Update parameters for a project/source/global scope."""
    try:
        from medina.db import repositories as repo
    except Exception:
        raise HTTPException(500, "Database not available")

    errors = {}
    updated = {}
    for key, value in body.params.items():
        try:
            validated = validate_param(key, value)
            scope_key = project_id if body.scope == "project_id" else ""
            repo.set_param(key, validated, scope=body.scope, scope_key=scope_key)
            updated[key] = validated
        except (KeyError, ValueError) as e:
            errors[key] = str(e)

    return {"updated": updated, "errors": errors}
