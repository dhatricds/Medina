"""Fixture and keynote position data for click-to-highlight."""
from __future__ import annotations

import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request

from medina.api.projects import get_project

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/projects", tags=["positions"])


@router.get("/{project_id}/page/{page_number}/positions")
async def get_page_positions(
    project_id: str,
    page_number: int,
    request: Request,
    sheet_code: str | None = None,
):
    """Return fixture and keynote positions for a specific page.

    Maps ``page_number`` to the plan's ``sheet_code`` via the project's
    page list, then looks up positions from the ``_positions.json`` file.
    When ``sheet_code`` is provided (e.g. for sub-plan viewports that share
    a physical page), the page_number→sheet_code resolution is skipped.
    """
    project = get_project(project_id, tenant_id=getattr(request.state, "tenant_id", "default"))
    if not project:
        raise HTTPException(404, "Project not found")

    if not project.output_path:
        return {"positions": None, "reason": "Project has no output yet"}

    # Resolve sheet_code from page_number (skip if caller provided it)
    result_data = project.result_data or {}
    pages = result_data.get("pages", [])
    if not sheet_code:
        for p in pages:
            if p.get("page_number") == page_number:
                sheet_code = p.get("sheet_code")
                break

    if not sheet_code:
        return {"positions": None, "reason": f"No sheet code for page {page_number}"}

    # Read positions file
    positions_path = Path(str(project.output_path) + "_positions.json")
    if not positions_path.exists():
        return {"positions": None, "reason": "No position data (processed before highlight feature)"}

    try:
        with open(positions_path, "r", encoding="utf-8") as f:
            all_positions = json.load(f)
    except Exception as e:
        logger.warning("Failed to read positions file: %s", e)
        return {"positions": None, "reason": "Failed to read position data"}

    page_data = all_positions.get(sheet_code)
    if not page_data:
        return {"positions": None, "reason": f"No positions for sheet {sheet_code}"}

    return {
        "sheet_code": sheet_code,
        "page_width": page_data.get("page_width", 0),
        "page_height": page_data.get("page_height", 0),
        "fixture_positions": page_data.get("fixture_positions", {}),
        "keynote_positions": page_data.get("keynote_positions", {}),
    }
