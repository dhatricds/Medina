"""Memory context retrieval for agent planning.

Queries SQLite (learnings, global_patterns, runtime_params) and ChromaDB
(similar corrections) to build a context dict that planners use to decide
strategy before each agent runs.

All DB access is wrapped in try/except so the planning module degrades
gracefully when the database is unavailable.
"""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


def get_planning_context(
    agent_name: str,
    source_key: str,
    project_id: str = "",
) -> dict[str, Any]:
    """Retrieve memory context relevant to an agent's pre-execution plan.

    Queries four data sources:
    1. **SQLite learnings** — past corrections for this source_key.
    2. **SQLite global_patterns** — recurring patterns across all sources.
    3. **ChromaDB corrections** — semantically similar corrections from
       other sources (useful for new PDFs that resemble past projects).
    4. **SQLite runtime_params** — custom parameters scoped to this
       source/project.

    Args:
        agent_name: The agent requesting context (e.g. "search", "schedule").
        source_key: Stable key derived from the source file path.
        project_id: Optional project identifier for project-scoped params.

    Returns:
        Dict with keys ``past_corrections``, ``global_patterns``,
        ``similar_corrections``, ``runtime_params``.  Each value is a
        (possibly empty) list or dict — never None.
    """
    context: dict[str, Any] = {
        "past_corrections": [],
        "global_patterns": [],
        "similar_corrections": [],
        "runtime_params": {},
    }

    # ── 1. Past corrections from learnings table ────────────────────────
    try:
        from medina.db import repositories as repo

        learning = repo.get_learning(source_key)
        if learning and learning.get("corrections"):
            corrections = learning["corrections"]
            # Filter to corrections relevant to this agent
            context["past_corrections"] = _filter_for_agent(
                agent_name, corrections,
            )
    except Exception as exc:
        logger.debug(
            "Could not load learnings for %s (source_key=%s): %s",
            agent_name, source_key, exc,
        )

    # ── 2. Global patterns ──────────────────────────────────────────────
    try:
        from medina.db import repositories as repo

        rows = repo.get_all_global_patterns()
        if rows:
            context["global_patterns"] = [
                {
                    "pattern_type": r.get("pattern_type", ""),
                    "fixture_code": r.get("fixture_code", ""),
                    "description": r.get("description", ""),
                    "source_count": r.get("source_count", 0),
                    "global_hint": r.get("global_hint", {}),
                }
                for r in rows
            ]
    except Exception as exc:
        logger.debug(
            "Could not load global patterns for %s: %s", agent_name, exc,
        )

    # ── 3. Similar corrections via ChromaDB ─────────────────────────────
    try:
        from medina.db.vector_store import query_similar, CORRECTIONS_COLLECTION

        # Build a query string that captures the agent's focus area
        query_text = _build_similarity_query(agent_name, source_key)
        if query_text:
            results = query_similar(
                CORRECTIONS_COLLECTION,
                query_text,
                n_results=5,
            )
            context["similar_corrections"] = [
                {
                    "id": r.get("id", ""),
                    "text": r.get("document", ""),
                    "metadata": r.get("metadata", {}),
                    "distance": r.get("distance", 0.0),
                }
                for r in results
                # Exclude corrections from the same source (already in
                # past_corrections) to surface cross-source patterns.
                if r.get("metadata", {}).get("source_key") != source_key
            ]
    except Exception as exc:
        logger.debug(
            "Could not query similar corrections for %s: %s",
            agent_name, exc,
        )

    # ── 4. Runtime parameters ───────────────────────────────────────────
    try:
        from medina.db import repositories as repo

        # Merge global params with source-scoped and project-scoped ones.
        # More specific scopes override broader ones.
        params: dict[str, Any] = {}

        global_params = repo.get_params(scope="global", scope_key="")
        params.update(global_params)

        if source_key:
            source_params = repo.get_params(
                scope="source", scope_key=source_key,
            )
            params.update(source_params)

        if project_id:
            project_params = repo.get_params(
                scope="project", scope_key=project_id,
            )
            params.update(project_params)

        context["runtime_params"] = params
    except Exception as exc:
        logger.debug(
            "Could not load runtime params for %s: %s", agent_name, exc,
        )

    return context


# ── Helpers ─────────────────────────────────────────────────────────────


def _filter_for_agent(
    agent_name: str,
    corrections: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return only corrections relevant to a specific agent.

    Different agents care about different correction types:
    - search: reclassify_page, split_page
    - schedule: add, remove, update_spec
    - count: count_override (with position data)
    - keynote: count_override for keynotes (no fixture data)
    - qa: all corrections (full picture)
    """
    agent_actions: dict[str, set[str]] = {
        "search": {"reclassify_page", "split_page"},
        "schedule": {"add", "remove", "update_spec"},
        "count": {"count_override"},
        "keynote": {"count_override"},
        "qa": set(),  # empty = accept all
    }

    accepted_actions = agent_actions.get(agent_name)
    if accepted_actions is None:
        # Unknown agent — return everything
        return corrections

    if not accepted_actions:
        # QA agent: wants all corrections
        return corrections

    return [
        c for c in corrections
        if c.get("action") in accepted_actions
    ]


def _build_similarity_query(agent_name: str, source_key: str) -> str:
    """Build a ChromaDB query string tailored to the agent's concerns.

    The query is a natural-language description of what kinds of past
    corrections would be useful for this agent to know about.
    """
    queries: dict[str, str] = {
        "search": (
            "page classification errors, wrong page type, "
            "reclassify page, lighting plan misidentified"
        ),
        "schedule": (
            "schedule extraction errors, missing fixture type, "
            "wrong fixture code, extra fixture, VLM misread"
        ),
        "count": (
            "fixture count correction, overcounting, undercounting, "
            "short code ambiguity, vision counting"
        ),
        "keynote": (
            "keynote count correction, keynote missed, "
            "keynote false positive, geometric detection"
        ),
        "qa": (
            "QA confidence issue, validation failure, "
            "count mismatch, low confidence score"
        ),
    }
    return queries.get(agent_name, "")
