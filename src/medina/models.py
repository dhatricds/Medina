"""Core data models for Medina."""

from __future__ import annotations

from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field


class PageType(str, Enum):
    """Classification types for electrical drawing pages."""

    SYMBOLS_LEGEND = "symbols_legend"
    LIGHTING_PLAN = "lighting_plan"
    DEMOLITION_PLAN = "demolition_plan"
    POWER_PLAN = "power_plan"
    SCHEDULE = "schedule"
    DETAIL = "detail"
    COVER = "cover"
    SITE_PLAN = "site_plan"
    FIRE_ALARM = "fire_alarm"
    RISER = "riser"
    OTHER = "other"


class SheetIndexEntry(BaseModel):
    """A single entry from the sheet index found on the legend/cover page."""

    sheet_code: str
    description: str
    inferred_type: PageType | None = None


class PageInfo(BaseModel):
    """Metadata for a single page in the document set."""

    page_number: int
    sheet_code: str | None = None
    sheet_title: str | None = None
    page_type: PageType = PageType.OTHER
    source_path: Path
    pdf_page_index: int = 0


class FixtureRecord(BaseModel):
    """A single fixture type extracted from a luminaire schedule."""

    code: str
    description: str = ""
    fixture_style: str = ""
    voltage: str = ""
    mounting: str = ""
    lumens: str = ""
    cct: str = ""
    dimming: str = ""
    max_va: str = ""
    counts_per_plan: dict[str, int] = Field(default_factory=dict)
    total: int = 0


class KeyNote(BaseModel):
    """A key note extracted from plan pages."""

    number: int | str
    text: str
    counts_per_plan: dict[str, int] = Field(default_factory=dict)
    total: int = 0
    fixture_references: list[str] = Field(default_factory=list)


class ConfidenceFlag(str, Enum):
    """Reasons why a QA check may lower confidence."""

    TEXT_VISION_MISMATCH = "text_vision_mismatch"
    LOW_TEXT_QUALITY = "low_text_quality"
    MISSING_SCHEDULE_COLUMNS = "missing_schedule_cols"
    FIXTURE_NOT_ON_ANY_PLAN = "fixture_not_on_plan"
    AMBIGUOUS_CODE_MATCH = "ambiguous_code_match"
    KEYNOTE_PARSE_UNCERTAIN = "keynote_parse_uncertain"
    SHEET_INDEX_INCOMPLETE = "sheet_index_incomplete"


class QAItemResult(BaseModel):
    """QA result for a single fixture or keynote."""

    item_code: str
    confidence: float = 1.0
    flags: list[ConfidenceFlag] = Field(default_factory=list)
    text_count: int | None = None
    vision_count: int | None = None
    notes: str = ""


class QAReport(BaseModel):
    """Overall QA report for the entire extraction."""

    overall_confidence: float = 1.0
    passed: bool = True
    threshold: float = 0.95
    stage_scores: dict[str, float] = Field(default_factory=dict)
    fixture_results: list[QAItemResult] = Field(default_factory=list)
    keynote_results: list[QAItemResult] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)


class ExtractionResult(BaseModel):
    """Complete result of processing a document set."""

    source: str
    sheet_index: list[SheetIndexEntry] = Field(default_factory=list)
    pages: list[PageInfo] = Field(default_factory=list)
    fixtures: list[FixtureRecord] = Field(default_factory=list)
    keynotes: list[KeyNote] = Field(default_factory=list)
    schedule_pages: list[str] = Field(default_factory=list)
    plan_pages: list[str] = Field(default_factory=list)
    qa_report: QAReport | None = None
