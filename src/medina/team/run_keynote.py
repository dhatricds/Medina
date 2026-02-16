"""Keynote Agent: Extract and count keynotes on plan pages (Stage 5b).

Like the estimator reading keynotes on each plan and counting the
geometric callout symbols (diamonds, hexagons, circles).

Usage:
    uv run python -m medina.team.run_keynote <source> <work_dir>
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
logger = logging.getLogger("medina.team.keynote")


def run(source: str, work_dir: str) -> dict:
    """Run stage 5b: KEYNOTE EXTRACTION AND COUNTING."""
    from medina.pdf.loader import load
    from medina.pdf.classifier import classify_pages
    from medina.plans.keynotes import extract_all_keynotes
    from medina.models import PageType, SheetIndexEntry
    from medina.config import get_config

    source_path = Path(source)
    work_path = Path(work_dir)

    # Read intermediate results
    with open(work_path / "search_result.json", "r", encoding="utf-8") as f:
        search_data = json.load(f)
    with open(work_path / "schedule_result.json", "r", encoding="utf-8") as f:
        schedule_data = json.load(f)

    fixture_codes = schedule_data.get("fixture_codes", [])

    # Reload PDF and classify pages
    logger.info("[KEYNOTE] Loading PDF for keynote extraction...")
    pages, pdf_pages = load(source_path)
    sheet_index = [
        SheetIndexEntry.model_validate(e) for e in search_data["sheet_index"]
    ]
    pages = classify_pages(pages, pdf_pages, sheet_index)

    plan_pages = [p for p in pages if p.page_type == PageType.LIGHTING_PLAN]
    plan_codes = [p.sheet_code for p in plan_pages if p.sheet_code]

    logger.info(
        "[KEYNOTE] Extracting keynotes from %d plan pages: %s",
        len(plan_pages),
        plan_codes,
    )

    # --- Keynote extraction with geometric shape detection ---
    all_keynotes = []
    all_keynote_counts: dict[str, dict[str, int]] = {}

    if plan_pages:
        all_keynotes, all_keynote_counts = extract_all_keynotes(
            plan_pages, pdf_pages, fixture_codes or None,
        )

    # --- VLM fallback for plans with all-zero geometric counts ---
    config = get_config()
    if config.anthropic_api_key and all_keynotes:
        keynote_numbers = [str(kn.number) for kn in all_keynotes]

        plans_needing_vlm = []
        for pinfo in plan_pages:
            code = pinfo.sheet_code or str(pinfo.page_number)
            page_counts = all_keynote_counts.get(code, {})
            if not any(
                page_counts.get(n, 0) > 0 for n in keynote_numbers
            ):
                plans_needing_vlm.append(pinfo)

        if plans_needing_vlm:
            logger.info(
                "[KEYNOTE] VLM fallback for %d plan(s) with zero counts",
                len(plans_needing_vlm),
            )
            try:
                from medina.pdf.renderer import render_page_to_image
                from medina.plans.vision_keynote_counter import (
                    count_keynotes_vision,
                )

                vlm_dpi = min(config.render_dpi, 200)
                for pinfo in plans_needing_vlm:
                    code = pinfo.sheet_code or str(pinfo.page_number)
                    try:
                        img_bytes = render_page_to_image(
                            pinfo.source_path, pinfo.pdf_page_index,
                            dpi=vlm_dpi,
                        )
                        vlm_counts = count_keynotes_vision(
                            pinfo, img_bytes, keynote_numbers, config,
                        )
                        all_keynote_counts[code] = vlm_counts
                        logger.info(
                            "[KEYNOTE] VLM counts for %s: %s",
                            code, vlm_counts,
                        )
                    except Exception as e:
                        logger.warning(
                            "[KEYNOTE] VLM failed for %s: %s", code, e,
                        )
            except ImportError:
                logger.warning("[KEYNOTE] VLM keynote counter not available")

    logger.info(
        "[KEYNOTE] Extracted %d unique keynotes", len(all_keynotes),
    )

    # --- Save results ---
    result = {
        "keynotes": [kn.model_dump(mode="json") for kn in all_keynotes],
        "all_keynote_counts": all_keynote_counts,
    }

    out_file = work_path / "keynote_result.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str)

    logger.info("[KEYNOTE] Results saved to %s", out_file)

    # Print summary
    print(f"\n=== KEYNOTE AGENT RESULTS ===")
    print(f"Keynotes found: {len(all_keynotes)}")
    for kn in all_keynotes:
        print(f"  #{kn.number}: {kn.text[:60]}...")
        for plan, count in kn.counts_per_plan.items():
            if count > 0:
                print(f"    {plan}: {count} occurrences")
    print(f"Keynote counts per plan: {all_keynote_counts}")
    print(f"Results saved to: {out_file}")

    return result


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(
            "Usage: python -m medina.team.run_keynote <source> <work_dir>"
        )
        sys.exit(1)
    run(sys.argv[1], sys.argv[2])
