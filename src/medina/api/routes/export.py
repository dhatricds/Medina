"""Routes for Excel export."""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from medina.api.projects import get_project
from medina.api.routes.dashboard import _json_to_extraction_result
from medina.output.excel import write_excel

router = APIRouter(prefix="/api", tags=["export"])


class CorrectedExportRequest(BaseModel):
    """Frontend sends corrected fixtures/keynotes for Excel generation."""
    fixtures: list[dict[str, Any]] | None = None
    keynotes: list[dict[str, Any]] | None = None


@router.get("/projects/{project_id}/export/excel")
async def export_excel(project_id: str, request: Request):
    """Download the pipeline-generated Excel workbook (original counts)."""
    project = get_project(project_id, tenant_id=getattr(request.state, "tenant_id", "default"))
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


@router.post("/projects/{project_id}/export/excel")
async def export_corrected_excel(project_id: str, request: Request, body: CorrectedExportRequest):
    """Generate and download Excel with user-corrected counts.

    The frontend sends the current fixture/keynote data (including any
    edits the user has made) and this endpoint regenerates the Excel
    on-the-fly with those values.
    """
    project = get_project(project_id, tenant_id=getattr(request.state, "tenant_id", "default"))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if not project.result_data:
        raise HTTPException(status_code=400, detail="Project has no results")

    # Build corrected data dict — start from pipeline output, overlay corrections
    import json
    corrected_data = json.loads(json.dumps(project.result_data))

    if body.fixtures is not None:
        corrected_data["fixtures"] = body.fixtures
        # Recalc totals
        for f in corrected_data["fixtures"]:
            f["total"] = sum(f.get("counts_per_plan", {}).values())
        total_fixtures = sum(f["total"] for f in corrected_data["fixtures"])
        summary = corrected_data.get("summary", {})
        summary["total_fixture_types"] = len(corrected_data["fixtures"])
        summary["total_fixtures"] = total_fixtures
        corrected_data["summary"] = summary

    if body.keynotes is not None:
        corrected_data["keynotes"] = body.keynotes
        for k in corrected_data["keynotes"]:
            k["total"] = sum(k.get("counts_per_plan", {}).values())

    extraction_result = _json_to_extraction_result(corrected_data)
    tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
    tmp.close()
    write_excel(extraction_result, tmp.name)

    filename = f"{project.source_path.stem}_inventory.xlsx"
    return FileResponse(
        path=tmp.name,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
