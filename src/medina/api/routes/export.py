"""Routes for Excel export."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from medina.api.projects import get_project

router = APIRouter(prefix="/api", tags=["export"])


@router.get("/projects/{project_id}/export/excel")
async def export_excel(project_id: str):
    """Download the Excel workbook for a completed project."""
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if not project.output_path:
        raise HTTPException(status_code=404, detail="No output available")

    excel_path = Path(f"{project.output_path}.xlsx")
    if not excel_path.exists():
        raise HTTPException(status_code=404, detail="Excel file not found")

    filename = f"{project.source_path.stem}_inventory.xlsx"
    return FileResponse(
        path=str(excel_path),
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
