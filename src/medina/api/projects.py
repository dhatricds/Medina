"""In-memory project state store with tenant isolation."""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ProjectState:
    project_id: str
    source_path: Path
    tenant_id: str = "default"
    status: str = "pending"  # pending, running, completed, error
    current_agent: int | None = None
    result_data: dict | None = None
    work_dir: str | None = None
    output_path: str | None = None
    error: str | None = None
    event_queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    corrections: list[dict] = field(default_factory=list)


# Global in-memory store
_projects: dict[str, ProjectState] = {}


def create_project(source_path: Path, tenant_id: str = "default") -> ProjectState:
    """Create a new project and return its state."""
    project_id = uuid.uuid4().hex[:12]
    project = ProjectState(
        project_id=project_id,
        source_path=source_path,
        tenant_id=tenant_id,
    )
    _projects[project_id] = project
    return project


def get_project(project_id: str, tenant_id: str | None = None) -> ProjectState | None:
    """Retrieve project state by ID, optionally verifying tenant ownership."""
    project = _projects.get(project_id)
    if project and tenant_id and project.tenant_id != tenant_id:
        return None  # tenant mismatch — act as if not found
    return project


def list_projects(tenant_id: str | None = None) -> list[ProjectState]:
    """List projects, optionally filtered by tenant."""
    if tenant_id:
        return [p for p in _projects.values() if p.tenant_id == tenant_id]
    return list(_projects.values())
