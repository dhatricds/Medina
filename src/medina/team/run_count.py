"""Count Agent: Count fixture occurrences on each plan page (Stage 5a).

Like the estimator going through each plan page, counting fixture
symbols with a highlighter.

Usage:
    uv run python -m medina.team.run_count <source> <work_dir> [--use-vision]
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
logger = logging.getLogger("medina.team.count")


def run(source: str, work_dir: str, use_vision: bool = False) -> dict:
    """Run stage 5a: FIXTURE COUNTING per plan page."""
    from medina.pdf.loader import load
    from medina.pdf.classifier import classify_pages
    from medina.plans.text_counter import count_all_plans
    from medina.models import PageInfo, PageType, SheetIndexEntry
    from medina.config import get_config

    source_path = Path(source)
    work_path = Path(work_dir)

    # Read intermediate results
    with open(work_path / "search_result.json", "r", encoding="utf-8") as f:
        search_data = json.load(f)
    with open(work_path / "schedule_result.json", "r", encoding="utf-8") as f:
        schedule_data = json.load(f)

    fixture_codes = schedule_data["fixture_codes"]
    if not fixture_codes:
        logger.warning("[COUNT] No fixture codes to count")
        result = {"all_plan_counts": {}}
        out_file = work_path / "count_result.json"
        with open(out_file, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        print("\n=== COUNT AGENT RESULTS ===")
        print("No fixture codes to count.")
        return result

    # Reload PDF and classify pages
    logger.info("[COUNT] Loading PDF for fixture counting...")
    pages, pdf_pages = load(source_path)
    sheet_index = [
        SheetIndexEntry.model_validate(e) for e in search_data["sheet_index"]
    ]
    pages = classify_pages(pages, pdf_pages, sheet_index)

    plan_pages = [p for p in pages if p.page_type == PageType.LIGHTING_PLAN]
    plan_codes = [p.sheet_code for p in plan_pages if p.sheet_code]

    logger.info(
        "[COUNT] Counting %d fixture codes on %d plan pages: %s",
        len(fixture_codes),
        len(plan_pages),
        plan_codes,
    )

    # --- Text-based counting ---
    all_plan_counts: dict[str, dict[str, int]] = {}
    if plan_pages and fixture_codes:
        all_plan_counts = count_all_plans(
            plan_pages, pdf_pages, fixture_codes, plan_sheet_codes=plan_codes,
        )

    # --- Vision-based counting (when enabled) ---
    config = get_config()
    if use_vision and config.anthropic_api_key and plan_pages:
        logger.info("[COUNT] Running vision-based counting...")
        try:
            from medina.pdf.renderer import render_page_to_image
            from medina.plans.vision_counter import count_all_plans_vision

            vision_dpi = min(config.render_dpi, 150)
            page_images: dict[int, bytes] = {}
            for pinfo in plan_pages:
                try:
                    img_bytes = render_page_to_image(
                        pinfo.source_path, pinfo.pdf_page_index,
                        dpi=vision_dpi,
                    )
                    page_images[pinfo.page_number] = img_bytes
                except Exception as e:
                    logger.warning("Render failed for %s: %s",
                                   pinfo.sheet_code, e)

            vision_counts = count_all_plans_vision(
                plan_pages, page_images, fixture_codes, config,
            )

            # Merge: use the higher of text and vision counts
            for plan_code, v_counts in vision_counts.items():
                t_counts = all_plan_counts.get(plan_code, {})
                merged: dict[str, int] = {}
                for fc in fixture_codes:
                    vc = v_counts.get(fc, 0)
                    tc = t_counts.get(fc, 0)
                    merged[fc] = max(vc, tc)
                all_plan_counts[plan_code] = merged

        except Exception as e:
            logger.warning("[COUNT] Vision counting failed: %s", e)

    # --- Save results ---
    result = {"all_plan_counts": all_plan_counts}

    out_file = work_path / "count_result.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    logger.info("[COUNT] Results saved to %s", out_file)

    # Print summary
    print(f"\n=== COUNT AGENT RESULTS ===")
    for plan_code, counts in all_plan_counts.items():
        nonzero = {k: v for k, v in counts.items() if v > 0}
        total = sum(counts.values())
        print(f"Plan {plan_code}: {total} fixtures ({len(nonzero)} types)")
        for code, count in sorted(nonzero.items()):
            print(f"  {code}: {count}")
    print(f"Results saved to: {out_file}")

    return result


if __name__ == "__main__":
    use_vision = "--use-vision" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--use-vision"]
    if len(args) < 2:
        print(
            "Usage: python -m medina.team.run_count <source> <work_dir> "
            "[--use-vision]"
        )
        sys.exit(1)
    run(args[0], args[1], use_vision=use_vision)
