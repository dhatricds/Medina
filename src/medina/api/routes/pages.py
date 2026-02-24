"""Routes for PDF page rendering and serving."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response

from medina.api.projects import get_project

router = APIRouter(prefix="/api", tags=["pages"])


def _resolve_page_source(project, page_number: int) -> tuple[Path, int]:
    """Resolve the source file and page index for a given page number.

    For folder projects, looks up the specific file from results.
    For single-file projects, uses the source path directly.

    Returns:
        (source_path, page_index) where page_index is 0-based.
    """
    source = project.source_path
    page_index = page_number - 1

    if source.is_dir() and project.result_data:
        pages = project.result_data.get("pages", [])
        for p in pages:
            if p.get("page_number") == page_number:
                source = Path(p["source_path"])
                page_index = p.get("pdf_page_index", 0)
                break

    return source, page_index


@router.get("/projects/{project_id}/page/{page_number}")
async def get_page_image(
    project_id: str,
    page_number: int,
    request: Request,
    dpi: int = Query(default=150, ge=72, le=600),
):
    """Render a PDF page as a PNG image (fallback for non-PDF rendering)."""
    project = get_project(project_id, tenant_id=getattr(request.state, "tenant_id", "default"))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        from medina.pdf.renderer import render_page_to_image

        source, page_index = _resolve_page_source(project, page_number)
        png_bytes = render_page_to_image(source, page_index, dpi=dpi)
        return Response(content=png_bytes, media_type="image/png")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/projects/{project_id}/page/{page_number}/pdf")
async def get_page_as_pdf(
    project_id: str,
    page_number: int,
    request: Request,
):
    """Serve an individual page as a standalone PDF for client-side rendering.

    Extracts the requested page from the source PDF into a new single-page
    PDF document, enabling vector-quality client-side rendering via pdf.js.
    Works for both single-file and folder-based projects.
    """
    project = get_project(project_id, tenant_id=getattr(request.state, "tenant_id", "default"))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        import fitz

        source, page_index = _resolve_page_source(project, page_number)
        doc = fitz.open(str(source))
        try:
            if page_index < 0 or page_index >= len(doc):
                raise HTTPException(
                    status_code=404,
                    detail=f"Page {page_number} not found",
                )
            new_doc = fitz.open()
            new_doc.insert_pdf(doc, from_page=page_index, to_page=page_index)
            pdf_bytes = new_doc.tobytes()
            new_doc.close()
        finally:
            doc.close()

        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Cache-Control": "public, max-age=3600"},
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/projects/{project_id}/pdf")
async def get_pdf_file(project_id: str, request: Request):
    """Serve the raw PDF file for client-side rendering."""
    project = get_project(project_id, tenant_id=getattr(request.state, "tenant_id", "default"))
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
        detail="Source is a folder, use per-page PDF endpoint instead",
    )
