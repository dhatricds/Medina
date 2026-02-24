"""Chat routes — conversational interface for corrections and questions."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from pydantic import BaseModel, Field

from medina.api.chat import (
    ChatMessage,
    ChatResponse,
    generate_suggestions,
    process_chat_message,
)
from medina.api.feedback import (
    AGENT_COUNT,
    CorrectionReason,
    FixtureFeedback,
    ProjectFeedback,
    TARGET_ALL,
    derive_hints,
    derive_target,
    load_project_feedback,
    save_project_feedback,
)
from medina.api.fix_it import FixItAction
from medina.api.projects import get_project

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/projects", tags=["chat"])


class ChatRequest(BaseModel):
    message: str


class ConfirmActionsRequest(BaseModel):
    actions: list[FixItAction]


@router.get("/{project_id}/chat/history")
async def get_chat_history(project_id: str, request: Request, limit: int = 50):
    """Get chat history for a project."""
    project = get_project(project_id, tenant_id=getattr(request.state, "tenant_id", "default"))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    try:
        from medina.db import repositories as repo
        messages = repo.get_chat_history(project_id, limit=limit)
        return {"messages": messages}
    except Exception:
        return {"messages": []}


@router.post("/{project_id}/chat/message")
async def send_chat_message(project_id: str, request: Request, req: ChatRequest):
    """Send a message in the project chat."""
    project = get_project(project_id, tenant_id=getattr(request.state, "tenant_id", "default"))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if not req.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty")

    # Get source_key for memory lookup
    source_key = ""
    try:
        from medina.api.learnings import _source_key
        if project.source_path:
            source_key = _source_key(project.source_path)
    except Exception:
        pass

    result = await process_chat_message(
        user_text=req.message,
        project_data=project.result_data or {},
        project_id=project_id,
        source_key=source_key,
    )

    return result.model_dump()


@router.post("/{project_id}/chat/confirm")
async def confirm_chat_actions(
    project_id: str,
    request: Request,
    req: ConfirmActionsRequest,
    background_tasks: BackgroundTasks,
):
    """Confirm correction actions from chat and trigger reprocess."""
    project = get_project(project_id, tenant_id=getattr(request.state, "tenant_id", "default"))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.status == "running":
        raise HTTPException(status_code=409, detail="Project already running")
    if not req.actions:
        raise HTTPException(status_code=400, detail="No actions to confirm")

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

    # Valid CorrectionReason enum values
    valid_reasons = {r.value for r in CorrectionReason}

    # Check if this is a pure reprocess request (no specific corrections)
    is_pure_reprocess = all(a.action == "reprocess" for a in req.actions)

    if not is_pure_reprocess:
        for action in req.actions:
            if action.action == "reprocess":
                continue  # Skip the pseudo-action
            # LLM may return verbose reason strings — map to valid enum
            reason = action.reason
            if reason not in valid_reasons:
                reason = CorrectionReason.OTHER.value
            fb_item = FixtureFeedback(
                action=action.action,
                fixture_code=action.fixture_code,
                reason=reason,
                reason_detail=action.reason_detail or action.reason,
                fixture_data=action.fixture_data,
                spec_patches=action.spec_patches,
            )
            feedback.corrections.append(fb_item)

        feedback.updated_at = now
        save_project_feedback(feedback)

    # Derive hints and trigger reprocess
    hints = derive_hints(feedback) if feedback.corrections else None

    # Extract target: explicit from shortcut, or derive from action types
    explicit_target: frozenset[int] | None = None
    explicit_vision: bool | None = None
    for a in req.actions:
        if a.fixture_data and "target" in a.fixture_data:
            explicit_target = frozenset(a.fixture_data["target"])
            explicit_vision = a.fixture_data.get("use_vision")
            break

    if explicit_target is not None:
        target = explicit_target
    elif not is_pure_reprocess and feedback.corrections:
        target = derive_target(feedback.corrections, hints)
    else:
        target = TARGET_ALL

    if explicit_vision is not None:
        use_vision = explicit_vision
    else:
        use_vision = any(a.action == "reprocess" for a in req.actions) or (AGENT_COUNT in target)

    project.status = "running"
    project.current_agent = None
    project.error = None
    project.event_queue = asyncio.Queue()

    from medina.api.orchestrator_wrapper import run_pipeline
    background_tasks.add_task(
        run_pipeline, project, use_vision=use_vision,
        hints=hints, is_reprocess=True, target=target,
    )

    # Log confirmation in chat
    try:
        from medina.db import repositories as repo
        action_summary = ", ".join(
            f"{a.action} {a.fixture_code}" for a in req.actions
        )
        repo.add_chat_message(
            project_id, "system",
            f"Confirmed {len(req.actions)} actions: {action_summary}. Reprocessing...",
            intent="correction",
        )
    except Exception:
        pass

    return {
        "project_id": project_id,
        "status": "running",
        "actions_applied": len(req.actions),
    }


@router.get("/{project_id}/chat/suggestions")
async def get_suggestions(project_id: str, request: Request):
    """Get auto-generated suggestions for the current project."""
    project = get_project(project_id, tenant_id=getattr(request.state, "tenant_id", "default"))
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if not project.result_data:
        return {"suggestions": []}

    suggestions = generate_suggestions(project.result_data)

    # Add COVE-based suggestions
    try:
        from medina.db import repositories as repo
        cove_results = repo.get_cove_results(project_id)
        for cr in cove_results:
            if not cr.get("passed"):
                issues = cr.get("issues", [])
                for issue in issues[:2]:
                    msg = issue.get("message", "")
                    if msg:
                        suggestions.append(f"COVE: {msg[:80]}")
    except Exception:
        pass

    return {"suggestions": suggestions[:8]}
