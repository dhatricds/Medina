"""Wraps the team agent functions with SSE event emission.

Mirrors the sequencing from orchestrator.py (lines 73-127) but emits
events to an asyncio.Queue instead of printing to stdout.

Now also includes:
  - **Planning**: Pre-execution reasoning before each agent
  - **COVE**: Chain of Verification after each agent
  - **Runtime params**: Passes source_key and project_id for param lookup
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from medina.api.projects import ProjectState

logger = logging.getLogger(__name__)


def _write_empty_result(work_dir: str, filename: str, data: dict) -> None:
    """Write an empty result JSON file so downstream agents can read it."""
    out = Path(work_dir) / filename
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _emit(project: ProjectState, event_type: str, data: dict) -> None:
    """Put an SSE event onto the project's queue."""
    try:
        project.event_queue.put_nowait({
            "event": event_type,
            "data": data,
        })
    except Exception:
        logger.warning("Failed to emit event %s", event_type)


def _get_source_key(source_path: Path) -> str:
    """Get the source key for parameter/memory lookup."""
    try:
        from medina.api.learnings import _source_key
        return _source_key(source_path)
    except Exception:
        return ""


# ── Planning helpers ──────────────────────────────────────────────────

def _run_plan(
    project: ProjectState,
    agent_id: int,
    agent_name: str,
    plan_func,
    plan_args: tuple,
    source_key: str,
) -> dict | None:
    """Run planning for an agent and emit SSE events."""
    try:
        _emit(project, "planning", {"agent_id": agent_id, "agent_name": agent_name})

        from medina.planning.memory_retrieval import get_planning_context
        context = get_planning_context(agent_name.lower(), source_key, project.project_id)

        plan = plan_func(*plan_args, context)

        # Save plan to DB
        try:
            from medina.db import repositories as repo
            repo.save_agent_plan(
                project_id=project.project_id,
                agent_id=agent_id,
                agent_name=agent_name,
                plan_text=plan.get("strategy", ""),
                strategy=plan,
                expected_challenges=plan.get("challenges", []),
            )
        except Exception:
            pass

        _emit(project, "plan_ready", {
            "agent_id": agent_id,
            "agent_name": agent_name,
            "strategy": plan.get("strategy", ""),
            "approach": plan.get("approach", []),
            "challenges": plan.get("challenges", []),
        })
        return plan
    except Exception as e:
        logger.debug("Planning failed for %s: %s", agent_name, e)
        return None


# ── COVE helpers ──────────────────────────────────────────────────────

def _run_cove(
    project: ProjectState,
    agent_id: int,
    agent_name: str,
    verify_func,
    verify_args: tuple,
) -> dict | None:
    """Run COVE verification for an agent and emit SSE events."""
    try:
        _emit(project, "cove_running", {"agent_id": agent_id, "agent_name": agent_name})

        result = verify_func(*verify_args)

        # Save to DB
        try:
            from medina.db import repositories as repo
            repo.save_cove_result(
                project_id=project.project_id,
                agent_id=agent_id,
                agent_name=agent_name,
                passed=result.passed,
                confidence=result.confidence,
                issues=[{"check": i.check, "message": i.message, "severity": i.severity}
                        for i in result.issues],
                reasoning=result.reasoning,
            )
        except Exception:
            pass

        # Save to ChromaDB for pattern detection
        try:
            from medina.db.vector_store import add_document, COVE_FINDINGS_COLLECTION
            if result.issues:
                for i, issue in enumerate(result.issues):
                    add_document(
                        COVE_FINDINGS_COLLECTION,
                        f"cove_{project.project_id}_{agent_id}_{i}",
                        f"{agent_name}: {issue.message}",
                        {"agent_id": agent_id, "severity": issue.severity},
                    )
        except Exception:
            pass

        issues_data = [
            {"check": i.check, "message": i.message, "severity": i.severity}
            for i in result.issues
        ]

        _emit(project, "cove_completed", {
            "agent_id": agent_id,
            "agent_name": agent_name,
            "passed": result.passed,
            "confidence": result.confidence,
            "issues": issues_data,
            "corrections_count": len(result.corrections),
        })

        return {
            "passed": result.passed,
            "confidence": result.confidence,
            "should_retry": not result.passed and result.confidence < 0.7,
            "corrections": result.corrections,
        }
    except Exception as e:
        logger.debug("COVE failed for %s: %s", agent_name, e)
        return None


def _load_cached(work_dir: str, filename: str) -> dict:
    """Read a cached JSON result from work_dir. Raises FileNotFoundError if missing."""
    path = Path(work_dir) / filename
    if not path.exists():
        raise FileNotFoundError(f"Cached result not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _emit_skipped(project: ProjectState, agent_id: int, name: str, stats: dict, reason: str = "using cached results") -> None:
    """Emit a 'completed' SSE event for a skipped (cached) agent."""
    _emit(project, "completed", {
        "agent_id": agent_id,
        "agent_name": name,
        "status": "completed",
        "time": 0,
        "stats": stats,
        "flags": [f"Skipped — {reason}"],
    })


def run_pipeline(project: ProjectState, use_vision: bool = False, hints=None, is_reprocess: bool = False, target: frozenset[int] | None = None) -> dict:
    """Run the full pipeline with SSE event emission.

    This mirrors orchestrator.py run_team() but emits events instead of printing.

    Hints come from two sources:
    1. **Learnings** (global): Accumulated corrections from past runs of the
       same source file.  Loaded automatically on every run.
    2. **Feedback** (per-project): Corrections from the current session's
       "Re-run All" flow.  Passed explicitly via *hints*.

    Both are merged (feedback overrides learnings for conflicts).
    """
    from medina.team.run_search import run as run_search
    from medina.team.run_schedule import run as run_schedule
    from medina.team.run_count import run as run_count
    from medina.team.run_keynote import run as run_keynote
    from medina.team.run_qa import run as run_qa
    from medina.api.learnings import derive_learned_hints, merge_hints
    from medina.api.feedback import AGENT_SEARCH, AGENT_SCHEDULE, AGENT_COUNT, AGENT_KEYNOTE, AGENT_QA, TARGET_ALL

    if target is None:
        target = TARGET_ALL

    source = str(project.source_path)
    project_name = (
        project.source_path.stem
        if project.source_path.is_file()
        else project.source_path.name
    )
    work_dir = project.work_dir or f"output/team_work_{project_name}"
    output_path = project.output_path or f"output/inventory_{project.project_id}"
    source_key = _get_source_key(project.source_path)
    project_id = project.project_id

    project.status = "running"
    t0 = time.time()

    # --- Auto-load global patterns + learnings from past corrections ---
    from medina.api.patterns import get_global_hints
    global_hints = get_global_hints()
    if global_hints:
        logger.info(
            "Loaded global pattern hints: %d removed, %d extra fixtures",
            len(global_hints.removed_codes),
            len(global_hints.extra_fixtures),
        )

    learned_hints = derive_learned_hints(project.source_path)
    if learned_hints:
        logger.info(
            "Loaded learnings for %s: %d extra fixtures, %d removed, "
            "%d position overrides",
            project_name,
            len(learned_hints.extra_fixtures),
            len(learned_hints.removed_codes),
            len(learned_hints.rejected_positions) + len(learned_hints.added_positions),
        )

    # Merge: global → learned → explicit feedback (each overrides previous)
    merged_base = merge_hints(global_hints, learned_hints)
    hints = merge_hints(merged_base, hints)

    # Check runtime param for vision counting
    try:
        from medina.runtime_params import get_effective_params
        rt_params = get_effective_params(source_key, project_id)
        if rt_params.get("use_vision_counting", False):
            use_vision = True
    except Exception:
        pass

    # Check if page overrides or viewport splits require re-running search
    has_page_overrides = hints and hasattr(hints, "page_overrides") and hints.page_overrides
    has_viewport_splits = hints and hasattr(hints, "viewport_splits") and hints.viewport_splits

    # Import verification and planning functions
    try:
        from medina.cove.verifier import verify_search, verify_schedule, verify_counts, verify_keynotes
        cove_available = True
    except ImportError:
        cove_available = False

    try:
        from medina.planning.planner import plan_search, plan_schedule, plan_count, plan_keynote, plan_qa
        planning_available = True
    except ImportError:
        planning_available = False

    try:
        # --- Agent 1: Search ---
        can_cache_search = (
            AGENT_SEARCH not in target
            or (
                is_reprocess
                and not has_page_overrides
                and not has_viewport_splits
            )
        ) and (Path(work_dir) / "search_result.json").exists()

        if can_cache_search:
            _emit(project, "running", {"agent_id": 1, "agent_name": "Search Agent", "status": "running"})
            project.current_agent = 1
            search_result = _load_cached(work_dir, "search_result.json")
            _emit_skipped(project, 1, "Search Agent", {
                "Pages": len(search_result.get("pages", [])),
                "Plans found": len(search_result.get("plan_codes", [])),
                "Schedules": len(search_result.get("schedule_codes", [])),
            })
        else:
            # Planning
            if planning_available:
                _run_plan(project, 1, "Search Agent", plan_search, (source,), source_key)

            _emit(project, "running", {"agent_id": 1, "agent_name": "Search Agent", "status": "running"})
            project.current_agent = 1
            t1 = time.time()
            search_result = run_search(source, work_dir, hints=hints)
            t_search = time.time() - t1
            flags = []
            if has_page_overrides:
                flags.append(f"Page overrides applied: {list(hints.page_overrides.keys())}")
            _emit(project, "completed", {
                "agent_id": 1, "agent_name": "Search Agent", "status": "completed",
                "time": round(t_search, 1),
                "stats": {
                    "Pages": len(search_result.get("pages", [])),
                    "Plans found": len(search_result.get("plan_codes", [])),
                    "Schedules": len(search_result.get("schedule_codes", [])),
                },
                **({"flags": flags} if flags else {}),
            })

            # COVE verification for search
            if cove_available:
                cove_result = _run_cove(project, 1, "Search Agent",
                                        verify_search, (search_result,))
                if cove_result and cove_result.get("should_retry"):
                    logger.info("COVE flagged search agent for retry")
                    _emit(project, "cove_retry", {"agent_id": 1, "agent_name": "Search Agent", "retry_number": 1, "reason": "COVE confidence < 0.7"})
                    t1 = time.time()
                    search_result = run_search(source, work_dir, hints=hints)
                    t_search = time.time() - t1
                    _emit(project, "completed", {
                        "agent_id": 1, "agent_name": "Search Agent", "status": "completed",
                        "time": round(t_search, 1),
                        "stats": {
                            "Pages": len(search_result.get("pages", [])),
                            "Plans found": len(search_result.get("plan_codes", [])),
                            "Schedules": len(search_result.get("schedule_codes", [])),
                        },
                        "flags": ["Retried after COVE verification"],
                    })

        # --- Agent 2: Schedule ---
        can_cache_schedule = (
            AGENT_SCHEDULE not in target
            and (Path(work_dir) / "schedule_result.json").exists()
        )

        if can_cache_schedule:
            _emit(project, "running", {"agent_id": 2, "agent_name": "Schedule Agent", "status": "running"})
            project.current_agent = 2
            schedule_result = _load_cached(work_dir, "schedule_result.json")
            _emit_skipped(project, 2, "Schedule Agent", {
                "Types found": len(schedule_result.get("fixture_codes", [])),
                "Schedule pages": ", ".join(search_result.get("schedule_codes", [])),
            })
        else:
            if planning_available:
                _run_plan(project, 2, "Schedule Agent", plan_schedule, (search_result,), source_key)

            _emit(project, "running", {"agent_id": 2, "agent_name": "Schedule Agent", "status": "running"})
            project.current_agent = 2
            t2 = time.time()
            schedule_result = run_schedule(source, work_dir, hints=hints, source_key=source_key, project_id=project_id)
            t_schedule = time.time() - t2
            _emit(project, "completed", {
                "agent_id": 2, "agent_name": "Schedule Agent", "status": "completed",
                "time": round(t_schedule, 1),
                "stats": {
                    "Types found": len(schedule_result.get("fixture_codes", [])),
                    "Schedule pages": ", ".join(search_result.get("schedule_codes", [])),
                },
            })

            # COVE for schedule
            if cove_available:
                cove_result = _run_cove(project, 2, "Schedule Agent",
                                        verify_schedule, (schedule_result, search_result))
                if cove_result and cove_result.get("should_retry"):
                    logger.info("COVE flagged schedule agent for retry")
                    _emit(project, "cove_retry", {"agent_id": 2, "agent_name": "Schedule Agent", "retry_number": 1, "reason": "COVE confidence < 0.7"})
                    t2 = time.time()
                    schedule_result = run_schedule(source, work_dir, hints=hints, source_key=source_key, project_id=project_id)
                    t_schedule = time.time() - t2
                    _emit(project, "completed", {
                        "agent_id": 2, "agent_name": "Schedule Agent", "status": "completed",
                        "time": round(t_schedule, 1),
                        "stats": {
                            "Types found": len(schedule_result.get("fixture_codes", [])),
                            "Schedule pages": ", ".join(search_result.get("schedule_codes", [])),
                        },
                        "flags": ["Retried after COVE verification"],
                    })

        # --- Check if count/keynote agents should run ---
        has_plans = len(search_result.get("plan_codes", [])) > 0
        has_fixtures = len(schedule_result.get("fixture_codes", [])) > 0

        # Determine per-agent run vs cache
        run_count_agent = has_plans and has_fixtures and AGENT_COUNT in target
        run_keynote_agent = has_plans and AGENT_KEYNOTE in target

        # Try to load cached results for agents we can skip
        count_result = None
        keynote_result = None

        if not run_count_agent:
            try:
                count_result = _load_cached(work_dir, "count_result.json")
            except FileNotFoundError:
                if has_plans and has_fixtures:
                    run_count_agent = True  # Cache missing, must run
        if not run_keynote_agent:
            try:
                keynote_result = _load_cached(work_dir, "keynote_result.json")
            except FileNotFoundError:
                if has_plans:
                    run_keynote_agent = True  # Cache missing, must run

        if run_count_agent or run_keynote_agent:
            # Planning for agents that will run
            if planning_available and run_count_agent:
                _run_plan(project, 3, "Count Agent", plan_count, (search_result, schedule_result), source_key)
            if planning_available and run_keynote_agent:
                _run_plan(project, 4, "Keynote Agent", plan_keynote, (search_result,), source_key)

            # Emit running for agents that will execute
            if run_count_agent:
                _emit(project, "running", {"agent_id": 3, "agent_name": "Count Agent", "status": "running"})
            if run_keynote_agent:
                _emit(project, "running", {"agent_id": 4, "agent_name": "Keynote Agent", "status": "running"})
            project.current_agent = 3 if run_count_agent else 4
            t3 = time.time()

            # Force vision when recounting on reprocess
            count_vision = use_vision or (is_reprocess and run_count_agent)

            if run_count_agent and run_keynote_agent:
                # Both need to run — parallel
                with ThreadPoolExecutor(max_workers=2) as executor:
                    count_future = executor.submit(run_count, source, work_dir, count_vision, hints, source_key=source_key, project_id=project_id)
                    keynote_future = executor.submit(run_keynote, source, work_dir, source_key=source_key, project_id=project_id, hints=hints)
                    for future in as_completed([count_future, keynote_future]):
                        result = future.result()
                        elapsed = time.time() - t3
                        if future is count_future:
                            count_result = result
                            _emit(project, "completed", {
                                "agent_id": 3, "agent_name": "Count Agent", "status": "completed",
                                "time": round(elapsed, 1),
                                "stats": {
                                    "Total fixtures": count_result.get("total_fixtures", 0),
                                    "Plans scanned": len(count_result.get("plan_counts", {})),
                                },
                            })
                        else:
                            keynote_result = result
                            _emit(project, "completed", {
                                "agent_id": 4, "agent_name": "Keynote Agent", "status": "completed",
                                "time": round(elapsed, 1),
                                "stats": {
                                    "Keynotes found": len(keynote_result.get("keynotes", [])),
                                },
                            })
            elif run_count_agent:
                # Only count runs, keynote cached
                count_result = run_count(source, work_dir, count_vision, hints, source_key=source_key, project_id=project_id)
                elapsed = time.time() - t3
                _emit(project, "completed", {
                    "agent_id": 3, "agent_name": "Count Agent", "status": "completed",
                    "time": round(elapsed, 1),
                    "stats": {
                        "Total fixtures": count_result.get("total_fixtures", 0),
                        "Plans scanned": len(count_result.get("plan_counts", {})),
                    },
                })
            else:
                # Only keynote runs, count cached
                keynote_result = run_keynote(source, work_dir, source_key=source_key, project_id=project_id, hints=hints)
                elapsed = time.time() - t3
                _emit(project, "completed", {
                    "agent_id": 4, "agent_name": "Keynote Agent", "status": "completed",
                    "time": round(elapsed, 1),
                    "stats": {
                        "Keynotes found": len(keynote_result.get("keynotes", [])),
                    },
                })

            # COVE for agents that ran
            if cove_available and run_count_agent and count_result:
                _run_cove(project, 3, "Count Agent",
                          verify_counts, (count_result, schedule_result))
            if cove_available and run_keynote_agent and keynote_result:
                _run_cove(project, 4, "Keynote Agent",
                          verify_keynotes, (keynote_result,))

        # Emit skipped events for agents that used cache
        if not run_count_agent:
            if count_result is not None:
                _emit_skipped(project, 3, "Count Agent", {
                    "Total fixtures": count_result.get("total_fixtures", 0),
                    "Plans scanned": len(count_result.get("plan_counts", {})),
                })
            elif not has_plans or not has_fixtures:
                _write_empty_result(work_dir, "count_result.json", {"all_plan_counts": {}, "all_plan_positions": {}})
                skip_reason = "no fixture codes found" if not has_fixtures else "no lighting plans found"
                _emit_skipped(project, 3, "Count Agent",
                              {"Total fixtures": 0, "Plans scanned": 0}, skip_reason)
        if not run_keynote_agent:
            if keynote_result is not None:
                _emit_skipped(project, 4, "Keynote Agent", {
                    "Keynotes found": len(keynote_result.get("keynotes", [])),
                })
            elif not has_plans:
                _write_empty_result(work_dir, "keynote_result.json", {"keynotes": [], "all_keynote_counts": {}, "all_keynote_positions": {}})
                _emit_skipped(project, 4, "Keynote Agent",
                              {"Keynotes found": 0}, "no lighting plans found")

        # --- Agent 5: QA ---
        if planning_available:
            _run_plan(project, 5, "QA Agent", plan_qa, (), source_key)

        _emit(project, "running", {"agent_id": 5, "agent_name": "QA Agent", "status": "running"})
        project.current_agent = 5
        t5 = time.time()
        qa_result = run_qa(source, work_dir, output_path)
        t_qa = time.time() - t5
        _emit(project, "completed", {
            "agent_id": 5, "agent_name": "QA Agent", "status": "completed",
            "time": round(t_qa, 1),
            "stats": {
                "Confidence": f"{qa_result.get('qa_confidence', 0):.0%}",
                "Warnings": len(qa_result.get("warnings", [])),
            },
        })

        total_time = time.time() - t0

        # Load the generated JSON result
        json_path = Path(f"{output_path}.json")
        if json_path.exists():
            with open(json_path) as f:
                project.result_data = json.load(f)

        project.output_path = output_path
        project.status = "completed"

        # Promote feedback to global learnings and clear project feedback.
        from medina.api.feedback import FEEDBACK_DIR, load_project_feedback, clear_project_feedback
        from medina.api.learnings import save_learnings
        fb = load_project_feedback(project.project_id)
        if fb and fb.corrections:
            save_learnings(project.source_path, fb.corrections)
            logger.info(
                "Promoted %d corrections to learnings for %s",
                len(fb.corrections), project_name,
            )
            # Check for new global patterns crossing threshold
            from medina.api.patterns import record_correction_pattern
            from medina.api.learnings import _source_key
            src_key = _source_key(project.source_path)
            new_patterns = record_correction_pattern(src_key, fb.corrections)
            if new_patterns:
                logger.info(
                    "[PIPELINE] %d new global patterns detected",
                    len(new_patterns),
                )
                for p in new_patterns:
                    logger.info(
                        "  Pattern: %s (%d sources)",
                        p.description, p.source_count,
                    )
        # Clear project feedback (use new helper that cleans both DB and file)
        clear_project_feedback(project.project_id)

        _emit(project, "pipeline_complete", {
            "total_time": round(total_time, 1),
            "fixture_count": qa_result.get("fixture_count", 0),
            "total_fixtures": qa_result.get("total_fixtures", 0),
            "qa_confidence": qa_result.get("qa_confidence", 0),
            "qa_passed": qa_result.get("qa_passed", False),
        })

        return qa_result

    except Exception as e:
        logger.exception("Pipeline failed: %s", e)
        project.status = "error"
        project.error = str(e)
        _emit(project, "pipeline_error", {
            "error": str(e),
            "agent_id": project.current_agent,
        })
        raise
