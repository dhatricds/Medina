"""Search Agent: Load PDF, discover sheet index, classify pages (Stages 1-3).

Like the contractor opening the drawings and flipping to the first
legend page to find the sheet index and identify which pages are
schedules and which are plans.

Usage:
    uv run python -m medina.team.run_search <source> <work_dir>
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
logger = logging.getLogger("medina.team.search")


def run(source: str, work_dir: str) -> dict:
    """Run stages 1-3: LOAD, DISCOVER, CLASSIFY."""
    from medina.pdf.loader import load
    from medina.pdf.sheet_index import discover_sheet_index
    from medina.pdf.classifier import classify_pages
    from medina.models import PageType

    source_path = Path(source)
    work_path = Path(work_dir)
    work_path.mkdir(parents=True, exist_ok=True)

    # --- Stage 1: LOAD ---
    logger.info("[SEARCH] Loading from %s", source_path)
    pages, pdf_pages = load(source_path)
    logger.info("[SEARCH] Loaded %d pages", len(pages))

    # --- Stage 2: DISCOVER ---
    logger.info("[SEARCH] Discovering sheet index...")
    sheet_index = discover_sheet_index(pages, pdf_pages)
    logger.info("[SEARCH] Found %d sheet index entries", len(sheet_index))
    for entry in sheet_index:
        t = entry.inferred_type.value if entry.inferred_type else "?"
        logger.info("  %s: %s [%s]", entry.sheet_code, entry.description, t)

    # --- Stage 3: CLASSIFY ---
    logger.info("[SEARCH] Classifying pages...")
    pages = classify_pages(pages, pdf_pages, sheet_index)

    plan_pages = [p for p in pages if p.page_type == PageType.LIGHTING_PLAN]
    schedule_pages = [p for p in pages if p.page_type == PageType.SCHEDULE]
    plan_codes = [p.sheet_code for p in plan_pages if p.sheet_code]
    schedule_codes = [p.sheet_code for p in schedule_pages if p.sheet_code]

    logger.info(
        "[SEARCH] Classification complete: %d lighting plans, %d schedules",
        len(plan_pages),
        len(schedule_pages),
    )

    # --- VLM Classification Fallback ---
    # When no sheet index and missing plan or schedule pages, use Claude
    # Vision to classify unidentified pages.
    if not sheet_index and (not plan_pages or not schedule_pages):
        from medina.config import get_config
        config = get_config()
        if config.anthropic_api_key:
            vlm_candidates = [
                p for p in pages
                if p.page_type in (
                    PageType.OTHER, PageType.POWER_PLAN, PageType.DETAIL,
                )
            ]
            if vlm_candidates:
                logger.info(
                    "[SEARCH] No sheet index — running VLM fallback on "
                    "%d candidate page(s)...",
                    len(vlm_candidates),
                )
                try:
                    from medina.pdf.vlm_classifier import classify_pages_vlm
                    vlm_results = classify_pages_vlm(vlm_candidates, config)
                    for page in pages:
                        if page.page_number in vlm_results:
                            vlm_types = vlm_results[page.page_number]
                            if PageType.LIGHTING_PLAN in vlm_types:
                                page.page_type = PageType.LIGHTING_PLAN
                            elif PageType.SCHEDULE in vlm_types:
                                page.page_type = PageType.SCHEDULE
                    # Refresh lists
                    plan_pages = [
                        p for p in pages
                        if p.page_type == PageType.LIGHTING_PLAN
                    ]
                    schedule_pages = [
                        p for p in pages
                        if p.page_type == PageType.SCHEDULE
                    ]
                    plan_codes = [
                        p.sheet_code for p in plan_pages if p.sheet_code
                    ]
                    schedule_codes = [
                        p.sheet_code for p in schedule_pages if p.sheet_code
                    ]
                    logger.info(
                        "[SEARCH] After VLM: %d lighting plans, %d schedules",
                        len(plan_pages),
                        len(schedule_pages),
                    )
                except Exception as e:
                    logger.warning(
                        "[SEARCH] VLM classification fallback failed: %s", e
                    )

    for p in pages:
        logger.info(
            "  Page %d (%s): %s",
            p.page_number,
            p.sheet_code or "?",
            p.page_type.value,
        )

    # --- Save results ---
    result = {
        "source": str(source_path),
        "project_name": (
            source_path.stem if source_path.is_file() else source_path.name
        ),
        "pages": [p.model_dump(mode="json") for p in pages],
        "sheet_index": [e.model_dump(mode="json") for e in sheet_index],
        "plan_codes": plan_codes,
        "schedule_codes": schedule_codes,
    }

    out_file = work_path / "search_result.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str)

    logger.info("[SEARCH] Results saved to %s", out_file)

    # Print summary for agent
    print(f"\n=== SEARCH AGENT RESULTS ===")
    print(f"Source: {source_path.name}")
    print(f"Pages loaded: {len(pages)}")
    print(f"Sheet index entries: {len(sheet_index)}")
    print(f"Lighting plans: {plan_codes}")
    print(f"Schedule pages: {schedule_codes}")
    print(f"Results saved to: {out_file}")

    return result


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python -m medina.team.run_search <source> <work_dir>")
        sys.exit(1)
    run(sys.argv[1], sys.argv[2])
