"""Global learning store for human-in-the-loop corrections.

Corrections from user feedback are promoted to a persistent learning store
indexed by source file identity (filename).  On every pipeline run, the
system checks for existing learnings and automatically applies them as hints
— so corrections made once are never forgotten.

Storage layout:
    output/learnings/
        {source_key}.json     # Corrections for a specific source file
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from medina.api.feedback import FeedbackHints, FixtureFeedback, derive_hints, ProjectFeedback

logger = logging.getLogger(__name__)

LEARNINGS_DIR = Path(__file__).resolve().parents[3] / "output" / "learnings"


def _source_key(source_path: Path) -> str:
    """Derive a stable key from a source path.

    Uses the filename (for files) or folder name (for directories),
    sanitized for filesystem safety.
    """
    if source_path.is_file():
        name = source_path.stem
    else:
        name = source_path.name
    # Sanitize: replace non-alphanumeric chars with underscores, keep short
    safe = "".join(c if c.isalnum() or c in "-_ " else "_" for c in name)
    # Add a short hash of full path to avoid collisions for same-named files
    path_hash = hashlib.md5(str(source_path.resolve()).encode()).hexdigest()[:8]
    return f"{safe}_{path_hash}"


class LearningEntry(BaseModel):
    """Persistent learnings for a specific source file."""
    source_key: str
    source_name: str = ""
    source_path: str = ""
    corrections: list[FixtureFeedback] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    times_applied: int = 0


def load_learnings(source_path: Path) -> LearningEntry | None:
    """Load learnings for a source file, if any exist."""
    key = _source_key(source_path)
    path = LEARNINGS_DIR / f"{key}.json"
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        entry = LearningEntry.model_validate(data)
        logger.info(
            "Loaded %d learnings for %s (applied %d times before)",
            len(entry.corrections), entry.source_name, entry.times_applied,
        )
        return entry
    except Exception as e:
        logger.warning("Failed to load learnings for %s: %s", key, e)
        return None


def save_learnings(source_path: Path, corrections: list[FixtureFeedback]) -> None:
    """Save corrections as persistent learnings for a source file.

    Merges with existing learnings — new corrections for the same fixture
    code and action replace old ones (last correction wins).
    """
    key = _source_key(source_path)
    LEARNINGS_DIR.mkdir(parents=True, exist_ok=True)
    path = LEARNINGS_DIR / f"{key}.json"

    now = datetime.now(timezone.utc).isoformat()
    name = source_path.stem if source_path.is_file() else source_path.name

    # Load existing
    existing = load_learnings(source_path)
    if existing is None:
        existing = LearningEntry(
            source_key=key,
            source_name=name,
            source_path=str(source_path),
            created_at=now,
        )

    # Merge: new corrections override old ones for same (code, action) pair.
    # Keep the order: existing first, then new.  Last one wins in derive_hints.
    merged = list(existing.corrections) + list(corrections)
    existing.corrections = merged
    existing.updated_at = now

    with open(path, "w", encoding="utf-8") as f:
        json.dump(existing.model_dump(), f, indent=2)

    logger.info(
        "Saved %d learnings for %s (%s)",
        len(merged), name, key,
    )


def derive_learned_hints(source_path: Path) -> FeedbackHints | None:
    """Load learnings for a source and derive pipeline hints.

    Returns None if no learnings exist for this source.
    """
    entry = load_learnings(source_path)
    if entry is None or not entry.corrections:
        return None

    # Build a ProjectFeedback wrapper so we can reuse derive_hints()
    pf = ProjectFeedback(
        project_id="learnings",
        project_name=entry.source_name,
        source_path=entry.source_path,
        corrections=entry.corrections,
    )
    hints = derive_hints(pf)

    # Track usage
    entry.times_applied += 1
    entry.updated_at = datetime.now(timezone.utc).isoformat()
    LEARNINGS_DIR.mkdir(parents=True, exist_ok=True)
    path = LEARNINGS_DIR / f"{entry.source_key}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(entry.model_dump(), f, indent=2)

    return hints


def merge_hints(base: FeedbackHints | None, overlay: FeedbackHints | None) -> FeedbackHints | None:
    """Merge two sets of hints. Overlay takes priority for conflicts."""
    if base is None:
        return overlay
    if overlay is None:
        return base

    merged = FeedbackHints()

    # Extra fixtures: combine, overlay wins for same code
    base_codes = {f["code"]: f for f in base.extra_fixtures}
    for f in overlay.extra_fixtures:
        base_codes[f["code"]] = f
    merged.extra_fixtures = list(base_codes.values())

    # Removed codes: union
    merged.removed_codes = sorted(set(base.removed_codes) | set(overlay.removed_codes))

    # Count overrides: overlay wins per (code, plan)
    merged.count_overrides = {**base.count_overrides}
    for code, plans in overlay.count_overrides.items():
        if code not in merged.count_overrides:
            merged.count_overrides[code] = {}
        merged.count_overrides[code].update(plans)

    # Spec patches: overlay wins per (code, field)
    merged.spec_patches = {**base.spec_patches}
    for code, patches in overlay.spec_patches.items():
        if code not in merged.spec_patches:
            merged.spec_patches[code] = {}
        merged.spec_patches[code].update(patches)

    # Rejected positions: overlay wins per (code, plan)
    merged.rejected_positions = {**base.rejected_positions}
    for code, plans in overlay.rejected_positions.items():
        if code not in merged.rejected_positions:
            merged.rejected_positions[code] = {}
        merged.rejected_positions[code].update(plans)

    # Added positions: overlay wins per (code, plan)
    merged.added_positions = {**base.added_positions}
    for code, plans in overlay.added_positions.items():
        if code not in merged.added_positions:
            merged.added_positions[code] = {}
        merged.added_positions[code].update(plans)

    return merged
