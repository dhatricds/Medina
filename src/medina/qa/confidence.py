"""Compute per-item and overall confidence scores."""

from __future__ import annotations

import logging

from medina.models import (
    ExtractionResult,
    QAItemResult,
    QAReport,
)
from medina.qa.validator import run_all_validations

logger = logging.getLogger(__name__)

STAGE_WEIGHTS = {
    "sheet_index": 0.15,
    "schedule_extraction": 0.30,
    "fixture_counting": 0.40,
    "keynote_extraction": 0.15,
}


def compute_confidence(
    result: ExtractionResult,
    threshold: float = 0.95,
) -> QAReport:
    """Compute per-item and overall confidence scores.

    Overall confidence = weighted average of stage scores:
      - schedule_extraction: 30% weight
      - fixture_counting: 40% weight
      - keynote_extraction: 15% weight
      - sheet_index: 15% weight
    """
    validation = run_all_validations(result)
    stage_scores: dict[str, float] = validation["stage_scores"]
    fixture_results: list[QAItemResult] = validation["fixture_results"]
    keynote_results: list[QAItemResult] = validation["keynote_results"]
    warnings: list[str] = validation["warnings"]

    overall = 0.0
    for stage, weight in STAGE_WEIGHTS.items():
        score = stage_scores.get(stage, 1.0)
        overall += score * weight

    overall = max(0.0, min(1.0, overall))
    passed = overall >= threshold

    recommendations: list[str] = []
    if not passed:
        recommendations.append(
            "Overall confidence below threshold — review flagged items"
        )
    if stage_scores.get("fixture_counting", 1.0) < 0.9:
        recommendations.append(
            "Consider running --use-vision to cross-check text counts"
        )
    if stage_scores.get("schedule_extraction", 1.0) < 0.9:
        recommendations.append(
            "Schedule extraction had issues — verify fixture specs manually"
        )
    if stage_scores.get("sheet_index", 1.0) < 0.8:
        recommendations.append(
            "Sheet index incomplete — verify page classifications manually"
        )

    report = QAReport(
        overall_confidence=round(overall, 4),
        passed=passed,
        threshold=threshold,
        stage_scores={k: round(v, 4) for k, v in stage_scores.items()},
        fixture_results=fixture_results,
        keynote_results=keynote_results,
        warnings=warnings,
        recommendations=recommendations,
    )

    if passed:
        logger.info("QA PASSED — confidence: %.1f%%", overall * 100)
    else:
        logger.warning(
            "QA FAILED — confidence: %.1f%% (threshold: %.1f%%)",
            overall * 100,
            threshold * 100,
        )

    return report
