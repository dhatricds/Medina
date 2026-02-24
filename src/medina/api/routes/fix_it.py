"""Fix It routes — natural language correction interpretation and confirmation."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, Field

from medina.api.fix_it import FixItAction, FixItInterpretation, interpret_fix_it
from medina.api.feedback import (
    FixtureFeedback,
    ProjectFeedback,
    derive_hints,
    derive_target,
    load_project_feedback,
    save_project_feedback,
)
from medina.api.projects import get_project

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects", tags=["fix-it"])


class InterpretRequest(BaseModel):
    text: str


class ConfirmRequest(BaseModel):
    actions: list[FixItAction]


@router.post("/{project_id}/fix-it/interpret")
async def interpret_fix(project_id: str, request: Request, req: InterpretRequest):
    """Interpret a natural language correction into structured actions."""
    project = get_project(project_id, tenant_id=getattr(request.state, "tenant_id", "default"))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if not project.result_data:
        raise HTTPException(status_code=400, detail="No results to correct")

    if not req.text.strip():
        raise HTTPException(status_code=400, detail="Text cannot be empty")

    result = await interpret_fix_it(req.text, project.result_data)
    return result.model_dump()


@router.post("/{project_id}/fix-it/confirm")
async def confirm_fix(
    project_id: str,
    request: Request,
    req: ConfirmRequest,
    background_tasks: BackgroundTasks,
):
    """Confirm interpreted actions, save as feedback, and trigger reprocess."""
    project = get_project(project_id, tenant_id=getattr(request.state, "tenant_id", "default"))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.status == "running":
        raise HTTPException(status_code=409, detail="Project already running")

    if not req.actions:
        raise HTTPException(status_code=400, detail="No actions to confirm")

    # Convert FixItAction → FixtureFeedback and persist
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

    for action in req.actions:
        fb_item = FixtureFeedback(
            action=action.action,
            fixture_code=action.fixture_code,
            reason=action.reason,
            reason_detail=action.reason_detail,
            fixture_data=action.fixture_data,
            spec_patches=action.spec_patches,
        )
        feedback.corrections.append(fb_item)

    feedback.updated_at = now
    save_project_feedback(feedback)

    # Derive hints and target
    hints = derive_hints(feedback)
    target = derive_target(feedback.corrections, hints)

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
        "actions_applied": len(req.actions),
    }
