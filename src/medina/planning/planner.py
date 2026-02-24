"""Deterministic planning functions for each pipeline agent.

Each function produces a plan dict with:
- ``strategy``: one-line description of the chosen approach
- ``approach``: ordered list of concrete steps the agent will take
- ``challenges``: anticipated issues based on memory context

Plans are persisted to the SQLite ``agent_plans`` table so the
orchestrator and UI can display what each agent intends to do before
it runs.  All DB writes are wrapped in try/except — planning never
blocks execution.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Agent numeric IDs (must match orchestrator_wrapper.py)
_AGENT_IDS: dict[str, int] = {
    "search": 1,
    "schedule": 2,
    "count": 3,
    "keynote": 4,
    "qa": 5,
}


# ════════════════════════════════════════════════════════════════════════
#  Persistence helper
# ════════════════════════════════════════════════════════════════════════


def _save_plan(
    project_id: str,
    agent_name: str,
    plan: dict[str, Any],
) -> None:
    """Persist a plan to the DB.  Silent on failure."""
    try:
        from medina.db import repositories as repo

        agent_id = _AGENT_IDS.get(agent_name, 0)
        # Build a readable plan_text from the structured plan
        lines = [f"Strategy: {plan.get('strategy', '')}"]
        for i, step in enumerate(plan.get("approach", []), 1):
            lines.append(f"  {i}. {step}")
        if plan.get("challenges"):
            lines.append("Challenges:")
            for ch in plan["challenges"]:
                lines.append(f"  - {ch}")
        plan_text = "\n".join(lines)

        repo.save_agent_plan(
            project_id=project_id,
            agent_id=agent_id,
            agent_name=agent_name,
            plan_text=plan_text,
            strategy=plan,
            expected_challenges=plan.get("challenges", []),
        )
    except Exception as exc:
        logger.debug("Failed to save plan for %s: %s", agent_name, exc)


# ════════════════════════════════════════════════════════════════════════
#  Context extraction helpers
# ════════════════════════════════════════════════════════════════════════


def _has_page_overrides(context: dict[str, Any]) -> list[dict]:
    """Return page-override corrections from past corrections."""
    return [
        c for c in context.get("past_corrections", [])
        if c.get("action") in ("reclassify_page", "split_page")
    ]


def _has_removed_codes(context: dict[str, Any]) -> list[str]:
    """Return fixture codes that should be removed per past corrections."""
    return [
        c.get("fixture_code", "")
        for c in context.get("past_corrections", [])
        if c.get("action") == "remove" and c.get("fixture_code")
    ]


def _has_extra_fixtures(context: dict[str, Any]) -> list[str]:
    """Return fixture codes that should be added per past corrections."""
    return [
        c.get("fixture_code", "")
        for c in context.get("past_corrections", [])
        if c.get("action") == "add" and c.get("fixture_code")
    ]


def _has_count_overrides(context: dict[str, Any]) -> list[dict]:
    """Return count override corrections from past corrections."""
    return [
        c for c in context.get("past_corrections", [])
        if c.get("action") == "count_override"
    ]


def _has_spec_patches(context: dict[str, Any]) -> list[dict]:
    """Return spec update corrections from past corrections."""
    return [
        c for c in context.get("past_corrections", [])
        if c.get("action") == "update_spec"
    ]


def _global_warnings(context: dict[str, Any]) -> list[str]:
    """Extract warning-type global patterns."""
    warnings = []
    for gp in context.get("global_patterns", []):
        hint = gp.get("global_hint", {})
        if hint.get("action") == "warn":
            warnings.append(hint.get("warning", gp.get("description", "")))
    return warnings


def _short_codes(fixture_codes: list[str]) -> list[str]:
    """Return fixture codes that are 1 or 2 characters (ambiguity risk)."""
    return [c for c in fixture_codes if len(c) <= 2]


# ════════════════════════════════════════════════════════════════════════
#  Agent planners
# ════════════════════════════════════════════════════════════════════════


def plan_search(
    source_path: str,
    context: dict[str, Any],
    project_id: str = "",
) -> dict[str, Any]:
    """Plan the search agent's execution strategy.

    Considers:
    - Whether the source is a folder of PDFs or a single file.
    - Whether learnings contain page overrides that require reclassification.
    - Whether viewport splits need auto-detection or user hints.
    """
    path = Path(source_path)
    is_folder = path.is_dir()
    page_overrides = _has_page_overrides(context)
    warnings = _global_warnings(context)

    # Determine strategy
    if is_folder:
        strategy = (
            "Folder input: load individual PDFs, deduplicate by title-block "
            "sheet code, discover sheet index from cover sheet"
        )
    else:
        strategy = (
            "Single PDF input: load all pages, discover sheet index from "
            "first/legend page"
        )

    approach = [
        f"Load {'folder of PDFs' if is_folder else 'multi-page PDF'} "
        f"from {path.name}",
        "Extract sheet index from cover/legend/symbols page",
        "Classify all pages using 4-priority chain "
        "(sheet index > title block > prefix > content scan)",
    ]

    if is_folder:
        approach.insert(
            1,
            "Deduplicate by title-block sheet code (keep latest revision)",
        )

    challenges: list[str] = []

    if page_overrides:
        n = len(page_overrides)
        codes = [c.get("fixture_code", "") for c in page_overrides]
        approach.append(
            f"Apply {n} page override(s) from learnings: {codes}"
        )
        challenges.append(
            f"Page overrides present for {codes} — cache will be "
            "invalidated and search must re-run from scratch"
        )

    # Check for viewport split hints
    split_corrections = [
        c for c in context.get("past_corrections", [])
        if c.get("action") == "split_page"
    ]
    if split_corrections:
        split_codes = [c.get("fixture_code", "") for c in split_corrections]
        approach.append(
            f"Apply viewport splits for: {split_codes}"
        )
        challenges.append(
            f"Viewport splits required for {split_codes} — pages will "
            "be split into virtual sub-pages for independent counting"
        )
    else:
        approach.append(
            "Auto-detect multi-viewport pages (side-by-side lighting plans)"
        )

    if warnings:
        for w in warnings:
            challenges.append(f"Global pattern: {w}")

    # Check similar corrections for classification issues
    similar = context.get("similar_corrections", [])
    if similar:
        classification_issues = [
            s for s in similar
            if "classif" in s.get("text", "").lower()
            or "reclassify" in s.get("text", "").lower()
        ]
        if classification_issues:
            challenges.append(
                f"Similar sources had {len(classification_issues)} "
                "classification correction(s) — extra attention to "
                "page type assignment"
            )

    plan = {
        "strategy": strategy,
        "approach": approach,
        "challenges": challenges,
    }
    _save_plan(project_id, "search", plan)
    return plan


def plan_schedule(
    search_result: dict[str, Any],
    context: dict[str, Any],
    project_id: str = "",
) -> dict[str, Any]:
    """Plan the schedule agent's execution strategy.

    Considers:
    - Number and identity of schedule pages found.
    - Whether combo pages (schedule embedded in plan) need checking.
    - Whether learnings have extra/removed fixture codes.
    - VLM fallback likelihood based on past corrections.
    """
    schedule_codes = search_result.get("schedule_codes", [])
    plan_codes = search_result.get("plan_codes", [])
    removed = _has_removed_codes(context)
    extra = _has_extra_fixtures(context)
    spec_patches = _has_spec_patches(context)
    warnings = _global_warnings(context)

    n_schedules = len(schedule_codes)

    if n_schedules == 0:
        strategy = (
            "No dedicated schedule pages found — will check plan pages "
            "for embedded (combo) schedule tables"
        )
    elif n_schedules == 1:
        strategy = (
            f"Single schedule page {schedule_codes[0]} — extract with "
            "pdfplumber, VLM fallback if no fixtures found"
        )
    else:
        strategy = (
            f"{n_schedules} schedule pages ({', '.join(schedule_codes)}) — "
            "extract from each, merge fixture records"
        )

    approach = []
    if schedule_codes:
        approach.append(
            f"Extract tables from schedule page(s): {', '.join(schedule_codes)}"
        )
        approach.append(
            "Map column headers to fixture spec fields "
            "(code, description, voltage, mounting, etc.)"
        )
        approach.append(
            "Validate extracted fixtures — reject panel schedules and "
            "header rows"
        )
        approach.append(
            "If pdfplumber finds 0 fixtures, trigger VLM fallback "
            "(render at 150 DPI, send to Claude Vision)"
        )
    if plan_codes:
        approach.append(
            f"Check plan page(s) {', '.join(plan_codes)} for embedded "
            "combo schedule tables"
        )

    challenges: list[str] = []

    if removed:
        approach.append(
            f"Filter out learned-removed fixture codes: {removed}"
        )
        challenges.append(
            f"Learnings indicate {len(removed)} fixture code(s) should "
            f"be removed: {removed}"
        )

    if extra:
        approach.append(
            f"Append learned-extra fixture types: {extra}"
        )
        challenges.append(
            f"Learnings indicate {len(extra)} fixture type(s) were "
            f"missed previously: {extra}"
        )

    if spec_patches:
        codes = [p.get("fixture_code", "") for p in spec_patches]
        approach.append(
            f"Apply spec patches from learnings for: {codes}"
        )

    # Check if VLM was needed before for this source
    vlm_corrections = [
        c for c in context.get("past_corrections", [])
        if c.get("reason") == "vlm_misread"
    ]
    if vlm_corrections:
        challenges.append(
            f"Past VLM misreads detected ({len(vlm_corrections)}) — "
            "VLM results will need extra validation"
        )

    # Check similar corrections for schedule issues
    similar = context.get("similar_corrections", [])
    schedule_similar = [
        s for s in similar
        if any(
            kw in s.get("text", "").lower()
            for kw in ("schedule", "fixture", "missing", "extra", "vlm")
        )
    ]
    if schedule_similar:
        challenges.append(
            f"Similar sources had {len(schedule_similar)} schedule-related "
            "correction(s) — common issues may recur"
        )

    if warnings:
        for w in warnings:
            challenges.append(f"Global pattern: {w}")

    if n_schedules == 0 and not plan_codes:
        challenges.append(
            "No schedule pages and no plan pages — extraction will "
            "produce 0 fixture types"
        )

    plan = {
        "strategy": strategy,
        "approach": approach,
        "challenges": challenges,
    }
    _save_plan(project_id, "schedule", plan)
    return plan


def plan_count(
    search_result: dict[str, Any],
    schedule_result: dict[str, Any],
    context: dict[str, Any],
    project_id: str = "",
) -> dict[str, Any]:
    """Plan the count agent's execution strategy.

    Considers:
    - Number of lighting plan pages to scan.
    - Fixture code characteristics (short codes = ambiguity risk).
    - Whether vision counting should be used.
    - Count overrides from learnings.
    """
    plan_codes = search_result.get("plan_codes", [])
    fixture_codes = schedule_result.get("fixture_codes", [])
    count_overrides = _has_count_overrides(context)
    warnings = _global_warnings(context)

    n_plans = len(plan_codes)
    n_fixtures = len(fixture_codes)
    short = _short_codes(fixture_codes)

    if n_plans == 0:
        strategy = "No lighting plans found — counting will be skipped"
    elif n_fixtures == 0:
        strategy = (
            f"{n_plans} plan(s) found but no fixture codes — "
            "counting will be skipped"
        )
    elif n_plans == 1:
        strategy = (
            f"Single plan {plan_codes[0]} with {n_fixtures} fixture type(s) "
            "— text-based character-level counting"
        )
    else:
        strategy = (
            f"{n_plans} plans ({', '.join(plan_codes)}) with {n_fixtures} "
            "fixture type(s) — count each plan independently"
        )

    approach: list[str] = []

    if n_plans > 0 and n_fixtures > 0:
        approach.append(
            f"Scan {n_plans} lighting plan page(s): "
            f"{', '.join(plan_codes)}"
        )
        approach.append(
            f"Count {n_fixtures} fixture code(s) using character-level "
            "text extraction with modal font-size filtering"
        )
        approach.append(
            "Exclude title block (rightmost 25%), borders, and "
            "notes sections from counting"
        )
        if short:
            approach.append(
                f"Apply tighter filtering for short codes ({', '.join(short)}): "
                "isolation check, font tolerance +/-15%, "
                "70pt spatial dedup"
            )

        # Check for combo pages (schedule table on plan page)
        approach.append(
            "Detect and exclude any embedded schedule tables on plan pages"
        )

        # Check for viewport pages
        viewport_map = search_result.get("viewport_map", {})
        if viewport_map:
            viewport_keys = list(viewport_map.keys())
            approach.append(
                f"Viewport-aware counting for split pages: {viewport_keys} "
                "— clip characters to viewport bbox"
            )

    challenges: list[str] = []

    if short:
        challenges.append(
            f"Short fixture codes ({', '.join(short)}) are prone to "
            "ambiguity with room labels, circuit IDs, and page references"
        )

    if count_overrides:
        codes = list({c.get("fixture_code", "") for c in count_overrides})
        approach.append(
            f"Apply {len(count_overrides)} count override(s) from "
            f"learnings for: {codes}"
        )
        challenges.append(
            f"Manual count overrides exist for {codes} — these will "
            "replace text-counted values"
        )

    # Check runtime params for vision counting
    params = context.get("runtime_params", {})
    use_vision = params.get("use_vision_counting", False)
    if use_vision:
        approach.append(
            "Vision-based counting enabled — will render plans at 150 DPI "
            "and send to Claude Vision API for cross-verification"
        )
        challenges.append(
            "Vision counting adds latency and API cost — used as "
            "secondary verification"
        )

    # Global pattern warnings
    if warnings:
        for w in warnings:
            challenges.append(f"Global pattern: {w}")

    # Check for overcount/undercount patterns in global patterns
    for gp in context.get("global_patterns", []):
        pt = gp.get("pattern_type", "")
        fc = gp.get("fixture_code", "")
        if fc in fixture_codes:
            if pt == "systematic_overcount":
                challenges.append(
                    f"Global pattern: '{fc}' is systematically overcounted "
                    f"across {gp.get('source_count', 0)} sources"
                )
            elif pt == "systematic_undercount":
                challenges.append(
                    f"Global pattern: '{fc}' is systematically undercounted "
                    f"across {gp.get('source_count', 0)} sources"
                )
            elif pt == "short_code_ambiguity":
                challenges.append(
                    f"Global pattern: short code '{fc}' matches non-fixture "
                    f"text across {gp.get('source_count', 0)} sources"
                )

    # Similar corrections from other sources
    similar = context.get("similar_corrections", [])
    count_similar = [
        s for s in similar
        if any(
            kw in s.get("text", "").lower()
            for kw in ("count", "overcount", "undercount", "short code")
        )
    ]
    if count_similar:
        challenges.append(
            f"Similar sources had {len(count_similar)} counting "
            "correction(s) — watch for recurring issues"
        )

    plan = {
        "strategy": strategy,
        "approach": approach,
        "challenges": challenges,
    }
    _save_plan(project_id, "count", plan)
    return plan


def plan_keynote(
    search_result: dict[str, Any],
    context: dict[str, Any],
    project_id: str = "",
) -> dict[str, Any]:
    """Plan the keynote agent's execution strategy.

    Considers:
    - Number of lighting plans to scan for keynotes.
    - Past keynote corrections (indicates detection issues).
    - Whether VLM fallback will likely be needed.
    """
    plan_codes = search_result.get("plan_codes", [])
    past_corrections = context.get("past_corrections", [])
    warnings = _global_warnings(context)

    n_plans = len(plan_codes)

    if n_plans == 0:
        strategy = "No lighting plans found — keynote extraction will be skipped"
    elif n_plans == 1:
        strategy = (
            f"Single plan {plan_codes[0]} — extract keynote text from "
            "notes panel, count via geometric shape detection"
        )
    else:
        strategy = (
            f"{n_plans} plans ({', '.join(plan_codes)}) — extract keynotes "
            "per plan, detect diamond/hexagon-enclosed numbers"
        )

    approach: list[str] = []

    if n_plans > 0:
        approach.append(
            f"Scan {n_plans} plan page(s) for KEY NOTES / KEYED NOTES / "
            "KEYED SHEET NOTES sections"
        )
        approach.append(
            "Extract keynote text entries (numbered items in notes panel)"
        )
        approach.append(
            "Count keynote occurrences using geometric shape detection: "
            "find numbers enclosed by line endpoints in 4 quadrants "
            "(TR, BR, BL, TL)"
        )
        approach.append(
            "Apply modal font_h filtering to eliminate false positives "
            "from circuit numbers, dimensions, and room labels"
        )
        approach.append(
            "If all counts are zero or any count exceeds 10, "
            "trigger VLM fallback (dual-crop: legend + drawing)"
        )

        # Viewport-aware keynote processing
        viewport_map = search_result.get("viewport_map", {})
        if viewport_map:
            approach.append(
                "Viewport sibling processing: extract keynote TEXT once "
                "from full page, COUNT per viewport bbox"
            )

    challenges: list[str] = []

    # Past keynote corrections suggest detection issues
    if past_corrections:
        challenges.append(
            f"{len(past_corrections)} past keynote correction(s) found — "
            "detection may need VLM verification"
        )
        # Check if corrections indicate consistent VLM was needed
        high_count_corrections = [
            c for c in past_corrections
            if c.get("fixture_data", {}).get("corrected", 0) !=
               c.get("fixture_data", {}).get("original", 0)
        ]
        if high_count_corrections:
            challenges.append(
                "Past corrections show count mismatches — geometric "
                "detection may produce inflated counts on dense pages"
            )

    # Similar corrections
    similar = context.get("similar_corrections", [])
    keynote_similar = [
        s for s in similar
        if any(
            kw in s.get("text", "").lower()
            for kw in ("keynote", "key note", "geometric", "diamond")
        )
    ]
    if keynote_similar:
        challenges.append(
            f"Similar sources had {len(keynote_similar)} keynote "
            "correction(s)"
        )

    if warnings:
        for w in warnings:
            challenges.append(f"Global pattern: {w}")

    plan = {
        "strategy": strategy,
        "approach": approach,
        "challenges": challenges,
    }
    _save_plan(project_id, "keynote", plan)
    return plan


def plan_qa(
    context: dict[str, Any],
    project_id: str = "",
) -> dict[str, Any]:
    """Plan the QA agent's execution strategy.

    The QA agent reviews all previous agents' work, so its plan is a
    summary of what to expect and validate.
    """
    all_corrections = context.get("past_corrections", [])
    global_patterns = context.get("global_patterns", [])
    warnings = _global_warnings(context)

    strategy = (
        "Review all agent outputs, compute confidence scores, "
        "cross-check counts, and generate Excel + JSON output"
    )

    approach = [
        "Load search, schedule, count, and keynote results from work directory",
        "Merge fixture specs with per-plan counts",
        "Run cross-checks: schedule completeness, zero-count fixtures, "
        "fixture code ambiguity, keynote consistency",
        "Compute per-stage and overall confidence scores "
        "(must exceed 95% to pass)",
        "Generate QA report with flags and recommendations",
        "Produce Excel workbook (3 sheets: Fixtures, Keynotes, QA) "
        "and JSON output for frontend",
    ]

    challenges: list[str] = []

    if all_corrections:
        n_by_action: dict[str, int] = {}
        for c in all_corrections:
            action = c.get("action", "unknown")
            n_by_action[action] = n_by_action.get(action, 0) + 1
        summary_parts = [f"{n} {a}" for a, n in sorted(n_by_action.items())]
        challenges.append(
            f"Source has {len(all_corrections)} past correction(s) "
            f"({', '.join(summary_parts)}) — verify they were applied "
            "correctly by upstream agents"
        )

    if global_patterns:
        challenges.append(
            f"{len(global_patterns)} global pattern(s) active — "
            "check that pattern-driven hints improved accuracy"
        )

    if warnings:
        for w in warnings:
            challenges.append(f"Global pattern: {w}")

    # Similar corrections may indicate recurring QA issues
    similar = context.get("similar_corrections", [])
    if similar:
        challenges.append(
            f"{len(similar)} similar correction(s) from other sources — "
            "cross-source patterns may affect confidence"
        )

    plan = {
        "strategy": strategy,
        "approach": approach,
        "challenges": challenges,
    }
    _save_plan(project_id, "qa", plan)
    return plan
