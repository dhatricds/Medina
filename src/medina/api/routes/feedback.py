"""Feedback routes for human-in-the-loop corrections."""
from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from medina.api.feedback import (
    CorrectionReason,
    FeedbackHints,
    FixtureFeedback,
    ProjectFeedback,
    derive_hints,
    derive_target,
    load_project_feedback,
    save_project_feedback,
)
from medina.api.projects import get_project

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects", tags=["feedback"])


@router.post("/{project_id}/feedback")
async def submit_feedback(project_id: str, request: Request, item: FixtureFeedback):
    """Submit a single correction for a project."""
    project = get_project(project_id, tenant_id=getattr(request.state, "tenant_id", "default"))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()

    feedback = load_project_feedback(project_id)
    if feedback is None:
        project_name = ""
        if project.result_data:
            project_name = project.result_data.get("project_name", "")
        feedback = ProjectFeedback(
            project_id=project_id,
            project_name=project_name,
            source_path=str(project.source_path),
            created_at=now,
            updated_at=now,
        )

    feedback.corrections.append(item)
    feedback.updated_at = now
    save_project_feedback(feedback)

    return {
        "project_id": project_id,
        "correction_count": len(feedback.corrections),
        "corrections": [c.model_dump() for c in feedback.corrections],
    }


@router.get("/{project_id}/feedback")
async def get_feedback(project_id: str, request: Request):
    """Get all feedback corrections for a project."""
    feedback = load_project_feedback(project_id)
    if feedback is None:
        return {"project_id": project_id, "corrections": [], "correction_count": 0}
    return {
        "project_id": project_id,
        "correction_count": len(feedback.corrections),
        "corrections": [c.model_dump() for c in feedback.corrections],
    }


@router.delete("/{project_id}/feedback/{index}")
async def remove_feedback(project_id: str, index: int, request: Request):
    """Remove a feedback correction by index."""
    feedback = load_project_feedback(project_id)
    if feedback is None:
        raise HTTPException(status_code=404, detail="No feedback for this project")
    if index < 0 or index >= len(feedback.corrections):
        raise HTTPException(status_code=404, detail="Correction index out of range")

    removed = feedback.corrections.pop(index)
    from datetime import datetime, timezone
    feedback.updated_at = datetime.now(timezone.utc).isoformat()
    save_project_feedback(feedback)

    return {
        "project_id": project_id,
        "removed": removed.model_dump(),
        "correction_count": len(feedback.corrections),
    }


@router.post("/{project_id}/reprocess")
async def reprocess_project(project_id: str, request: Request, background_tasks: BackgroundTasks):
    """Reprocess a project with accumulated feedback as hints."""
    project = get_project(project_id, tenant_id=getattr(request.state, "tenant_id", "default"))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.status == "running":
        raise HTTPException(status_code=409, detail="Project already running")

    # Load and derive hints
    feedback = load_project_feedback(project_id)
    hints = derive_hints(feedback) if feedback else None
    target = derive_target(feedback.corrections if feedback else [], hints)

    # Reset project state for reprocessing
    project.status = "running"
    project.current_agent = None
    project.error = None
    project.event_queue = asyncio.Queue()

    from medina.api.orchestrator_wrapper import run_pipeline
    background_tasks.add_task(
        run_pipeline, project, hints=hints, is_reprocess=True, target=target,
    )

    return {
        "project_id": project_id,
        "status": "running",
        "hint_summary": {
            "extra_fixtures": len(hints.extra_fixtures) if hints else 0,
            "removed_codes": len(hints.removed_codes) if hints else 0,
            "spec_patches": len(hints.spec_patches) if hints else 0,
        },
    }
