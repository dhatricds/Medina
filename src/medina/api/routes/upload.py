"""Routes for file upload."""
from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import APIRouter, File, Request, UploadFile

from medina.api.models import ProjectCreateResponse
from medina.api.projects import create_project

router = APIRouter(prefix="/api", tags=["upload"])

UPLOAD_DIR = Path("uploads")


@router.post("/upload", response_model=ProjectCreateResponse)
async def upload_file(request: Request, file: UploadFile = File(...)):
    """Upload a PDF file and create a project."""
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

    dest = UPLOAD_DIR / file.filename
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)

    tenant_id = getattr(request.state, "tenant_id", "default")
    project = create_project(dest, tenant_id=tenant_id)
    return ProjectCreateResponse(
        project_id=project.project_id,
        source=str(dest),
    )
