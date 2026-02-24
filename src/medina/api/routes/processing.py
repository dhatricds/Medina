"""Routes for pipeline processing and SSE status streaming."""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from sse_starlette.sse import EventSourceResponse

from medina.api.models import FromSourceRequest, ProjectCreateResponse
from medina.api.projects import create_project, get_project
from medina.api.orchestrator_wrapper import run_pipeline

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["processing"])


@router.post("/projects/from-source", response_model=ProjectCreateResponse)
async def create_from_source(req: FromSourceRequest, request: Request):
    """Create a project from an existing data/ path."""
    from pathlib import Path

    source = Path(req.source_path)
    if not source.exists():
        raise HTTPException(status_code=404, detail=f"Source not found: {req.source_path}")

    tenant_id = getattr(request.state, "tenant_id", "default")
    project = create_project(source, tenant_id=tenant_id)
    return ProjectCreateResponse(
        project_id=project.project_id,
        source=str(source),
    )


@router.post("/projects/{project_id}/run")
async def run_project(project_id: str, request: Request, background_tasks: BackgroundTasks):
    """Start the pipeline for a project (runs in background)."""
    tenant_id = getattr(request.state, "tenant_id", "default")
    project = get_project(project_id, tenant_id=tenant_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.status == "running":
        raise HTTPException(status_code=409, detail="Project already running")

    project.status = "running"
    background_tasks.add_task(run_pipeline, project)

    return {"project_id": project_id, "status": "running"}


@router.get("/projects/{project_id}/status")
async def project_status_stream(project_id: str, request: Request):
    """SSE stream of agent progress events."""
    tenant_id = getattr(request.state, "tenant_id", "default")
    project = get_project(project_id, tenant_id=tenant_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    async def event_generator():
        heartbeat_interval = 30

        while True:
            try:
                event = await asyncio.wait_for(
                    project.event_queue.get(),
                    timeout=heartbeat_interval,
                )
                yield {
                    "event": event["event"],
                    "data": json.dumps(event["data"]),
                }
                if event["event"] in ("pipeline_complete", "pipeline_error"):
                    break
            except asyncio.TimeoutError:
                yield {"event": "heartbeat", "data": "{}"}

    return EventSourceResponse(event_generator())
