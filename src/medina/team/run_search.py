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


def run(source: str, work_dir: str, hints=None) -> dict:
    """Run stages 1-3: LOAD, DISCOVER, CLASSIFY.

    Args:
        source: Path to source PDF or folder.
        work_dir: Directory for intermediate results.
        hints: Optional FeedbackHints with page_overrides to force
               page classifications.
    """
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

    # --- Backfill missing sheet codes from sheet index ---
    # When pages have no sheet_code (e.g., scanned PDFs with timestamps
    # in title blocks), match them to sheet index entries by page type
    # and order.  E.g., if the index lists e1.1, e1.2 as lighting plans
    # and the classifier found 2 LIGHTING_PLAN pages with no codes,
    # assign e1.1 to the first and e1.2 to the second.
    if sheet_index:
        _backfill_sheet_codes(pages, sheet_index)

    # --- Apply user page classification overrides ---
    page_overrides = {}
    if hints and hasattr(hints, "page_overrides"):
        page_overrides = hints.page_overrides or {}
    if page_overrides:
        _apply_page_overrides(pages, page_overrides)
        # Re-run backfill — overrides may have changed page types,
        # allowing previously-unmatched sheet index entries to pair
        # with the newly-reclassified pages.
        if sheet_index:
            _backfill_sheet_codes(pages, sheet_index)

    # --- Multi-viewport detection ---
    # For each lighting plan, check if it contains multiple viewports
    # (e.g., "LEVEL 1 ENLARGED LIGHTING PLAN" + "MEZZANINE ENLARGED LIGHTING PLAN").
    # Also apply user-provided viewport splits from hints.
    viewport_splits = {}
    if hints and hasattr(hints, "viewport_splits"):
        viewport_splits = hints.viewport_splits or {}

    from medina.plans.viewport_detector import detect_viewports, split_page_into_viewports

    expanded_pages: list = []
    viewport_map: dict[str, int] = {}  # composite_code -> physical page_number
    for p in pages:
        if p.page_type == PageType.LIGHTING_PLAN:
            # Check user-provided splits first
            p_key = p.sheet_code or str(p.page_number)
            user_split_data = viewport_splits.get(p_key)
            if user_split_data is not None and len(user_split_data) > 0:
                # User/LLM provided viewport hints.  If they include a
                # bbox they are fully defined; otherwise treat them as
                # label-only hints and fall through to auto-detect.
                from medina.models import Viewport
                all_have_bbox = all(
                    isinstance(vp, dict) and "bbox" in vp
                    for vp in user_split_data
                )
                if all_have_bbox:
                    user_vps = [
                        Viewport.model_validate(vp)
                        for vp in user_split_data
                    ]
                    virtual = split_page_into_viewports(p, user_vps)
                else:
                    # Labels without bbox — auto-detect to get real boxes
                    logger.info(
                        "Viewport hints for %s lack bbox — falling back "
                        "to auto-detect",
                        p_key,
                    )
                    pdf_page = pdf_pages.get(p.page_number)
                    if pdf_page is not None:
                        vps = detect_viewports(pdf_page, p)
                        virtual = split_page_into_viewports(p, vps)
                    else:
                        virtual = [p]
            else:
                # Auto-detect viewports (triggered for all lighting plans,
                # or when user sent empty list = "auto-detect" sentinel)
                pdf_page = pdf_pages.get(p.page_number)
                if pdf_page is not None:
                    vps = detect_viewports(pdf_page, p)
                    virtual = split_page_into_viewports(p, vps)
                else:
                    virtual = [p]
            for vp in virtual:
                expanded_pages.append(vp)
                if vp.parent_sheet_code:
                    viewport_map[vp.sheet_code] = vp.page_number
        else:
            expanded_pages.append(p)
    pages = expanded_pages

    plan_pages = [p for p in pages if p.page_type == PageType.LIGHTING_PLAN]
    schedule_pages = [p for p in pages if p.page_type == PageType.SCHEDULE]
    # Ensure every plan/schedule page has a sheet_code — downstream agents
    # skip pages without one.  Fall back to "pg{N}" for pages that didn't
    # get a code from title block or backfill.
    for p in plan_pages + schedule_pages:
        if not p.sheet_code:
            p.sheet_code = f"pg{p.page_number}"
            logger.info(
                "[SEARCH] Assigned fallback code %s to page %d (%s)",
                p.sheet_code, p.page_number, p.page_type.value,
            )
    plan_codes = [p.sheet_code for p in plan_pages]
    schedule_codes = [p.sheet_code for p in schedule_pages]

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
        if config.has_vlm_key:
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
                        p.sheet_code or str(p.page_number)
                        for p in schedule_pages
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
        "viewport_map": viewport_map,
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


def _apply_page_overrides(
    pages: list,
    page_overrides: dict[str, str],
) -> None:
    """Apply user page classification overrides.

    Overrides can reference pages by sheet_code (e.g., "E601") or by
    page_number as a string (e.g., "5").
    """
    from medina.models import PageType

    type_map = {t.value: t for t in PageType}

    for key, page_type_str in page_overrides.items():
        if not key:
            continue  # Skip empty keys
        target_type = type_map.get(page_type_str)
        if not target_type:
            logger.warning(
                "[SEARCH] Unknown page type in override: %s", page_type_str
            )
            continue

        # Normalize key: "page_4" / "pg4" → "4"
        norm_key = key
        for prefix in ("page_", "pg"):
            if norm_key.lower().startswith(prefix):
                norm_key = norm_key[len(prefix):]
                break

        matched = False
        for page in pages:
            # Match by sheet code (case-insensitive)
            if page.sheet_code and page.sheet_code.upper() == norm_key.upper():
                old_type = page.page_type.value
                page.page_type = target_type
                logger.info(
                    "[SEARCH] Page override: page %d (%s) %s -> %s",
                    page.page_number, page.sheet_code, old_type, target_type.value,
                )
                matched = True
                break
            # Match by page number
            if norm_key.isdigit() and page.page_number == int(norm_key):
                old_type = page.page_type.value
                page.page_type = target_type
                logger.info(
                    "[SEARCH] Page override: page %d (%s) %s -> %s",
                    page.page_number, page.sheet_code or "?",
                    old_type, target_type.value,
                )
                matched = True
                break

        if not matched:
            logger.warning(
                "[SEARCH] Page override target not found: %s", key
            )


def _backfill_sheet_codes(
    pages: list,
    sheet_index: list,
) -> None:
    """Assign sheet codes from the sheet index to pages missing them.

    For each page type (lighting_plan, schedule, etc.), collect:
    - Sheet index entries of that type whose code isn't on any page
    - Pages of that type with no sheet_code
    Then match them in order.
    """
    from medina.models import PageType

    existing_codes = {
        p.sheet_code.upper() for p in pages if p.sheet_code
    }

    for page_type in (
        PageType.LIGHTING_PLAN,
        PageType.SCHEDULE,
        PageType.DEMOLITION_PLAN,
        PageType.POWER_PLAN,
    ):
        # Index entries of this type not yet matched to a page
        unmatched_entries = [
            e for e in sheet_index
            if e.inferred_type == page_type
            and e.sheet_code.upper() not in existing_codes
        ]
        # Pages of this type with no sheet code
        unmatched_pages = [
            p for p in pages
            if p.page_type == page_type and not p.sheet_code
        ]

        if not unmatched_entries or not unmatched_pages:
            continue

        for page, entry in zip(unmatched_pages, unmatched_entries):
            page.sheet_code = entry.sheet_code
            logger.info(
                "[SEARCH] Backfilled page %d with sheet code %s "
                "from sheet index (%s)",
                page.page_number,
                entry.sheet_code,
                page_type.value,
            )


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python -m medina.team.run_search <source> <work_dir>")
        sys.exit(1)
    run(sys.argv[1], sys.argv[2])
