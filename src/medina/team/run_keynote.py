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


_MAX_PLAUSIBLE_KEYNOTE_COUNT = 10  # Single keynote rarely appears >10 times per plan


def run(source: str, work_dir: str, source_key: str = "", project_id: str = "", hints=None) -> dict:
    """Run stage 5b: KEYNOTE EXTRACTION AND COUNTING."""
    from medina.pdf.loader import load
    from medina.plans.keynotes import extract_all_keynotes
    from medina.models import PageInfo, PageType
    from medina.config import get_config

    source_path = Path(source)
    work_path = Path(work_dir)

    # Read intermediate results
    with open(work_path / "search_result.json", "r", encoding="utf-8") as f:
        search_data = json.load(f)
    with open(work_path / "schedule_result.json", "r", encoding="utf-8") as f:
        schedule_data = json.load(f)

    fixture_codes = schedule_data.get("fixture_codes", [])

    # Load runtime params for keynote thresholds
    max_plausible = _MAX_PLAUSIBLE_KEYNOTE_COUNT
    keynote_max_num = 20
    try:
        from medina.runtime_params import get_effective_params
        rt_params = get_effective_params(source_key=source_key, project_id=project_id)
        max_plausible = rt_params.get("max_plausible_keynote_count", max_plausible)
        keynote_max_num = rt_params.get("keynote_max_number", keynote_max_num)
    except Exception:
        pass

    # Reconstruct PageInfo from search_result.json to preserve Fix It
    # page overrides (re-classifying from scratch would lose them).
    pages = [PageInfo.model_validate(p) for p in search_data["pages"]]
    logger.info("[KEYNOTE] Loading PDF for keynote extraction...")
    _, pdf_pages = load(source_path)

    plan_pages = [p for p in pages if p.page_type == PageType.LIGHTING_PLAN]
    plan_codes = [p.sheet_code or f"pg{p.page_number}" for p in plan_pages]

    logger.info(
        "[KEYNOTE] Extracting keynotes from %d plan pages: %s",
        len(plan_pages),
        plan_codes,
    )

    # --- Keynote extraction with geometric shape detection ---
    all_keynotes = []
    all_keynote_counts: dict[str, dict[str, int]] = {}
    all_keynote_positions: dict[str, dict] = {}

    if plan_pages:
        kn_result = extract_all_keynotes(
            plan_pages, pdf_pages, fixture_codes or None,
            return_positions=True,
        )
        if len(kn_result) == 3:
            all_keynotes, all_keynote_counts, all_keynote_positions = kn_result
        else:
            all_keynotes, all_keynote_counts = kn_result[0], kn_result[1]

    # --- VLM fallback for plans with low keynote counts ---
    # Triggers when: (a) all counts are zero, or (b) total count is
    # suspiciously low relative to the number of keynotes defined on
    # that page (indicates geometric/text detection failed).
    config = get_config()
    if config.anthropic_api_key and all_keynotes:
        keynote_numbers = list(dict.fromkeys(
            str(kn.number) for kn in all_keynotes
        ))

        plans_needing_vlm = []
        for pinfo in plan_pages:
            code = pinfo.sheet_code or str(pinfo.page_number)
            page_counts = all_keynote_counts.get(code, {})
            # Keynote numbers defined for this specific plan
            plan_kn_nums = [
                n for n in page_counts if page_counts.get(n) is not None
            ]
            total = sum(page_counts.get(n, 0) for n in plan_kn_nums)
            num_keynotes = len(plan_kn_nums) or len(keynote_numbers)
            max_single = max(page_counts.values()) if page_counts else 0
            # Trigger VLM if:
            # (a) total count too low — each keynote should appear ≥1 on avg
            # (b) any single keynote count suspiciously high — likely false
            #     positives from dense line pages (bare circuit numbers
            #     passing the geometric quadrant check)
            if total < num_keynotes or max_single > max_plausible:
                if max_single > max_plausible:
                    logger.info(
                        "[KEYNOTE] Plan %s: max keynote count=%d exceeds "
                        "threshold=%d — triggering VLM verification",
                        code, max_single, max_plausible,
                    )
                plans_needing_vlm.append(pinfo)

        if plans_needing_vlm:
            logger.info(
                "[KEYNOTE] VLM fallback for %d plan(s) with low/suspect counts",
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

    # --- Sync VLM-updated counts back into keynote objects ---
    # VLM fallback updates all_keynote_counts but not the individual
    # KeyNote.counts_per_plan.  Sync them so the saved JSON (and the
    # frontend display) reflects the latest counts.
    for kn in all_keynotes:
        for plan_code in list(kn.counts_per_plan):
            if plan_code in all_keynote_counts:
                kn.counts_per_plan[plan_code] = (
                    all_keynote_counts[plan_code]
                    .get(str(kn.number), 0)
                )
        kn.total = sum(kn.counts_per_plan.values())

    # --- Apply keynote count overrides from user feedback ---
    if hints and hasattr(hints, "keynote_count_overrides") and hints.keynote_count_overrides:
        logger.info(
            "[KEYNOTE] Applying %d keynote count override(s)",
            len(hints.keynote_count_overrides),
        )
        for kn_num, plan_overrides in hints.keynote_count_overrides.items():
            for plan_code, corrected in plan_overrides.items():
                # Update all_keynote_counts
                if plan_code in all_keynote_counts:
                    all_keynote_counts[plan_code][str(kn_num)] = corrected
                # Update keynote objects
                for kn in all_keynotes:
                    if str(kn.number) == str(kn_num) and plan_code in kn.counts_per_plan:
                        kn.counts_per_plan[plan_code] = corrected
                        kn.total = sum(kn.counts_per_plan.values())
                        logger.info(
                            "[KEYNOTE] Override: #%s on %s = %d",
                            kn_num, plan_code, corrected,
                        )

    # --- Apply keynote add/remove from user feedback ---
    if hints and hasattr(hints, "removed_keynote_numbers") and hints.removed_keynote_numbers:
        before = len(all_keynotes)
        removed_set = set(str(n) for n in hints.removed_keynote_numbers)
        all_keynotes = [kn for kn in all_keynotes if str(kn.number) not in removed_set]
        # Also remove from counts dicts
        for plan_code in list(all_keynote_counts):
            for kn_num in removed_set:
                all_keynote_counts[plan_code].pop(kn_num, None)
        for kn_num in removed_set:
            all_keynote_positions.pop(kn_num, None)
        logger.info(
            "[KEYNOTE] Removed %d user-rejected keynotes: %s",
            before - len(all_keynotes), sorted(removed_set),
        )

    if hints and hasattr(hints, "extra_keynotes") and hints.extra_keynotes:
        from medina.models import KeyNote
        for kn_data in hints.extra_keynotes:
            kn_num = str(kn_data.get("keynote_number", ""))
            kn_text = kn_data.get("keynote_text", "")
            kn_counts = kn_data.get("counts_per_plan", {})
            if not kn_num:
                continue
            # Check if keynote already exists (update it)
            existing = next((k for k in all_keynotes if str(k.number) == kn_num), None)
            if existing:
                for plan_code, count in kn_counts.items():
                    existing.counts_per_plan[plan_code] = count
                existing.total = sum(existing.counts_per_plan.values())
                if kn_text and not existing.text:
                    existing.text = kn_text
                logger.info("[KEYNOTE] Updated user-added keynote #%s", kn_num)
            else:
                new_kn = KeyNote(
                    number=kn_num,
                    text=kn_text,
                    counts_per_plan=kn_counts,
                    total=sum(kn_counts.values()),
                )
                all_keynotes.append(new_kn)
                logger.info("[KEYNOTE] Added user-provided keynote #%s", kn_num)
            # Update all_keynote_counts
            for plan_code, count in kn_counts.items():
                if plan_code not in all_keynote_counts:
                    all_keynote_counts[plan_code] = {}
                all_keynote_counts[plan_code][kn_num] = count

    logger.info(
        "[KEYNOTE] Extracted %d unique keynotes", len(all_keynotes),
    )

    # --- Save results ---
    result = {
        "keynotes": [kn.model_dump(mode="json") for kn in all_keynotes],
        "all_keynote_counts": all_keynote_counts,
        "all_keynote_positions": all_keynote_positions,
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
