"""Demo mode — load pre-computed results for instant display."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from medina.models import (
    ExtractionResult,
    FixtureRecord,
    KeyNote,
    QAReport,
    SheetIndexEntry,
    PageType,
)
from medina.ui.language import DEMO_PROJECTS

logger = logging.getLogger(__name__)

DEMO_DATA_DIR = Path(__file__).resolve().parents[3] / "demo_data"


def get_demo_project_names() -> list[str]:
    """Return display names for available demo projects."""
    available = []
    for name, filename in DEMO_PROJECTS.items():
        if (DEMO_DATA_DIR / filename).exists():
            available.append(name)
    return available


def load_demo_result(display_name: str) -> ExtractionResult | None:
    """Load a pre-computed demo result by display name.

    Parses the JSON back into an ExtractionResult model.
    Returns None if the file doesn't exist.
    """
    filename = DEMO_PROJECTS.get(display_name)
    if not filename:
        return None

    json_path = DEMO_DATA_DIR / filename
    if not json_path.exists():
        logger.warning("Demo data file not found: %s", json_path)
        return None

    data = json.loads(json_path.read_text(encoding="utf-8"))

    # Parse sheet index
    sheet_index = []
    for entry in data.get("sheet_index", []):
        inferred_type = None
        type_val = entry.get("type")
        if type_val and type_val != "other":
            try:
                inferred_type = PageType(type_val)
            except ValueError:
                pass
        sheet_index.append(SheetIndexEntry(
            sheet_code=entry["sheet_code"],
            description=entry["description"],
            inferred_type=inferred_type,
        ))

    # Parse fixtures
    fixtures = []
    for f in data.get("fixtures", []):
        fixtures.append(FixtureRecord(
            code=f["code"],
            description=f.get("description", ""),
            fixture_style=f.get("fixture_style", ""),
            voltage=f.get("voltage", ""),
            mounting=f.get("mounting", ""),
            lumens=f.get("lumens", ""),
            cct=f.get("cct", ""),
            dimming=f.get("dimming", ""),
            max_va=f.get("max_va", ""),
            counts_per_plan=f.get("counts_per_plan", {}),
            total=f.get("total", 0),
        ))

    # Parse keynotes
    keynotes = []
    for kn in data.get("keynotes", []):
        keynotes.append(KeyNote(
            number=kn["keynote_number"],
            text=kn["keynote_text"],
            counts_per_plan=kn.get("counts_per_plan", {}),
            total=kn.get("total", 0),
            fixture_references=kn.get("fixture_references", []),
        ))

    # Parse QA report
    qa_report = None
    qa_data = data.get("qa_report")
    if qa_data:
        qa_report = QAReport(
            overall_confidence=qa_data["overall_confidence"],
            passed=qa_data["passed"],
            threshold=qa_data["threshold"],
            stage_scores=qa_data.get("stage_scores", {}),
            warnings=qa_data.get("warnings", []),
            recommendations=qa_data.get("recommendations", []),
        )

    return ExtractionResult(
        source=data.get("project_name", display_name),
        sheet_index=sheet_index,
        pages=[],
        fixtures=fixtures,
        keynotes=keynotes,
        schedule_pages=data.get("schedule_pages", []),
        plan_pages=data.get("lighting_plans", []),
        qa_report=qa_report,
    )
