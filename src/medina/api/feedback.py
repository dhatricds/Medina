"""Feedback models and persistence for human-in-the-loop learning."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

FEEDBACK_DIR = Path(__file__).resolve().parents[3] / "output" / "feedback"


class CorrectionReason(str, Enum):
    MISSED_EMBEDDED_SCHEDULE = "missed_embedded_schedule"
    WRONG_FIXTURE_CODE = "wrong_fixture_code"
    EXTRA_FIXTURE = "extra_fixture"
    MISSING_FIXTURE = "missing_fixture"
    VLM_MISREAD = "vlm_misread"
    WRONG_BOUNDING_BOX = "wrong_bounding_box"
    MANUAL_COUNT_EDIT = "manual_count_edit"
    OTHER = "other"


class FixtureFeedback(BaseModel):
    action: str  # "add", "remove", "update_spec", "count_override"
    fixture_code: str
    reason: CorrectionReason = CorrectionReason.OTHER
    reason_detail: str = ""
    fixture_data: dict[str, Any] = Field(default_factory=dict)  # For "add": specs
    spec_patches: dict[str, str] = Field(default_factory=dict)  # For "update_spec"


class ProjectFeedback(BaseModel):
    project_id: str
    project_name: str = ""
    source_path: str = ""
    corrections: list[FixtureFeedback] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""


class FeedbackHints(BaseModel):
    """Derived hints passed to the pipeline for reprocessing."""
    extra_fixtures: list[dict[str, Any]] = Field(default_factory=list)
    removed_codes: list[str] = Field(default_factory=list)
    count_overrides: dict[str, dict[str, int]] = Field(default_factory=dict)
    spec_patches: dict[str, dict[str, str]] = Field(default_factory=dict)
    # Rejected positions: {fixture_code: {sheet_code: [{x0,top,x1,bottom,cx,cy}]}}
    # These are locations where the user said the pipeline incorrectly found a fixture.
    rejected_positions: dict[str, dict[str, list[dict[str, float]]]] = Field(
        default_factory=dict
    )
    # Added positions: {fixture_code: {sheet_code: [{x0,top,x1,bottom,cx,cy}]}}
    # These are locations where the user said a fixture exists but the pipeline missed it.
    added_positions: dict[str, dict[str, list[dict[str, float]]]] = Field(
        default_factory=dict
    )


def load_project_feedback(project_id: str) -> ProjectFeedback | None:
    """Load feedback for a project from disk."""
    path = FEEDBACK_DIR / f"{project_id}.json"
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return ProjectFeedback.model_validate(data)


def save_project_feedback(feedback: ProjectFeedback) -> None:
    """Save feedback for a project to disk."""
    FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)
    path = FEEDBACK_DIR / f"{feedback.project_id}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(feedback.model_dump(), f, indent=2)
    logger.info("Saved feedback for project %s (%d corrections)",
                feedback.project_id, len(feedback.corrections))


def derive_hints(feedback: ProjectFeedback) -> FeedbackHints:
    """Convert user feedback corrections into pipeline hints.

    Processes corrections in order. Last action wins for conflicts.
    """
    hints = FeedbackHints()

    # Track final state per code
    added_codes: dict[str, dict] = {}
    removed_codes: set[str] = set()

    for correction in feedback.corrections:
        code = correction.fixture_code
        if correction.action == "add":
            # Build fixture data dict from the correction
            fixture_data = {
                "code": code,
                "description": correction.fixture_data.get("description", ""),
                "fixture_style": correction.fixture_data.get("fixture_style", ""),
                "voltage": correction.fixture_data.get("voltage", ""),
                "mounting": correction.fixture_data.get("mounting", ""),
                "lumens": correction.fixture_data.get("lumens", ""),
                "cct": correction.fixture_data.get("cct", ""),
                "dimming": correction.fixture_data.get("dimming", ""),
                "max_va": correction.fixture_data.get("max_va", ""),
            }
            added_codes[code] = fixture_data
            removed_codes.discard(code)  # Re-add after remove
        elif correction.action == "remove":
            removed_codes.add(code)
            added_codes.pop(code, None)  # Remove after add
        elif correction.action == "count_override":
            # User corrected a count on a specific plan page
            # fixture_data: {"sheet": "E200", "corrected": 36,
            #   "rejected_positions": [{x0,top,x1,bottom,cx,cy}, ...]}
            sheet = correction.fixture_data.get("sheet", "")
            corrected = correction.fixture_data.get("corrected")
            if sheet and corrected is not None:
                if code not in hints.count_overrides:
                    hints.count_overrides[code] = {}
                hints.count_overrides[code][sheet] = int(corrected)
            # Collect rejected positions so the counter can skip them
            rejected = correction.fixture_data.get("rejected_positions", [])
            if sheet and rejected:
                if code not in hints.rejected_positions:
                    hints.rejected_positions[code] = {}
                # Last correction wins — replace previous rejections
                hints.rejected_positions[code][sheet] = [
                    {k: float(v) for k, v in pos.items()}
                    for pos in rejected
                    if isinstance(pos, dict)
                ]
            # Collect added positions so the counter knows what was missed
            added = correction.fixture_data.get("added_positions", [])
            if sheet and added:
                if code not in hints.added_positions:
                    hints.added_positions[code] = {}
                hints.added_positions[code][sheet] = [
                    {k: float(v) for k, v in pos.items()}
                    for pos in added
                    if isinstance(pos, dict)
                ]
        elif correction.action == "update_spec":
            if code not in hints.spec_patches:
                hints.spec_patches[code] = {}
            hints.spec_patches[code].update(correction.spec_patches)

    hints.extra_fixtures = list(added_codes.values())
    hints.removed_codes = sorted(removed_codes)

    return hints
