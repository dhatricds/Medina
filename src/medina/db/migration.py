"""One-time migration from file-based JSON storage to SQLite DB.

Migrates:
  output/learnings/*.json  → learnings table
  output/feedback/*.json   → corrections table
  output/learnings/_global_patterns.json → global_patterns table
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

from medina.db.engine import get_conn
from medina.db import repositories as repo

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[3]
_LEARNINGS_DIR = _PROJECT_ROOT / "output" / "learnings"
_FEEDBACK_DIR = _PROJECT_ROOT / "output" / "feedback"
_MIGRATED_MARKER = _PROJECT_ROOT / "output" / ".db_migrated"


def needs_migration() -> bool:
    """Check if migration is needed."""
    if _MIGRATED_MARKER.exists():
        return False
    return _LEARNINGS_DIR.exists() or _FEEDBACK_DIR.exists()


def run_migration() -> None:
    """Migrate JSON files to SQLite DB."""
    if not needs_migration():
        logger.info("No migration needed (already migrated or no JSON files)")
        return

    logger.info("Starting migration from JSON files to SQLite DB...")
    migrated = 0

    # Migrate learnings
    if _LEARNINGS_DIR.exists():
        for path in _LEARNINGS_DIR.glob("*.json"):
            if path.name.startswith("_"):
                # Handle _global_patterns.json separately
                if path.name == "_global_patterns.json":
                    migrated += _migrate_global_patterns(path)
                continue
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                repo.upsert_learning(
                    source_key=data.get("source_key", path.stem),
                    source_name=data.get("source_name", ""),
                    source_path=data.get("source_path", ""),
                    corrections_json=json.dumps(data.get("corrections", [])),
                    times_applied=data.get("times_applied", 0),
                )
                migrated += 1
                logger.info("Migrated learning: %s", path.name)
            except Exception as e:
                logger.warning("Failed to migrate %s: %s", path.name, e)

    # Migrate feedback
    if _FEEDBACK_DIR.exists():
        for path in _FEEDBACK_DIR.glob("*.json"):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                project_id = data.get("project_id", path.stem)
                source_path = data.get("source_path", "")
                for correction in data.get("corrections", []):
                    repo.add_correction(
                        project_id=project_id,
                        source_key="",
                        action=correction.get("action", ""),
                        fixture_code=correction.get("fixture_code", ""),
                        reason=correction.get("reason", "other"),
                        reason_detail=correction.get("reason_detail", ""),
                        fixture_data=correction.get("fixture_data"),
                        spec_patches=correction.get("spec_patches"),
                        origin="migrated",
                    )
                migrated += 1
                logger.info("Migrated feedback: %s", path.name)
            except Exception as e:
                logger.warning("Failed to migrate %s: %s", path.name, e)

    # Write marker
    _MIGRATED_MARKER.parent.mkdir(parents=True, exist_ok=True)
    _MIGRATED_MARKER.write_text(f"Migrated {migrated} files\n")
    logger.info("Migration complete: %d files migrated", migrated)


def _migrate_global_patterns(path: Path) -> int:
    """Migrate _global_patterns.json to the global_patterns table."""
    try:
        with open(path, "r", encoding="utf-8") as f:
            patterns = json.load(f)
        count = 0
        for p in patterns:
            repo.upsert_global_pattern(
                pattern_type=p.get("pattern_type", ""),
                fixture_code=p.get("global_hint", {}).get("fixture_code", ""),
                description=p.get("description", ""),
                source_count=p.get("source_count", 0),
                examples=p.get("examples", []),
                global_hint=p.get("global_hint", {}),
                source_keys=p.get("source_keys", []),
            )
            count += 1
        logger.info("Migrated %d global patterns", count)
        return 1
    except Exception as e:
        logger.warning("Failed to migrate global patterns: %s", e)
        return 0
