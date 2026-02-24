"""Global pattern detection across correction learnings.

Analyzes corrections across all source files to detect recurring patterns.
When a pattern is observed across enough unique sources (PROMOTION_THRESHOLD),
it is promoted to a global pattern that applies to ALL future pipeline runs.

Storage: SQLite DB (primary), output/learnings/_global_patterns.json (fallback).
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from enum import Enum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from medina.api.feedback import FeedbackHints, FixtureFeedback
from medina.api.learnings import LEARNINGS_DIR, LearningEntry

logger = logging.getLogger(__name__)

PROMOTION_THRESHOLD = 3  # Unique sources before global promotion
GLOBAL_PATTERNS_FILE = LEARNINGS_DIR / "_global_patterns.json"


class PatternCategory(str, Enum):
    SYSTEMATIC_OVERCOUNT = "systematic_overcount"
    SYSTEMATIC_UNDERCOUNT = "systematic_undercount"
    SHORT_CODE_AMBIGUITY = "short_code_ambiguity"
    MISSING_FIXTURE_TYPE = "missing_fixture_type"
    PHANTOM_FIXTURE_TYPE = "phantom_fixture_type"
    SPEC_CORRECTION = "spec_correction"
    VLM_MISREAD = "vlm_misread"


class CorrectionPattern(BaseModel):
    """A recurring correction pattern detected across multiple sources."""
    pattern_type: str
    description: str
    source_count: int = 0
    examples: list[dict[str, Any]] = Field(default_factory=list)
    global_hint: dict[str, Any] = Field(default_factory=dict)
    source_keys: list[str] = Field(default_factory=list)


def categorize_correction(correction: FixtureFeedback) -> PatternCategory:
    """Map a single correction to its pattern category."""
    if correction.action == "count_override":
        corrected = correction.fixture_data.get("corrected", 0)
        original = correction.fixture_data.get("original", 0)
        if isinstance(corrected, (int, float)) and isinstance(original, (int, float)):
            if corrected < original:
                if len(correction.fixture_code) == 1:
                    return PatternCategory.SHORT_CODE_AMBIGUITY
                return PatternCategory.SYSTEMATIC_OVERCOUNT
            if corrected > original:
                return PatternCategory.SYSTEMATIC_UNDERCOUNT
        return PatternCategory.SYSTEMATIC_OVERCOUNT

    if correction.action == "remove":
        return PatternCategory.PHANTOM_FIXTURE_TYPE

    if correction.action == "add":
        return PatternCategory.MISSING_FIXTURE_TYPE

    if correction.action == "update_spec":
        if correction.reason == "vlm_misread":
            return PatternCategory.VLM_MISREAD
        return PatternCategory.SPEC_CORRECTION

    return PatternCategory.SYSTEMATIC_OVERCOUNT


def _load_all_learnings_from_db() -> list[tuple[str, LearningEntry]]:
    """Load all learnings from the DB."""
    try:
        from medina.db import repositories as repo
        rows = repo.get_all_learnings()
        entries: list[tuple[str, LearningEntry]] = []
        for row in rows:
            corrections = [
                FixtureFeedback.model_validate(c) if isinstance(c, dict) else c
                for c in row.get("corrections", [])
            ]
            entry = LearningEntry(
                source_key=row["source_key"],
                source_name=row.get("source_name", ""),
                source_path=row.get("source_path", ""),
                corrections=corrections,
                times_applied=row.get("times_applied", 0),
            )
            entries.append((entry.source_key, entry))
        return entries
    except Exception as e:
        logger.debug("DB learnings load failed: %s", e)
        return []


def _load_all_learnings_from_files() -> list[tuple[str, LearningEntry]]:
    """Fallback: load all learning files from disk."""
    if not LEARNINGS_DIR.exists():
        return []
    entries: list[tuple[str, LearningEntry]] = []
    for path in LEARNINGS_DIR.glob("*.json"):
        if path.name.startswith("_"):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            entry = LearningEntry.model_validate(data)
            entries.append((entry.source_key, entry))
        except Exception as e:
            logger.warning("Failed to load learning %s: %s", path.name, e)
    return entries


def _load_all_learnings() -> list[tuple[str, LearningEntry]]:
    """Load all learnings — DB first, file fallback."""
    entries = _load_all_learnings_from_db()
    if entries:
        return entries
    return _load_all_learnings_from_files()


def _load_global_patterns_from_db() -> list[CorrectionPattern]:
    """Load global patterns from DB."""
    try:
        from medina.db import repositories as repo
        rows = repo.get_all_global_patterns()
        return [
            CorrectionPattern(
                pattern_type=r["pattern_type"],
                description=r.get("description", ""),
                source_count=r.get("source_count", 0),
                examples=r.get("examples", []),
                global_hint=r.get("global_hint", {}),
                source_keys=r.get("source_keys", []),
            )
            for r in rows
        ]
    except Exception:
        return []


def _load_global_patterns() -> list[CorrectionPattern]:
    """Load existing global patterns — DB first, file fallback."""
    patterns = _load_global_patterns_from_db()
    if patterns:
        return patterns
    # File fallback
    if not GLOBAL_PATTERNS_FILE.exists():
        return []
    try:
        with open(GLOBAL_PATTERNS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [CorrectionPattern.model_validate(p) for p in data]
    except Exception as e:
        logger.warning("Failed to load global patterns: %s", e)
        return []


def _save_global_patterns(patterns: list[CorrectionPattern]) -> None:
    """Save global patterns to DB and file."""
    # Save to DB
    try:
        from medina.db import repositories as repo
        for p in patterns:
            repo.upsert_global_pattern(
                pattern_type=p.pattern_type,
                fixture_code=p.global_hint.get("fixture_code", ""),
                description=p.description,
                source_count=p.source_count,
                examples=p.examples,
                global_hint=p.global_hint,
                source_keys=p.source_keys,
            )
    except Exception as e:
        logger.debug("DB pattern save failed: %s", e)

    # Also save to file (backward compat)
    LEARNINGS_DIR.mkdir(parents=True, exist_ok=True)
    with open(GLOBAL_PATTERNS_FILE, "w", encoding="utf-8") as f:
        json.dump([p.model_dump() for p in patterns], f, indent=2)
    logger.info("Saved %d global patterns", len(patterns))


def scan_all_learnings() -> list[CorrectionPattern]:
    """Scan all learnings for recurring patterns across sources."""
    all_learnings = _load_all_learnings()
    if not all_learnings:
        return []

    groups: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {"source_keys": set(), "examples": []}
    )

    for source_key, entry in all_learnings:
        for correction in entry.corrections:
            category = categorize_correction(correction)
            key = (category.value, correction.fixture_code)
            groups[key]["source_keys"].add(source_key)
            if len(groups[key]["examples"]) < 5:
                groups[key]["examples"].append({
                    "source_key": source_key,
                    "source_name": entry.source_name,
                    "action": correction.action,
                    "fixture_code": correction.fixture_code,
                    "reason": correction.reason,
                    "fixture_data": correction.fixture_data,
                })

    patterns: list[CorrectionPattern] = []
    for (category, fixture_code), group_data in groups.items():
        source_keys = group_data["source_keys"]
        if len(source_keys) >= PROMOTION_THRESHOLD:
            desc = _describe_pattern(category, fixture_code, len(source_keys))
            hint = _build_global_hint(category, fixture_code, group_data["examples"])
            patterns.append(CorrectionPattern(
                pattern_type=category,
                description=desc,
                source_count=len(source_keys),
                examples=group_data["examples"],
                global_hint=hint,
                source_keys=sorted(source_keys),
            ))

    return patterns


def _describe_pattern(category: str, fixture_code: str, count: int) -> str:
    descs = {
        PatternCategory.SYSTEMATIC_OVERCOUNT.value:
            f"Fixture '{fixture_code}' is systematically overcounted ({count} sources)",
        PatternCategory.SYSTEMATIC_UNDERCOUNT.value:
            f"Fixture '{fixture_code}' is systematically undercounted ({count} sources)",
        PatternCategory.SHORT_CODE_AMBIGUITY.value:
            f"Short code '{fixture_code}' matches non-fixture text ({count} sources)",
        PatternCategory.MISSING_FIXTURE_TYPE.value:
            f"Fixture type '{fixture_code}' consistently missed by schedule parser ({count} sources)",
        PatternCategory.PHANTOM_FIXTURE_TYPE.value:
            f"Fixture type '{fixture_code}' consistently wrongly extracted ({count} sources)",
        PatternCategory.SPEC_CORRECTION.value:
            f"Spec for '{fixture_code}' consistently wrong ({count} sources)",
        PatternCategory.VLM_MISREAD.value:
            f"VLM consistently misreads '{fixture_code}' ({count} sources)",
    }
    return descs.get(category, f"Pattern for '{fixture_code}' ({count} sources)")


def _build_global_hint(
    category: str,
    fixture_code: str,
    examples: list[dict],
) -> dict[str, Any]:
    hint: dict[str, Any] = {"category": category, "fixture_code": fixture_code}

    if category == PatternCategory.PHANTOM_FIXTURE_TYPE.value:
        hint["action"] = "remove"
        hint["removed_codes"] = [fixture_code]

    elif category == PatternCategory.MISSING_FIXTURE_TYPE.value:
        for ex in reversed(examples):
            if ex.get("fixture_data"):
                hint["action"] = "add"
                hint["extra_fixture"] = ex["fixture_data"]
                break

    elif category in (
        PatternCategory.SHORT_CODE_AMBIGUITY.value,
        PatternCategory.SYSTEMATIC_OVERCOUNT.value,
    ):
        hint["action"] = "warn"
        hint["warning"] = (
            f"Code '{fixture_code}' frequently overcounted — "
            "consider vision-based verification"
        )

    return hint


def get_global_hints() -> FeedbackHints | None:
    """Build FeedbackHints from promoted global patterns."""
    patterns = _load_global_patterns()
    if not patterns:
        return None

    hints = FeedbackHints()

    for pattern in patterns:
        gh = pattern.global_hint
        action = gh.get("action", "")

        if action == "remove":
            codes = gh.get("removed_codes", [])
            hints.removed_codes.extend(codes)

        elif action == "add":
            fixture = gh.get("extra_fixture")
            if fixture and isinstance(fixture, dict):
                hints.extra_fixtures.append(fixture)

    # Deduplicate
    hints.removed_codes = sorted(set(hints.removed_codes))
    seen_codes = set()
    unique_fixtures: list[dict] = []
    for f in hints.extra_fixtures:
        code = f.get("code", "")
        if code not in seen_codes:
            seen_codes.add(code)
            unique_fixtures.append(f)
    hints.extra_fixtures = unique_fixtures

    if not hints.removed_codes and not hints.extra_fixtures:
        return None

    return hints


def record_correction_pattern(
    source_key: str,
    corrections: list[FixtureFeedback],
) -> list[CorrectionPattern]:
    """After learning promotion, check if any patterns cross threshold."""
    if not corrections:
        return []

    all_patterns = scan_all_learnings()
    if not all_patterns:
        return []

    existing = _load_global_patterns()
    existing_keys = {
        (p.pattern_type, p.global_hint.get("fixture_code", ""))
        for p in existing
    }

    new_patterns: list[CorrectionPattern] = []
    for pattern in all_patterns:
        key = (pattern.pattern_type, pattern.global_hint.get("fixture_code", ""))
        if key not in existing_keys:
            new_patterns.append(pattern)

    if new_patterns:
        merged = existing + new_patterns
        _save_global_patterns(merged)

    return new_patterns
