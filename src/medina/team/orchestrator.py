"""Team Orchestrator: Run all 5 agents in the expert contractor workflow.

Coordinates the search, schedule, count, keynote, and QA agents,
running count and keynote in parallel since they are independent.

Usage:
    uv run python -m medina.team.orchestrator <source> [--output PATH]
        [--use-vision] [--work-dir DIR]

Examples:
    uv run python -m medina.team.orchestrator data/24031_15_Elec.pdf
    uv run python -m medina.team.orchestrator "data/Elk River Gym prints/"
    uv run python -m medina.team.orchestrator data/24031_15_Elec.pdf \\
        --output output/hcmc --use-vision
"""

from __future__ import annotations

import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("medina.team.orchestrator")


def run_team(
    source: str,
    output_path: str = "output/inventory",
    use_vision: bool = False,
    work_dir: str | None = None,
) -> dict:
    """Run the full expert contractor agent team workflow.

    Flow:
        search-agent (Stages 1-3)
            |
            v
        schedule-agent (Stage 4)
            |
            +---> count-agent (Stage 5a)  [parallel]
            +---> keynote-agent (Stage 5b) [parallel]
            |
            v
        qa-agent (Stages 6-7)
    """
    from medina.team.run_search import run as run_search
    from medina.team.run_schedule import run as run_schedule
    from medina.team.run_count import run as run_count
    from medina.team.run_keynote import run as run_keynote
    from medina.team.run_qa import run as run_qa

    source_path = Path(source)
    if work_dir is None:
        project_name = (
            source_path.stem if source_path.is_file() else source_path.name
        )
        work_dir = f"output/team_work_{project_name}"

    t0 = time.time()

    # --- Load learnings from past corrections for this source ---
    hints = None
    try:
        from medina.api.learnings import derive_learned_hints
        hints = derive_learned_hints(source_path)
        if hints:
            logger.info(
                "Loaded learnings: %d extra fixtures, %d removed, "
                "%d rejected positions, %d added positions",
                len(hints.extra_fixtures),
                len(hints.removed_codes),
                len(hints.rejected_positions),
                len(hints.added_positions),
            )
    except Exception as e:
        logger.warning("Failed to load learnings: %s", e)

    print("=" * 60)
    print("  EXPERT ELECTRICAL CONTRACTOR TEAM")
    print(f"  Project: {source_path.name}")
    if hints:
        print(f"  Learnings: {len(hints.extra_fixtures)} extra fixtures, "
              f"{len(hints.removed_codes)} removed codes")
    print("=" * 60)

    # --- Agent 1: Search (The Page Navigator) ---
    print("\n[1/5] SEARCH AGENT: Opening drawings, finding sheet index...")
    t1 = time.time()
    search_result = run_search(source, work_dir)
    t_search = time.time() - t1
    print(f"      Completed in {t_search:.1f}s")
    print(
        f"      Found {len(search_result['plan_codes'])} plans, "
        f"{len(search_result['schedule_codes'])} schedules"
    )

    # --- Agent 2: Schedule (The Schedule Reader) ---
    print("\n[2/5] SCHEDULE AGENT: Reading luminaire schedule tables...")
    t2 = time.time()
    schedule_result = run_schedule(source, work_dir, hints=hints)
    t_schedule = time.time() - t2
    print(f"      Completed in {t_schedule:.1f}s")
    print(
        f"      Extracted {len(schedule_result['fixture_codes'])} fixture types"
    )

    # --- Agents 3 & 4: Count + Keynote (parallel) ---
    print(
        "\n[3/5] COUNT AGENT + [4/5] KEYNOTE AGENT: "
        "Counting fixtures and keynotes (parallel)..."
    )
    t3 = time.time()
    count_result = None
    keynote_result = None

    with ThreadPoolExecutor(max_workers=2) as executor:
        count_future = executor.submit(run_count, source, work_dir, use_vision, hints)
        keynote_future = executor.submit(run_keynote, source, work_dir)

        for future in as_completed([count_future, keynote_future]):
            try:
                result = future.result()
                if future is count_future:
                    count_result = result
                else:
                    keynote_result = result
            except Exception as e:
                logger.error("Agent failed: %s", e)
                raise

    t_parallel = time.time() - t3
    print(f"      Both completed in {t_parallel:.1f}s (parallel)")

    # --- Agent 5: QA (The Senior Reviewer) ---
    print("\n[5/5] QA AGENT: Reviewing work, generating output...")
    t5 = time.time()
    qa_result = run_qa(source, work_dir, output_path)
    t_qa = time.time() - t5
    print(f"      Completed in {t_qa:.1f}s")

    total_time = time.time() - t0

    # --- Final Summary ---
    print("\n" + "=" * 60)
    print("  TEAM WORKFLOW COMPLETE")
    print("=" * 60)
    print(f"  Total time: {total_time:.1f}s")
    print(f"    Search:   {t_search:.1f}s")
    print(f"    Schedule: {t_schedule:.1f}s")
    print(f"    Count + Keynote (parallel): {t_parallel:.1f}s")
    print(f"    QA:       {t_qa:.1f}s")
    print(f"  Fixtures: {qa_result['fixture_count']} types, "
          f"{qa_result['total_fixtures']} total")
    print(f"  Keynotes: {qa_result['keynote_count']}")
    print(f"  QA: {qa_result['qa_confidence']:.1%} "
          f"{'PASSED' if qa_result['qa_passed'] else 'FAILED'}")
    print(f"  Output: {qa_result['excel_path']}")
    print("=" * 60)

    return qa_result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Run the Expert Electrical Contractor Agent Team"
    )
    parser.add_argument("source", help="PDF file or folder of PDFs")
    parser.add_argument(
        "--output", "-o", default="output/inventory",
        help="Output file path (without extension)",
    )
    parser.add_argument(
        "--use-vision", action="store_true",
        help="Use Claude Vision API for counting",
    )
    parser.add_argument(
        "--work-dir", default=None,
        help="Working directory for intermediate files",
    )

    args = parser.parse_args()
    run_team(args.source, args.output, args.use_vision, args.work_dir)
