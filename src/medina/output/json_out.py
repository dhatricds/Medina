"""JSON output generation for frontend display."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from medina.models import ExtractionResult

logger = logging.getLogger(__name__)


def build_json_output(result: ExtractionResult) -> dict:
    """Build the structured JSON output dict for frontend consumption."""
    sheet_index_data = [
        {
            "sheet_code": entry.sheet_code,
            "description": entry.description,
            "type": entry.inferred_type.value if entry.inferred_type else "other",
        }
        for entry in result.sheet_index
    ]

    fixtures_data = [
        {
            "code": f.code,
            "description": f.description,
            "fixture_style": f.fixture_style,
            "voltage": f.voltage,
            "mounting": f.mounting,
            "lumens": f.lumens,
            "cct": f.cct,
            "dimming": f.dimming,
            "max_va": f.max_va,
            "counts_per_plan": f.counts_per_plan,
            "total": f.total,
        }
        for f in result.fixtures
    ]

    keynotes_data = [
        {
            "keynote_number": str(kn.number),
            "keynote_text": kn.text,
            "counts_per_plan": kn.counts_per_plan,
            "total": kn.total,
            "fixture_references": kn.fixture_references,
        }
        for kn in result.keynotes
    ]

    total_fixtures = sum(f.total for f in result.fixtures)

    qa_data = None
    if result.qa_report:
        qa_data = {
            "overall_confidence": result.qa_report.overall_confidence,
            "passed": result.qa_report.passed,
            "threshold": result.qa_report.threshold,
            "stage_scores": result.qa_report.stage_scores,
            "warnings": result.qa_report.warnings,
            "recommendations": result.qa_report.recommendations,
        }

    # Build a page list from pages (always available) so frontend can navigate
    # even when the sheet index is empty.  Include source_path and
    # pdf_page_index so the per-page PDF endpoint can resolve folder projects.
    pages_data = [
        {
            "page_number": p.page_number,
            "sheet_code": p.sheet_code or f"Page {p.page_number}",
            "description": p.sheet_title or "",
            "type": p.page_type.value if hasattr(p.page_type, "value") else str(p.page_type),
            "source_path": str(p.source_path),
            "pdf_page_index": p.pdf_page_index,
        }
        for p in result.pages
    ]

    return {
        "project_name": result.source,
        "total_pages": len(result.pages),
        "pages": pages_data,
        "sheet_index": sheet_index_data,
        "lighting_plans": result.plan_pages,
        "schedule_pages": result.schedule_pages,
        "fixtures": fixtures_data,
        "keynotes": keynotes_data,
        "summary": {
            "total_fixture_types": len(result.fixtures),
            "total_fixtures": total_fixtures,
            "total_lighting_plans": len(result.plan_pages),
            "total_keynotes": len(result.keynotes),
        },
        "qa_report": qa_data,
    }


def write_json(
    result: ExtractionResult,
    output_path: str | Path,
) -> Path:
    """Generate the JSON output file."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    data = build_json_output(result)

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    logger.info("JSON output saved to %s", output_path)
    return output_path


def write_positions_json(
    fixture_positions: dict,
    keynote_positions: dict,
    output_path: str | Path,
) -> Path:
    """Write fixture and keynote positions to a separate JSON file.

    This keeps the main results JSON lightweight while storing the
    per-fixture, per-keynote coordinate data needed for click-to-highlight.

    Args:
        fixture_positions: ``{sheet_code: {"page_width": float,
            "page_height": float, "fixtures": {code: [pos, ...]}}}``.
        keynote_positions: ``{sheet_code: {"page_width": float,
            "page_height": float, "keynotes": {number: [pos, ...]}}}``.
        output_path: Path to write (should end with ``_positions.json``).

    Returns:
        The output path.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Merge fixture and keynote positions per plan page
    all_plans: set[str] = set(fixture_positions) | set(keynote_positions)
    merged: dict[str, dict] = {}
    for plan in sorted(all_plans):
        fp = fixture_positions.get(plan, {})
        kp = keynote_positions.get(plan, {})
        merged[plan] = {
            "page_width": fp.get("page_width") or kp.get("page_width", 0),
            "page_height": fp.get("page_height") or kp.get("page_height", 0),
            "fixture_positions": fp.get("fixtures", {}),
            "keynote_positions": kp.get("keynotes", {}),
        }

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(merged, f, indent=2, ensure_ascii=False)

    logger.info("Positions JSON saved to %s", output_path)
    return output_path
