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
        result = {"all_plan_counts": {}, "all_plan_positions": {}}
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
    all_plan_positions: dict[str, dict] = {}
    if plan_pages and fixture_codes:
        counts_result = count_all_plans(
            plan_pages, pdf_pages, fixture_codes, plan_sheet_codes=plan_codes,
            return_positions=True,
        )
        if isinstance(counts_result, tuple):
            all_plan_counts, all_plan_positions = counts_result
        else:
            all_plan_counts = counts_result

    # --- Vision-based counting ---
    # Triggers when:
    #   1. User explicitly requested --use-vision, OR
    #   2. Any single-char fixture codes exist (text counting is unreliable
    #      for these — too many false positives/negatives from room labels,
    #      panel refs, etc.)
    config = get_config()
    has_short_codes = any(len(fc) == 1 for fc in fixture_codes)
    should_run_vlm = (
        (use_vision or has_short_codes)
        and config.anthropic_api_key
        and plan_pages
    )
    if has_short_codes and not use_vision:
        short_list = [fc for fc in fixture_codes if len(fc) == 1]
        logger.info(
            "[COUNT] Short fixture codes detected %s — auto-triggering VLM recount",
            short_list,
        )

    if should_run_vlm:
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

            # Smart merge strategy:
            # - Single-char codes (len=1): text counting is unreliable due
            #   to false positives/negatives.  When text and VLM agree
            #   (within ±2), take the higher value.  When they disagree
            #   significantly (>2), prefer text (more conservative).
            # - Multi-char codes (len≥2): text counting is already accurate.
            #   Always keep text count — VLM tends to overcount on these.
            _MERGE_TOLERANCE = 2
            for plan_code, v_counts in vision_counts.items():
                t_counts = all_plan_counts.get(plan_code, {})
                merged: dict[str, int] = {}
                for fc in fixture_codes:
                    vc = v_counts.get(fc, 0)
                    tc = t_counts.get(fc, 0)
                    if len(fc) > 1:
                        # Multi-char: text is reliable, skip VLM
                        merged[fc] = tc
                        if vc != tc and vc > 0:
                            logger.debug(
                                "[COUNT] %s on %s: text=%d, VLM=%d → keeping text (multi-char)",
                                fc, plan_code, tc, vc,
                            )
                        continue
                    diff = abs(vc - tc)
                    if tc == 0 and vc > 0:
                        merged[fc] = vc  # text missed entirely
                    elif diff <= _MERGE_TOLERANCE:
                        merged[fc] = max(vc, tc)  # close agreement
                    else:
                        merged[fc] = tc  # significant disagreement → text
                    if vc != tc and vc > 0:
                        logger.info(
                            "[COUNT] %s on %s: text=%d, VLM=%d, diff=%d → using %d%s",
                            fc, plan_code, tc, vc, diff, merged[fc],
                            " (text wins, disagree)" if diff > _MERGE_TOLERANCE else "",
                        )
                all_plan_counts[plan_code] = merged

        except Exception as e:
            logger.warning("[COUNT] Vision counting failed: %s", e)

    # --- Save results ---
    result = {
        "all_plan_counts": all_plan_counts,
        "all_plan_positions": all_plan_positions,
    }

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
