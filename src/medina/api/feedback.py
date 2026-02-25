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

# ── Agent targeting constants ─────────────────────────────────────────
AGENT_SEARCH, AGENT_SCHEDULE, AGENT_COUNT, AGENT_KEYNOTE, AGENT_QA = 1, 2, 3, 4, 5
TARGET_ALL: frozenset[int] = frozenset({1, 2, 3, 4, 5})

# Action type → minimum agent set that must run
_ACTION_TARGET: dict[str, frozenset[int]] = {
    "reprocess":              TARGET_ALL,
    "reclassify_page":        TARGET_ALL,
    "split_page":             TARGET_ALL,
    "add":                    frozenset({2, 3, 5}),   # schedule + count + QA
    "remove":                 frozenset({2, 3, 5}),
    "update_spec":            frozenset({2, 5}),       # schedule + QA
    "count_override":         frozenset({3, 5}),        # count + QA
    "keynote_count_override": frozenset({4, 5}),        # keynote + QA
    "keynote_add":            frozenset({4, 5}),        # keynote + QA
    "keynote_remove":         frozenset({4, 5}),        # keynote + QA
}


def derive_target(
    actions: list[FixtureFeedback] | None,
    hints: FeedbackHints | None,
) -> frozenset[int]:
    """Determine which agents to run based on actions and hints.

    QA (agent 5) always runs.  If search (agent 1) is triggered by any
    action, we cascade to TARGET_ALL because downstream agents depend on it.
    """
    target: frozenset[int] = frozenset({AGENT_QA})
    for action in actions or []:
        target = target | _ACTION_TARGET.get(action.action, TARGET_ALL)
    # Hints override: page/viewport changes → force all
    if hints and (hints.page_overrides or hints.viewport_splits):
        return TARGET_ALL
    # Cascade: if search is in target, must run everything downstream
    if AGENT_SEARCH in target:
        return TARGET_ALL
    return target


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
    # Keynote count overrides: {keynote_number: {sheet_code: corrected_count}}
    keynote_count_overrides: dict[str, dict[str, int]] = Field(default_factory=dict)
    # User-added keynotes: [{keynote_number, keynote_text, counts_per_plan}]
    extra_keynotes: list[dict[str, Any]] = Field(default_factory=list)
    # User-removed keynote numbers
    removed_keynote_numbers: list[str] = Field(default_factory=list)
    spec_patches: dict[str, dict[str, str]] = Field(default_factory=dict)
    # Rejected positions: {fixture_code: {sheet_code: [{x0,top,x1,bottom,cx,cy}]}}
    rejected_positions: dict[str, dict[str, list[dict[str, float]]]] = Field(
        default_factory=dict
    )
    # Added positions: {fixture_code: {sheet_code: [{x0,top,x1,bottom,cx,cy}]}}
    added_positions: dict[str, dict[str, list[dict[str, float]]]] = Field(
        default_factory=dict
    )
    # Page classification overrides: {sheet_code_or_page_num: page_type}
    page_overrides: dict[str, str] = Field(default_factory=dict)
    # Viewport splits: {sheet_code: [{"label": "L1", "title": "...", "bbox": [...], ...}]}
    viewport_splits: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)


def load_project_feedback(project_id: str) -> ProjectFeedback | None:
    """Load feedback for a project — DB first, then file fallback."""
    # Try DB
    try:
        from medina.db import repositories as repo
        rows = repo.get_corrections(project_id)
        if rows:
            corrections = [
                FixtureFeedback(
                    action=r["action"],
                    fixture_code=r["fixture_code"],
                    reason=r.get("reason", "other"),
                    reason_detail=r.get("reason_detail", ""),
                    fixture_data=r.get("fixture_data", {}),
                    spec_patches=r.get("spec_patches", {}),
                )
                for r in rows
            ]
            return ProjectFeedback(
                project_id=project_id,
                corrections=corrections,
            )
    except Exception as e:
        logger.debug("DB feedback load failed, trying file: %s", e)

    # Fallback to file
    path = FEEDBACK_DIR / f"{project_id}.json"
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return ProjectFeedback.model_validate(data)


def save_project_feedback(feedback: ProjectFeedback) -> None:
    """Save feedback for a project — DB primary, file backup."""
    # Save to DB
    saved_to_db = False
    try:
        from medina.db import repositories as repo
        from medina.api.learnings import _source_key
        source_path = Path(feedback.source_path) if feedback.source_path else None
        src_key = _source_key(source_path) if source_path else ""
        for corr in feedback.corrections:
            repo.add_correction(
                project_id=feedback.project_id,
                source_key=src_key,
                action=corr.action,
                fixture_code=corr.fixture_code,
                reason=corr.reason.value if isinstance(corr.reason, Enum) else corr.reason,
                reason_detail=corr.reason_detail,
                fixture_data=corr.fixture_data,
                spec_patches=corr.spec_patches,
                origin="user",
            )
        saved_to_db = True
    except Exception as e:
        logger.debug("DB feedback save failed, falling back to file: %s", e)

    # Always save to file too (backward compat)
    FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)
    path = FEEDBACK_DIR / f"{feedback.project_id}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(feedback.model_dump(), f, indent=2)
    logger.info("Saved feedback for project %s (%d corrections, db=%s)",
                feedback.project_id, len(feedback.corrections), saved_to_db)


def clear_project_feedback(project_id: str) -> None:
    """Clear all feedback for a project from both DB and file."""
    try:
        from medina.db import repositories as repo
        repo.clear_corrections(project_id)
    except Exception:
        pass
    fb_path = FEEDBACK_DIR / f"{project_id}.json"
    if fb_path.exists():
        fb_path.unlink()


def derive_hints(feedback: ProjectFeedback) -> FeedbackHints:
    """Convert user feedback corrections into pipeline hints.

    Processes corrections in order. Last action wins for conflicts.
    """
    hints = FeedbackHints()

    # Track final state per code
    added_codes: dict[str, dict] = {}
    removed_codes: set[str] = set()

    # Track keynote add/remove
    added_keynotes: dict[str, dict] = {}  # keynote_number → data
    removed_keynote_nums: set[str] = set()

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
            sheet = correction.fixture_data.get("sheet", "")
            corrected = correction.fixture_data.get("corrected")
            if sheet and corrected is not None:
                if code not in hints.count_overrides:
                    hints.count_overrides[code] = {}
                hints.count_overrides[code][sheet] = int(corrected)
            # Collect rejected positions
            rejected = correction.fixture_data.get("rejected_positions", [])
            if sheet and rejected:
                if code not in hints.rejected_positions:
                    hints.rejected_positions[code] = {}
                hints.rejected_positions[code][sheet] = [
                    {k: float(v) for k, v in pos.items()}
                    for pos in rejected
                    if isinstance(pos, dict)
                ]
            # Collect added positions
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
        elif correction.action == "keynote_count_override":
            kn_num = correction.fixture_data.get("keynote_number", "")
            sheet = correction.fixture_data.get("sheet", "")
            corrected = correction.fixture_data.get("corrected")
            if kn_num and sheet and corrected is not None:
                if kn_num not in hints.keynote_count_overrides:
                    hints.keynote_count_overrides[kn_num] = {}
                hints.keynote_count_overrides[kn_num][sheet] = int(corrected)
        elif correction.action == "keynote_add":
            kn_num = str(correction.fixture_data.get("keynote_number", ""))
            kn_text = correction.fixture_data.get("keynote_text", "")
            sheet = correction.fixture_data.get("sheet", "")
            kn_count = int(correction.fixture_data.get("corrected", 0))
            if kn_num:
                if kn_num in added_keynotes:
                    # Merge counts into existing entry
                    if sheet:
                        added_keynotes[kn_num]["counts_per_plan"][sheet] = kn_count
                else:
                    added_keynotes[kn_num] = {
                        "keynote_number": kn_num,
                        "keynote_text": kn_text,
                        "counts_per_plan": {sheet: kn_count} if sheet else {},
                    }
                removed_keynote_nums.discard(kn_num)
        elif correction.action == "keynote_remove":
            kn_num = str(correction.fixture_data.get("keynote_number", ""))
            if not kn_num:
                # Extract from fixture_code like "KN-3"
                kn_num = code.replace("KN-", "") if code.startswith("KN-") else ""
            if kn_num:
                removed_keynote_nums.add(kn_num)
                added_keynotes.pop(kn_num, None)
        elif correction.action == "reclassify_page":
            page_type = correction.fixture_data.get("page_type", "")
            if code and page_type:
                hints.page_overrides[code] = page_type
        elif correction.action == "split_page":
            if not code:
                continue
            viewports = correction.fixture_data.get("viewports", [])
            if viewports:
                hints.viewport_splits[code] = viewports
            else:
                hints.viewport_splits[code] = []
            if code not in hints.page_overrides:
                hints.page_overrides[code] = "lighting_plan"

    hints.extra_fixtures = list(added_codes.values())
    hints.removed_codes = sorted(removed_codes)
    hints.extra_keynotes = list(added_keynotes.values())
    hints.removed_keynote_numbers = sorted(removed_keynote_nums)

    return hints
