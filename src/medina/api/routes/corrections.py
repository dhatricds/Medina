"""Routes for saving user corrections."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from medina.api.models import CorrectionRequest
from medina.api.projects import get_project

router = APIRouter(prefix="/api", tags=["corrections"])


@router.patch("/projects/{project_id}/corrections")
async def save_corrections(project_id: str, request: Request, req: CorrectionRequest):
    """Save user cell corrections."""
    project = get_project(project_id, tenant_id=getattr(request.state, "tenant_id", "default"))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    for c in req.corrections:
        project.corrections.append(c.model_dump())

    # Persist to disk alongside the project output
    if project.output_path:
        corrections_path = Path(f"{project.output_path}_corrections.json")
        corrections_path.parent.mkdir(parents=True, exist_ok=True)
        with open(corrections_path, "w") as f:
            json.dump(project.corrections, f, indent=2)

    return {"saved": len(req.corrections), "total": len(project.corrections)}
