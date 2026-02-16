"""Request/response Pydantic schemas for the API."""
from __future__ import annotations

from pydantic import BaseModel


class ProjectCreateResponse(BaseModel):
    project_id: str
    source: str


class ProjectStatusResponse(BaseModel):
    project_id: str
    status: str  # pending, running, completed, error
    current_agent: int | None = None


class AgentEvent(BaseModel):
    agent_id: int
    agent_name: str
    status: str  # running, completed, error
    stats: dict = {}
    time: float | None = None
    error: str | None = None


class CorrectionRequest(BaseModel):
    corrections: list[CorrectionItem]


class CorrectionItem(BaseModel):
    type: str  # "lighting" or "keynote"
    identifier: str
    sheet: str
    original: int
    corrected: int


class SourceItem(BaseModel):
    name: str
    path: str
    type: str  # "file" or "folder"
    size: int | None = None


class FromSourceRequest(BaseModel):
    source_path: str
