"""Wraps the team agent functions with SSE event emission.

Mirrors the sequencing from orchestrator.py (lines 73-127) but emits
events to an asyncio.Queue instead of printing to stdout.
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


def run_pipeline(project: ProjectState, use_vision: bool = False, hints=None, is_reprocess: bool = False) -> dict:
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

    source = str(project.source_path)
    project_name = (
        project.source_path.stem
        if project.source_path.is_file()
        else project.source_path.name
    )
    work_dir = project.work_dir or f"output/team_work_{project_name}"
    output_path = project.output_path or f"output/inventory_{project.project_id}"

    project.status = "running"
    t0 = time.time()

    # --- Auto-load learnings from past corrections for this source ---
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
    # Merge: explicit feedback hints override learnings
    hints = merge_hints(learned_hints, hints)

    try:
        # --- Agent 1: Search ---
        if is_reprocess and (Path(work_dir) / "search_result.json").exists():
            # Cache hit — skip search agent on reprocessing
            _emit(project, "running", {"agent_id": 1, "agent_name": "Search Agent", "status": "running"})
            project.current_agent = 1
            import json as _json
            with open(Path(work_dir) / "search_result.json") as _f:
                search_result = _json.load(_f)
            _emit(project, "completed", {
                "agent_id": 1, "agent_name": "Search Agent", "status": "completed",
                "time": 0,
                "stats": {
                    "Pages": len(search_result.get("pages", [])),
                    "Plans found": len(search_result.get("plan_codes", [])),
                    "Schedules": len(search_result.get("schedule_codes", [])),
                },
                "flags": ["Cached — skipped (reprocessing)"],
            })
        else:
            _emit(project, "running", {"agent_id": 1, "agent_name": "Search Agent", "status": "running"})
            project.current_agent = 1
            t1 = time.time()
            search_result = run_search(source, work_dir)
            t_search = time.time() - t1
            _emit(project, "completed", {
                "agent_id": 1, "agent_name": "Search Agent", "status": "completed",
                "time": round(t_search, 1),
                "stats": {
                    "Pages": len(search_result.get("pages", [])),
                    "Plans found": len(search_result.get("plan_codes", [])),
                    "Schedules": len(search_result.get("schedule_codes", [])),
                },
            })

        # --- Agent 2: Schedule ---
        _emit(project, "running", {"agent_id": 2, "agent_name": "Schedule Agent", "status": "running"})
        project.current_agent = 2
        t2 = time.time()
        schedule_result = run_schedule(source, work_dir, hints=hints)
        t_schedule = time.time() - t2
        _emit(project, "completed", {
            "agent_id": 2, "agent_name": "Schedule Agent", "status": "completed",
            "time": round(t_schedule, 1),
            "stats": {
                "Types found": len(schedule_result.get("fixture_codes", [])),
                "Schedule pages": ", ".join(search_result.get("schedule_codes", [])),
            },
        })

        # --- Check if count/keynote agents should run ---
        has_plans = len(search_result.get("plan_codes", [])) > 0
        has_fixtures = len(schedule_result.get("fixture_codes", [])) > 0

        if has_plans and has_fixtures:
            # --- Agents 3 & 4: Count + Keynote (parallel) ---
            _emit(project, "running", {"agent_id": 3, "agent_name": "Count Agent", "status": "running"})
            _emit(project, "running", {"agent_id": 4, "agent_name": "Keynote Agent", "status": "running"})
            project.current_agent = 3
            t3 = time.time()
            count_result = None
            keynote_result = None

            with ThreadPoolExecutor(max_workers=2) as executor:
                count_future = executor.submit(run_count, source, work_dir, use_vision, hints)
                keynote_future = executor.submit(run_keynote, source, work_dir)

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
        elif has_plans and not has_fixtures:
            # Plans exist but no fixtures — skip count, still run keynotes
            # Write empty count result so QA agent can read it
            _write_empty_result(work_dir, "count_result.json", {"all_plan_counts": {}, "all_plan_positions": {}})
            _emit(project, "completed", {
                "agent_id": 3, "agent_name": "Count Agent", "status": "completed",
                "time": 0,
                "stats": {"Total fixtures": 0, "Plans scanned": 0},
                "flags": ["Skipped — no fixture codes found"],
            })
            _emit(project, "running", {"agent_id": 4, "agent_name": "Keynote Agent", "status": "running"})
            project.current_agent = 4
            t4 = time.time()
            keynote_result = run_keynote(source, work_dir)
            t_keynote = time.time() - t4
            _emit(project, "completed", {
                "agent_id": 4, "agent_name": "Keynote Agent", "status": "completed",
                "time": round(t_keynote, 1),
                "stats": {"Keynotes found": len(keynote_result.get("keynotes", []))},
            })
        else:
            # No plans — skip both count and keynote
            _write_empty_result(work_dir, "count_result.json", {"all_plan_counts": {}, "all_plan_positions": {}})
            _write_empty_result(work_dir, "keynote_result.json", {"keynotes": [], "all_keynote_counts": {}, "all_keynote_positions": {}})
            _emit(project, "completed", {
                "agent_id": 3, "agent_name": "Count Agent", "status": "completed",
                "time": 0,
                "stats": {"Total fixtures": 0, "Plans scanned": 0},
                "flags": ["Skipped — no lighting plans found"],
            })
            _emit(project, "completed", {
                "agent_id": 4, "agent_name": "Keynote Agent", "status": "completed",
                "time": 0,
                "stats": {"Keynotes found": 0},
                "flags": ["Skipped — no lighting plans found"],
            })

        # --- Agent 5: QA ---
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
        # Corrections are now baked into the result AND saved as persistent
        # learnings so future runs of the same source auto-apply them.
        from medina.api.feedback import FEEDBACK_DIR, load_project_feedback
        from medina.api.learnings import save_learnings
        fb = load_project_feedback(project.project_id)
        if fb and fb.corrections:
            save_learnings(project.source_path, fb.corrections)
            logger.info(
                "Promoted %d corrections to learnings for %s",
                len(fb.corrections), project_name,
            )
        fb_path = FEEDBACK_DIR / f"{project.project_id}.json"
        if fb_path.exists():
            fb_path.unlink()
            logger.info("Cleared project feedback for %s (promoted to learnings)",
                        project.project_id)

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
