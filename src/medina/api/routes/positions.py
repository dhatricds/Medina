"""Fixture and keynote position data for click-to-highlight."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from medina.api.projects import get_project

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/projects", tags=["positions"])

# In-memory cache of on-demand positions keyed by (project_id, sheet_code)
_on_demand_cache: dict[tuple[str, str], dict] = {}


def _extract_positions_on_demand(
    project: Any,
    page_number: int,
    sheet_code: str,
) -> dict | None:
    """Extract fixture and keynote positions on-the-fly for a single page.

    Used when no pre-computed _positions.json exists (e.g. for seed/older
    dashboard projects opened for editing).
    """
    cache_key = (project.project_id, sheet_code)
    if cache_key in _on_demand_cache:
        return _on_demand_cache[cache_key]

    result_data = project.result_data or {}
    fixture_codes = [f["code"] for f in result_data.get("fixtures", [])]
    keynote_numbers = [
        str(k.get("keynote_number", k.get("number", "")))
        for k in result_data.get("keynotes", [])
    ]

    if not fixture_codes and not keynote_numbers:
        return None

    # Resolve the PDF source file and page index
    source_path = project.source_path
    pdf_page_index = page_number - 1

    pages = result_data.get("pages", [])
    for p in pages:
        if p.get("page_number") == page_number:
            if p.get("source_path"):
                source_path = Path(p["source_path"])
            pdf_page_index = p.get("pdf_page_index", page_number - 1)
            break

    try:
        import pdfplumber
        from medina.models import PageInfo, PageType

        page_info = PageInfo(
            page_number=page_number,
            sheet_code=sheet_code,
            sheet_title="",
            page_type=PageType.LIGHTING_PLAN,
            source_path=source_path,
            pdf_page_index=pdf_page_index,
        )

        pdf = pdfplumber.open(str(source_path))
        pdf_page = pdf.pages[pdf_page_index]

        page_data: dict = {
            "page_width": float(pdf_page.width),
            "page_height": float(pdf_page.height),
            "fixture_positions": {},
            "keynote_positions": {},
        }

        # Extract fixture positions
        if fixture_codes:
            from medina.plans.text_counter import count_fixtures_on_plan
            plan_sheet_codes = result_data.get("lighting_plans", [])
            enriched = count_fixtures_on_plan(
                page_info, pdf_page, fixture_codes,
                plan_sheet_codes=plan_sheet_codes,
                return_positions=True,
            )
            for code, data in enriched.items():
                if isinstance(data, dict) and data.get("positions"):
                    page_data["fixture_positions"][code] = data["positions"]

        # Extract keynote positions (non-fatal — don't lose fixture positions)
        if keynote_numbers:
            try:
                from medina.plans.keynotes import extract_keynotes_from_plan
                all_fixture_codes = [f["code"] for f in result_data.get("fixtures", [])]
                result_tuple = extract_keynotes_from_plan(
                    page_info, pdf_page,
                    known_fixture_codes=all_fixture_codes,
                    return_positions=True,
                )
                # Returns (keynotes_list, counts_dict, positions_dict)
                if len(result_tuple) >= 3:
                    kn_positions = result_tuple[2]
                    for num, pos_list in kn_positions.items():
                        if pos_list:
                            page_data["keynote_positions"][str(num)] = pos_list
            except Exception as ke:
                logger.warning("Keynote position extraction failed for %s: %s", sheet_code, ke)

        pdf.close()

        # Cache the result
        _on_demand_cache[cache_key] = page_data
        logger.info(
            "Generated on-demand positions for %s page %d: %d fixtures, %d keynotes",
            sheet_code, page_number,
            len(page_data["fixture_positions"]),
            len(page_data["keynote_positions"]),
        )
        return page_data

    except Exception as e:
        logger.warning("Failed to extract on-demand positions for %s: %s", sheet_code, e)
        return None


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

    If no pre-computed positions file exists (e.g. for seed/older dashboard
    projects), positions are extracted on-the-fly from the source PDF.
    """
    project = get_project(project_id, tenant_id=getattr(request.state, "tenant_id", "default"))
    if not project:
        raise HTTPException(404, "Project not found")

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

    # Try reading pre-computed positions file
    if project.output_path:
        positions_path = Path(str(project.output_path) + "_positions.json")
        if positions_path.exists():
            try:
                with open(positions_path, "r", encoding="utf-8") as f:
                    all_positions = json.load(f)
                page_data = all_positions.get(sheet_code)
                if page_data:
                    return {
                        "sheet_code": sheet_code,
                        "page_width": page_data.get("page_width", 0),
                        "page_height": page_data.get("page_height", 0),
                        "fixture_positions": page_data.get("fixture_positions", {}),
                        "keynote_positions": page_data.get("keynote_positions", {}),
                    }
            except Exception as e:
                logger.warning("Failed to read positions file: %s", e)

    # No pre-computed positions — extract on demand
    page_data = _extract_positions_on_demand(project, page_number, sheet_code)
    if page_data:
        return {
            "sheet_code": sheet_code,
            "page_width": page_data.get("page_width", 0),
            "page_height": page_data.get("page_height", 0),
            "fixture_positions": page_data.get("fixture_positions", {}),
            "keynote_positions": page_data.get("keynote_positions", {}),
        }

    return {"positions": None, "reason": f"No positions available for sheet {sheet_code}"}
