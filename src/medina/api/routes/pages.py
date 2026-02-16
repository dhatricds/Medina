"""Routes for PDF page rendering."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from medina.api.projects import get_project

router = APIRouter(prefix="/api", tags=["pages"])


@router.get("/projects/{project_id}/page/{page_number}")
async def get_page_image(
    project_id: str,
    page_number: int,
    dpi: int = Query(default=150, ge=72, le=300),
):
    """Render a PDF page as a PNG image."""
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
