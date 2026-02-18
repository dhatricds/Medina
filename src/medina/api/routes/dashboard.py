"""Dashboard CRUD routes for approved projects."""
from __future__ import annotations

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from medina.api.projects import get_project

logger = logging.getLogger(__name__)

DASHBOARD_DIR = Path(__file__).resolve().parents[4] / "output" / "dashboard"

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def _read_index() -> list[dict]:
    """Read the dashboard index file."""
    index_path = DASHBOARD_DIR / "index.json"
    if not index_path.exists():
        return []
    with open(index_path) as f:
        return json.load(f)


def _write_index(index: list[dict]) -> None:
    """Write the dashboard index file."""
    DASHBOARD_DIR.mkdir(parents=True, exist_ok=True)
    index_path = DASHBOARD_DIR / "index.json"
    with open(index_path, "w") as f:
        json.dump(index, f, indent=2)


@router.get("")
async def list_dashboard_projects():
    """List all approved dashboard projects (summary cards)."""
    return _read_index()


@router.get("/{dashboard_id}")
async def get_dashboard_project(dashboard_id: str):
    """Get full project data for a dashboard entry."""
    project_path = DASHBOARD_DIR / f"{dashboard_id}.json"
    if not project_path.exists():
        raise HTTPException(status_code=404, detail="Dashboard project not found")
    with open(project_path) as f:
        return json.load(f)


@router.get("/{dashboard_id}/export/excel")
async def export_dashboard_excel(dashboard_id: str):
    """Download the Excel file for a dashboard project."""
    xlsx_path = DASHBOARD_DIR / f"{dashboard_id}.xlsx"
    if not xlsx_path.exists():
        raise HTTPException(status_code=404, detail="Excel file not found")

    # Find project name for filename
    index = _read_index()
    name = dashboard_id
    for entry in index:
        if entry["id"] == dashboard_id:
            name = entry["name"]
            break

    filename = f"{name}_inventory.xlsx"
    return FileResponse(
        path=str(xlsx_path),
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.post("/approve/{project_id}")
async def approve_project(project_id: str):
    """Approve a processed project and add it to the dashboard."""
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if not project.result_data:
        # Try loading from disk
        if project.output_path:
            json_path = Path(f"{project.output_path}.json")
            if json_path.exists():
                with open(json_path) as f:
                    project.result_data = json.load(f)

    if not project.result_data:
        raise HTTPException(status_code=400, detail="Project has no results to approve")

    DASHBOARD_DIR.mkdir(parents=True, exist_ok=True)

    # Generate a dashboard ID from project name
    project_name = project.result_data.get("project_name", project_id)
    import re
    dashboard_id = re.sub(r"[^a-zA-Z0-9_-]", "_", project_name)[:60]

    # Check for duplicates and make unique
    index = _read_index()
    existing_ids = {e["id"] for e in index}
    base_id = dashboard_id
    counter = 1
    while dashboard_id in existing_ids:
        dashboard_id = f"{base_id}_{counter}"
        counter += 1

    # Save project data JSON
    project_json_path = DASHBOARD_DIR / f"{dashboard_id}.json"
    with open(project_json_path, "w") as f:
        json.dump(project.result_data, f, indent=2)

    # Copy Excel file if available
    if project.output_path:
        xlsx_src = Path(f"{project.output_path}.xlsx")
        if xlsx_src.exists():
            shutil.copy2(xlsx_src, DASHBOARD_DIR / f"{dashboard_id}.xlsx")

    # Build index entry
    summary = project.result_data.get("summary", {})
    qa = project.result_data.get("qa_report")
    now = datetime.now(timezone.utc).isoformat()

    entry = {
        "id": dashboard_id,
        "name": project_name,
        "approved_at": now,
        "fixture_types": summary.get("total_fixture_types", 0),
        "total_fixtures": summary.get("total_fixtures", 0),
        "keynote_count": summary.get("total_keynotes", 0),
        "plan_count": summary.get("total_lighting_plans", 0),
        "qa_score": qa.get("overall_confidence") if qa else None,
        "qa_passed": qa.get("passed") if qa else None,
    }
    index.append(entry)
    _write_index(index)

    logger.info("Project approved to dashboard: %s (%s)", project_name, dashboard_id)
    return entry


@router.delete("/{dashboard_id}")
async def delete_dashboard_project(dashboard_id: str):
    """Remove a project from the dashboard."""
    index = _read_index()
    new_index = [e for e in index if e["id"] != dashboard_id]

    if len(new_index) == len(index):
        raise HTTPException(status_code=404, detail="Dashboard project not found")

    _write_index(new_index)

    # Remove files
    for ext in (".json", ".xlsx"):
        file_path = DASHBOARD_DIR / f"{dashboard_id}{ext}"
        if file_path.exists():
            file_path.unlink()

    return {"deleted": dashboard_id}
