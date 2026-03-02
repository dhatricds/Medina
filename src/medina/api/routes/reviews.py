"""Per-plan review progress tracking, keyed by source file identity."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from medina.api.projects import get_project
from medina.api.learnings import _source_key

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/projects", tags=["reviews"])

_REVIEWS_DIR = Path(__file__).resolve().parents[3] / "output" / "reviews"


class PlanReview(BaseModel):
    sheet_code: str
    status: str = "not_reviewed"  # not_reviewed | reviewed
    reviewed_by: str | None = None
    reviewed_by_name: str | None = None
    reviewed_at: str | None = None
    corrections_count: int = 0


class ReviewUpdate(BaseModel):
    status: str  # "reviewed" or "not_reviewed"


def _reviews_path(source_key: str) -> Path:
    return _REVIEWS_DIR / f"{source_key}.json"


def _load_reviews(source_key: str) -> dict[str, Any]:
    path = _reviews_path(source_key)
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def _save_reviews(source_key: str, reviews: dict[str, Any]) -> None:
    _REVIEWS_DIR.mkdir(parents=True, exist_ok=True)
    path = _reviews_path(source_key)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(reviews, f, indent=2)


def _get_source_key(project) -> str:
    """Derive source_key from a project's source_path."""
    return _source_key(project.source_path)


@router.get("/{project_id}/reviews")
async def get_reviews(project_id: str, request: Request):
    """Get review status for all plans in a project."""
    tenant_id = getattr(request.state, "tenant_id", "default")
    project = get_project(project_id, tenant_id=tenant_id)
    if not project:
        raise HTTPException(404, "Project not found")

    key = _get_source_key(project)
    reviews = _load_reviews(key)

    # Build plan list from project result data
    result_data = project.result_data or {}
    lighting_plans = result_data.get("lighting_plans", [])
    schedule_pages = result_data.get("schedule_pages", [])

    # Count corrections per plan from feedback
    corrections_per_plan: dict[str, int] = {}
    try:
        from medina.api.feedback import load_project_feedback
        fb = load_project_feedback(project_id)
        if fb:
            for c in fb.corrections:
                plan = getattr(c, "plan", None) or ""
                if plan:
                    corrections_per_plan[plan] = corrections_per_plan.get(plan, 0) + 1
    except Exception:
        pass

    plans: list[dict] = []

    # Add schedule pages first
    for sc in schedule_pages:
        r = reviews.get(sc, {})
        plans.append({
            "sheet_code": sc,
            "type": "schedule",
            "status": r.get("status", "not_reviewed"),
            "reviewed_by": r.get("reviewed_by"),
            "reviewed_by_name": r.get("reviewed_by_name"),
            "reviewed_at": r.get("reviewed_at"),
            "corrections_count": corrections_per_plan.get(sc, 0),
        })

    # Add lighting plans
    for lp in lighting_plans:
        r = reviews.get(lp, {})
        plans.append({
            "sheet_code": lp,
            "type": "lighting_plan",
            "status": r.get("status", "not_reviewed"),
            "reviewed_by": r.get("reviewed_by"),
            "reviewed_by_name": r.get("reviewed_by_name"),
            "reviewed_at": r.get("reviewed_at"),
            "corrections_count": corrections_per_plan.get(lp, 0),
        })

    reviewed = sum(1 for p in plans if p["status"] == "reviewed")
    total = len(plans)

    return {
        "project_id": project_id,
        "plans": plans,
        "reviewed": reviewed,
        "total": total,
    }


@router.patch("/{project_id}/reviews/{sheet_code}")
async def update_review(
    project_id: str,
    sheet_code: str,
    body: ReviewUpdate,
    request: Request,
):
    """Mark a plan as reviewed or not_reviewed."""
    tenant_id = getattr(request.state, "tenant_id", "default")
    project = get_project(project_id, tenant_id=tenant_id)
    if not project:
        raise HTTPException(404, "Project not found")

    key = _get_source_key(project)
    reviews = _load_reviews(key)

    user = getattr(request.state, "user", None)
    user_id = getattr(user, "id", None) if user else None
    user_name = getattr(user, "name", None) if user else None

    if body.status == "reviewed":
        reviews[sheet_code] = {
            "status": "reviewed",
            "reviewed_by": user_id,
            "reviewed_by_name": user_name,
            "reviewed_at": datetime.now(timezone.utc).isoformat(),
        }
    else:
        reviews[sheet_code] = {"status": "not_reviewed"}

    _save_reviews(key, reviews)

    return {
        "sheet_code": sheet_code,
        "status": body.status,
        "reviewed_by": reviews[sheet_code].get("reviewed_by"),
        "reviewed_by_name": reviews[sheet_code].get("reviewed_by_name"),
        "reviewed_at": reviews[sheet_code].get("reviewed_at"),
    }
