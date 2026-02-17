"""QA Agent: Review, validate, and generate output (Stages 6-7).

Like the senior estimator reviewing each person's work for accuracy,
checking for errors, and producing the final deliverable.

Usage:
    uv run python -m medina.team.run_qa <source> <work_dir> <output_path>
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("medina.team.qa")


def run(
    source: str,
    work_dir: str,
    output_path: str = "output/inventory",
) -> dict:
    """Run stages 6-7: QA VERIFICATION and OUTPUT GENERATION."""
    from medina.models import (
        ExtractionResult,
        FixtureRecord,
        KeyNote,
        PageInfo,
        SheetIndexEntry,
    )
    from medina.qa.confidence import compute_confidence
    from medina.qa.report import format_qa_report
    from medina.output.excel import write_excel
    from medina.output.json_out import write_json
    from medina.config import get_config

    source_path = Path(source)
    work_path = Path(work_dir)
    out_path = Path(output_path)
    config = get_config()

    # --- Read all intermediate results ---
    logger.info("[QA] Reading intermediate results...")

    with open(work_path / "search_result.json", "r", encoding="utf-8") as f:
        search_data = json.load(f)

    with open(work_path / "schedule_result.json", "r", encoding="utf-8") as f:
        schedule_data = json.load(f)

    with open(work_path / "count_result.json", "r", encoding="utf-8") as f:
        count_data = json.load(f)

    with open(work_path / "keynote_result.json", "r", encoding="utf-8") as f:
        keynote_data = json.load(f)

    # --- Reconstruct data models ---
    project_name = search_data["project_name"]
    pages = [PageInfo.model_validate(p) for p in search_data["pages"]]
    sheet_index = [
        SheetIndexEntry.model_validate(e) for e in search_data["sheet_index"]
    ]
    plan_codes = search_data["plan_codes"]
    schedule_codes = search_data["schedule_codes"]

    fixtures = [
        FixtureRecord.model_validate(f) for f in schedule_data["fixtures"]
    ]
    fixture_codes = schedule_data["fixture_codes"]

    all_plan_counts = count_data["all_plan_counts"]
    all_keynotes = [
        KeyNote.model_validate(kn) for kn in keynote_data["keynotes"]
    ]
    all_keynote_counts = keynote_data["all_keynote_counts"]

    # --- Aggregate per-plan counts into fixtures ---
    logger.info("[QA] Aggregating per-plan counts...")
    for fixture in fixtures:
        fixture.counts_per_plan = {
            plan_code: plan_counts.get(fixture.code, 0)
            for plan_code, plan_counts in all_plan_counts.items()
        }
        fixture.total = sum(fixture.counts_per_plan.values())

    # Keynote counts are already per-page from extraction — just
    # recalculate totals from the counts_per_plan each keynote carries.
    for keynote in all_keynotes:
        keynote.total = sum(keynote.counts_per_plan.values())

    # --- Build ExtractionResult ---
    result = ExtractionResult(
        source=project_name,
        sheet_index=sheet_index,
        pages=pages,
        fixtures=fixtures,
        keynotes=all_keynotes,
        schedule_pages=schedule_codes,
        plan_pages=plan_codes,
    )

    # --- Stage 6: QA verification ---
    logger.info("[QA] Running QA verification...")
    qa_report = compute_confidence(result, config.qa_confidence_threshold)
    result.qa_report = qa_report

    qa_text = format_qa_report(qa_report, project_name)
    logger.info("\n%s", qa_text)

    # --- Stage 7: Generate output ---
    logger.info("[QA] Generating output files...")

    excel_path = out_path.with_suffix(".xlsx")
    write_excel(result, excel_path)

    json_path = out_path.with_suffix(".json")
    write_json(result, json_path)

    # Print full QA report and summary
    print(f"\n{qa_text}")
    print(f"\n=== QA AGENT RESULTS ===")
    print(f"Project: {project_name}")
    print(f"Fixtures: {len(fixtures)} types, {sum(f.total for f in fixtures)} total")
    print(f"Keynotes: {len(all_keynotes)}")
    print(f"QA Confidence: {qa_report.overall_confidence:.1%}")
    print(f"QA Status: {'PASSED' if qa_report.passed else 'FAILED'}")

    if qa_report.warnings:
        print(f"\nWarnings:")
        for w in qa_report.warnings:
            print(f"  ! {w}")

    print(f"\nFixture Inventory:")
    for f in fixtures:
        print(
            f"  {f.code}: {f.total} total "
            f"({', '.join(f'{k}={v}' for k, v in f.counts_per_plan.items())})"
        )

    if all_keynotes:
        print(f"\nKeynote Counts:")
        for kn in all_keynotes:
            print(
                f"  #{kn.number}: {kn.total} total "
                f"({', '.join(f'{k}={v}' for k, v in kn.counts_per_plan.items())})"
            )

    print(f"\nOutput files:")
    print(f"  Excel: {excel_path}")
    print(f"  JSON:  {json_path}")

    return {
        "project_name": project_name,
        "fixture_count": len(fixtures),
        "total_fixtures": sum(f.total for f in fixtures),
        "keynote_count": len(all_keynotes),
        "qa_confidence": qa_report.overall_confidence,
        "qa_passed": qa_report.passed,
        "excel_path": str(excel_path),
        "json_path": str(json_path),
    }


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(
            "Usage: python -m medina.team.run_qa "
            "<source> <work_dir> [output_path]"
        )
        sys.exit(1)
    out = sys.argv[3] if len(sys.argv) > 3 else "output/inventory"
    run(sys.argv[1], sys.argv[2], out)
