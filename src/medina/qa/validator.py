"""Cross-check and validate extraction results."""

from __future__ import annotations

import logging
import re

from medina.models import (
    ConfidenceFlag,
    ExtractionResult,
    FixtureRecord,
    KeyNote,
    QAItemResult,
)

logger = logging.getLogger(__name__)


def validate_schedule_completeness(
    fixtures: list[FixtureRecord],
) -> tuple[float, list[QAItemResult], list[str]]:
    """Check that schedule extraction captured all expected columns."""
    score = 1.0
    results: list[QAItemResult] = []
    warnings: list[str] = []

    required_fields = ["code", "description"]
    important_fields = ["voltage", "mounting", "lumens", "cct"]

    for fixture in fixtures:
        item_score = 1.0
        flags: list[ConfidenceFlag] = []
        notes_parts: list[str] = []

        if not fixture.code:
            continue

        missing_important = [
            f for f in important_fields if not getattr(fixture, f, "")
        ]
        if missing_important:
            penalty = 0.05 * len(missing_important)
            item_score -= penalty
            flags.append(ConfidenceFlag.MISSING_SCHEDULE_COLUMNS)
            notes_parts.append(
                f"Missing columns: {', '.join(missing_important)}"
            )

        if not fixture.description and not fixture.fixture_style:
            item_score -= 0.1
            flags.append(ConfidenceFlag.MISSING_SCHEDULE_COLUMNS)
            notes_parts.append("No description or style")

        results.append(QAItemResult(
            item_code=fixture.code,
            confidence=max(0.0, item_score),
            flags=flags,
            text_count=fixture.total,
            notes="; ".join(notes_parts),
        ))

    if results:
        score = sum(r.confidence for r in results) / len(results)
    if score < 0.9:
        warnings.append(
            f"Schedule extraction quality low ({score:.0%}): "
            "many missing columns"
        )

    return score, results, warnings


def validate_fixture_counts(
    fixtures: list[FixtureRecord],
    plan_pages: list[str],
) -> tuple[float, list[QAItemResult], list[str]]:
    """Validate fixture counting results."""
    score = 1.0
    results: list[QAItemResult] = []
    warnings: list[str] = []
    deductions = 0.0

    for fixture in fixtures:
        item_score = 1.0
        flags: list[ConfidenceFlag] = []
        notes_parts: list[str] = []

        if fixture.total == 0:
            item_score -= 0.3
            flags.append(ConfidenceFlag.FIXTURE_NOT_ON_ANY_PLAN)
            notes_parts.append("Not found on any plan page")
            warnings.append(
                f"Fixture {fixture.code}: found 0 times on all plans"
            )

        if re.match(r'^[A-Z]\d$', fixture.code):
            flags.append(ConfidenceFlag.AMBIGUOUS_CODE_MATCH)
            item_score -= 0.05
            notes_parts.append(
                "Short code may match room labels or other text"
            )

        if fixture.total == 1:
            notes_parts.append("Only 1 instance — verify count")
            warnings.append(
                f"Fixture {fixture.code}: found only 1 time — verify"
            )

        computed_total = sum(fixture.counts_per_plan.values())
        if computed_total != fixture.total:
            item_score -= 0.1
            notes_parts.append(
                f"Total mismatch: sum={computed_total}, total={fixture.total}"
            )

        results.append(QAItemResult(
            item_code=fixture.code,
            confidence=max(0.0, item_score),
            flags=flags,
            text_count=fixture.total,
            notes="; ".join(notes_parts),
        ))

    if results:
        score = sum(r.confidence for r in results) / len(results)

    zero_count = sum(1 for f in fixtures if f.total == 0)
    if zero_count > 0:
        deductions += 0.03 * zero_count
        score = max(0.0, score - deductions)

    return score, results, warnings


def validate_keynotes(
    keynotes: list[KeyNote],
    plan_pages: list[str],
) -> tuple[float, list[QAItemResult], list[str]]:
    """Validate keynote extraction results."""
    score = 1.0
    results: list[QAItemResult] = []
    warnings: list[str] = []

    for kn in keynotes:
        item_score = 1.0
        flags: list[ConfidenceFlag] = []
        notes_parts: list[str] = []

        if not kn.text or len(kn.text.strip()) < 3:
            item_score -= 0.2
            flags.append(ConfidenceFlag.KEYNOTE_PARSE_UNCERTAIN)
            notes_parts.append("Keynote text very short or empty")

        if kn.total == 0:
            item_score -= 0.1
            notes_parts.append("Keynote not referenced on any plan")

        results.append(QAItemResult(
            item_code=str(kn.number),
            confidence=max(0.0, item_score),
            flags=flags,
            text_count=kn.total,
            notes="; ".join(notes_parts),
        ))

    if results:
        score = sum(r.confidence for r in results) / len(results)

    return score, results, warnings


def validate_sheet_index(
    result: ExtractionResult,
) -> tuple[float, list[str]]:
    """Validate sheet index discovery completeness."""
    score = 1.0
    warnings: list[str] = []

    if not result.sheet_index:
        score -= 0.15
        warnings.append("No sheet index found — relying on fallback")
        return score, warnings

    index_codes = {e.sheet_code for e in result.sheet_index}
    found_codes = {p.sheet_code for p in result.pages if p.sheet_code}

    missing = index_codes - found_codes
    if missing:
        penalty = 0.05 * len(missing)
        score -= penalty
        warnings.append(
            f"Sheet index lists pages not found: {', '.join(sorted(missing))}"
        )

    if not result.plan_pages:
        score -= 0.2
        warnings.append("No lighting plan pages identified")

    if not result.schedule_pages:
        score -= 0.2
        warnings.append("No schedule pages identified")

    return max(0.0, score), warnings


def run_all_validations(
    result: ExtractionResult,
) -> dict:
    """Run all validation checks and return structured results."""
    sched_score, sched_results, sched_warnings = (
        validate_schedule_completeness(result.fixtures)
    )
    count_score, count_results, count_warnings = (
        validate_fixture_counts(result.fixtures, result.plan_pages)
    )
    kn_score, kn_results, kn_warnings = (
        validate_keynotes(result.keynotes, result.plan_pages)
    )
    idx_score, idx_warnings = validate_sheet_index(result)

    all_warnings = (
        sched_warnings + count_warnings + kn_warnings + idx_warnings
    )

    return {
        "stage_scores": {
            "sheet_index": idx_score,
            "schedule_extraction": sched_score,
            "fixture_counting": count_score,
            "keynote_extraction": kn_score,
        },
        "fixture_results": sched_results + count_results,
        "keynote_results": kn_results,
        "warnings": all_warnings,
    }
