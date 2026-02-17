"""Routes for PDF page rendering and serving."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, Response

from medina.api.projects import get_project

router = APIRouter(prefix="/api", tags=["pages"])


@router.get("/projects/{project_id}/page/{page_number}")
async def get_page_image(
    project_id: str,
    page_number: int,
    dpi: int = Query(default=150, ge=72, le=300),
):
    """Render a PDF page as a PNG image (legacy fallback)."""
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        from medina.pdf.renderer import render_page_to_image

        png_bytes = render_page_to_image(
            project.source_path,
            page_number - 1,  # 0-indexed
            dpi=dpi,
        )
        return Response(content=png_bytes, media_type="image/png")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/projects/{project_id}/pdf")
async def get_pdf_file(project_id: str):
    """Serve the raw PDF file for client-side rendering."""
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    source = project.source_path
    if not source.exists():
        raise HTTPException(status_code=404, detail="PDF file not found")

    # For single-file PDFs, serve directly.
    # For folder-based projects, we can't serve a single PDF — fall back.
    if source.is_file() and source.suffix.lower() == ".pdf":
        return FileResponse(
            path=str(source),
            media_type="application/pdf",
            filename=source.name,
        )

    raise HTTPException(
        status_code=400,
        detail="Source is a folder, use per-page image endpoint instead",
    )
