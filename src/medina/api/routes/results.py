"""Routes for retrieving pipeline results."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from medina.api.projects import get_project

router = APIRouter(prefix="/api", tags=["results"])


@router.get("/projects/{project_id}/results")
async def get_results(project_id: str, request: Request):
    """Get the full JSON result for a completed project."""
    tenant_id = getattr(request.state, "tenant_id", "default")
    project = get_project(project_id, tenant_id=tenant_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if project.result_data:
        return project.result_data

    # Try loading from disk
    if project.output_path:
        json_path = Path(f"{project.output_path}.json")
        if json_path.exists():
            with open(json_path) as f:
                project.result_data = json.load(f)
            return project.result_data

    raise HTTPException(status_code=404, detail="Results not available yet")
