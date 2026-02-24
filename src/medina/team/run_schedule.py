"""Schedule Agent: Extract fixture schedule tables (Stage 4).

Like the estimator reading the luminaire schedule table, creating
inventory entries with specs (code, description, voltage, etc.).

Usage:
    uv run python -m medina.team.run_schedule <source> <work_dir>
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
logger = logging.getLogger("medina.team.schedule")


import re

# Header words that should never be treated as fixture codes.
_HEADER_WORDS = frozenset({
    "SCHEDULE", "SCHEDULES", "LUMINAIRE", "FIXTURE", "FIXTURES",
    "LIGHTING", "TYPE", "DESCRIPTION", "MARK", "SYMBOL", "CATALOG",
    "MOUNTING", "VOLTAGE", "DIMMING", "WATTS", "WATTAGE",
})


def _is_valid_fixture_code(code: str) -> bool:
    """Check if code looks like a real fixture identifier, not a table header."""
    code = code.strip().upper()
    if not code:
        return False
    if code in _HEADER_WORDS:
        return False
    # Pure alphabetic codes longer than 3 chars are table headers.
    # Real pure-alpha fixture codes: A, B, EX, SL, WL (1-3 chars).
    if code.isalpha() and len(code) > 3:
        return False
    return True


def run(source: str, work_dir: str, hints=None, source_key: str = "", project_id: str = "") -> dict:
    """Run stage 4: SCHEDULE EXTRACTION."""
    from medina.pdf.loader import load
    from medina.pdf.classifier import classify_pages
    from medina.schedule.parser import parse_all_schedules
    from medina.models import PageInfo, PageType, SheetIndexEntry
    from medina.config import get_config

    source_path = Path(source)
    work_path = Path(work_dir)

    # Read search results
    search_file = work_path / "search_result.json"
    with open(search_file, "r", encoding="utf-8") as f:
        search_data = json.load(f)

    logger.info("[SCHEDULE] Loading PDF for schedule extraction...")
    pages_raw, pdf_pages = load(source_path)

    # Reconstruct classified pages from search results
    pages = [PageInfo.model_validate(p) for p in search_data["pages"]]
    sheet_index = [
        SheetIndexEntry.model_validate(e) for e in search_data["sheet_index"]
    ]

    # Re-classify to ensure page_type is set (pages from JSON may lack it
    # if the loader returns fresh PageInfo objects).
    from medina.pdf.classifier import classify_pages
    pages_raw = classify_pages(pages_raw, pdf_pages, sheet_index)

    schedule_pages = [
        p for p in pages_raw if p.page_type == PageType.SCHEDULE
    ]
    plan_pages = [
        p for p in pages_raw if p.page_type == PageType.LIGHTING_PLAN
    ]

    logger.info(
        "[SCHEDULE] Processing %d schedule pages: %s",
        len(schedule_pages),
        [p.sheet_code for p in schedule_pages],
    )

    # --- Stage 4: Text-based schedule extraction ---
    fixtures = []
    if schedule_pages:
        fixtures = parse_all_schedules(schedule_pages, pdf_pages)

    # Combo page: also check plan pages for embedded schedule tables
    if plan_pages:
        combo_fixtures = parse_all_schedules(plan_pages, pdf_pages)
        if combo_fixtures:
            logger.info(
                "[SCHEDULE] Found %d fixture type(s) on plan page(s) "
                "(combo page)",
                len(combo_fixtures),
            )
            fixtures.extend(combo_fixtures)

    # Extract fixture codes from plan pages (for VLM cross-reference)
    found_plan_codes: set[str] = set()
    if plan_pages:
        from medina.schedule.vlm_extractor import extract_plan_fixture_codes
        plan_pdf_pages = {
            p.page_number: pdf_pages[p.page_number]
            for p in plan_pages
            if p.page_number in pdf_pages
        }
        found_plan_codes = extract_plan_fixture_codes(plan_pdf_pages)
        if found_plan_codes:
            logger.info(
                "[SCHEDULE] Found %d fixture codes on plan pages: %s",
                len(found_plan_codes),
                sorted(found_plan_codes),
            )

    # --- Filter out invalid fixture codes (table headers, etc.) ---
    before_filter = len(fixtures)
    fixtures = [f for f in fixtures if _is_valid_fixture_code(f.code)]
    if before_filter > len(fixtures):
        logger.info(
            "[SCHEDULE] Filtered out %d invalid fixture code(s)",
            before_filter - len(fixtures),
        )

    # --- VLM fallback when pdfplumber extracted 0 valid fixtures ---
    # Triggered when: (a) pdfplumber found no fixtures, or (b) page has
    # image-based content.  Covers both truly rasterized pages and pages
    # with text tables whose column headers don't match expected patterns.
    # When no dedicated schedule pages exist, try plan pages (combo pages
    # may have embedded schedule tables that are image-based).
    config = get_config()
    vlm_candidates = schedule_pages if schedule_pages else plan_pages
    if not fixtures and vlm_candidates and config.anthropic_api_key:
        from medina.schedule.vlm_extractor import (
            extract_schedule_vlm,
        )
        from medina.pdf.renderer import render_page_to_image
        import base64

        for spage in vlm_candidates:
            spdf = pdf_pages.get(spage.page_number)
            if spdf is None:
                continue

            label = spage.sheet_code or str(spage.page_number)
            logger.info(
                "[SCHEDULE] pdfplumber found 0 fixtures on %s — "
                "trying VLM fallback",
                label,
            )
            try:
                from PIL import Image
                import io

                _MAX_VLM_PIXEL = 8000  # Claude Vision API max dimension

                sched_render_dpi = 200
                try:
                    from medina.runtime_params import get_param
                    sched_render_dpi = get_param("schedule_render_dpi", source_key=source_key, project_id=project_id)
                except Exception:
                    pass
                sched_dpi = min(config.render_dpi, sched_render_dpi)
                img_bytes = render_page_to_image(
                    spage.source_path, spage.pdf_page_index,
                    dpi=sched_dpi,
                )
                b64_size = len(base64.b64encode(img_bytes))
                img = Image.open(io.BytesIO(img_bytes))
                max_dim = max(img.size)
                while (b64_size > 5_000_000 or max_dim > _MAX_VLM_PIXEL) and sched_dpi > 72:
                    sched_dpi = max(72, sched_dpi - 20)
                    img_bytes = render_page_to_image(
                        spage.source_path, spage.pdf_page_index,
                        dpi=sched_dpi,
                    )
                    b64_size = len(base64.b64encode(img_bytes))
                    img = Image.open(io.BytesIO(img_bytes))
                    max_dim = max(img.size)
                logger.info(
                    "[SCHEDULE] VLM render: %s at %d DPI, %dx%d px, %.1f MB",
                    label, sched_dpi, img.size[0], img.size[1],
                    b64_size / 1_000_000,
                )
                vlm_fixtures = extract_schedule_vlm(
                    spage, img_bytes, config,
                    plan_codes_hint=(
                        found_plan_codes if found_plan_codes else None
                    ),
                )
                fixtures.extend(vlm_fixtures)
                logger.info(
                    "[SCHEDULE] VLM extracted %d fixtures from %s",
                    len(vlm_fixtures),
                    label,
                )
            except Exception as e:
                logger.warning(
                    "[SCHEDULE] VLM failed for %s: %s", label, e
                )

    # Cross-reference VLM codes against plan page text
    if fixtures and found_plan_codes:
        from medina.schedule.vlm_extractor import crossref_vlm_codes
        fixtures = crossref_vlm_codes(fixtures, found_plan_codes)

    # Deduplicate by code
    seen: set[str] = set()
    deduped = []
    for f in fixtures:
        if f.code not in seen:
            seen.add(f.code)
            deduped.append(f)
    fixtures = deduped

    # --- Apply user feedback hints ---
    if hints is not None:
        # Remove user-flagged fixtures
        if hints.removed_codes:
            before = len(fixtures)
            fixtures = [f for f in fixtures if f.code not in hints.removed_codes]
            for code in hints.removed_codes:
                logger.info("[SCHEDULE] User hint: removed %s", code)
            if before > len(fixtures):
                logger.info(
                    "[SCHEDULE] Removed %d fixture(s) via user hints",
                    before - len(fixtures),
                )

        # Add user-provided fixtures
        if hints.extra_fixtures:
            from medina.models import FixtureRecord
            existing_codes = {f.code for f in fixtures}
            for fx_data in hints.extra_fixtures:
                code = fx_data.get("code", "")
                if code and code not in existing_codes:
                    new_fixture = FixtureRecord(
                        code=code,
                        description=fx_data.get("description", ""),
                        fixture_style=fx_data.get("fixture_style", ""),
                        voltage=fx_data.get("voltage", ""),
                        mounting=fx_data.get("mounting", ""),
                        lumens=fx_data.get("lumens", ""),
                        cct=fx_data.get("cct", ""),
                        dimming=fx_data.get("dimming", ""),
                        max_va=fx_data.get("max_va", ""),
                    )
                    fixtures.append(new_fixture)
                    existing_codes.add(code)
                    logger.info("[SCHEDULE] User hint: added %s", code)

        # Apply spec patches
        if hints.spec_patches:
            for f in fixtures:
                if f.code in hints.spec_patches:
                    patches = hints.spec_patches[f.code]
                    for field_name, value in patches.items():
                        if hasattr(f, field_name):
                            setattr(f, field_name, value)
                            logger.info(
                                "[SCHEDULE] User hint: patched %s.%s = %s",
                                f.code, field_name, value,
                            )

    fixture_codes = [f.code for f in fixtures]

    logger.info(
        "[SCHEDULE] Extracted %d unique fixture types: %s",
        len(fixtures),
        fixture_codes,
    )

    # --- Save results ---
    result = {
        "fixtures": [f.model_dump(mode="json") for f in fixtures],
        "fixture_codes": fixture_codes,
        "found_plan_codes": sorted(found_plan_codes),
    }

    out_file = work_path / "schedule_result.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str)

    logger.info("[SCHEDULE] Results saved to %s", out_file)

    # Print summary
    print(f"\n=== SCHEDULE AGENT RESULTS ===")
    print(f"Fixture types extracted: {len(fixtures)}")
    for f in fixtures:
        print(f"  {f.code}: {f.description[:60]}")
    print(f"Results saved to: {out_file}")

    return result


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(
            "Usage: python -m medina.team.run_schedule <source> <work_dir>"
        )
        sys.exit(1)
    run(sys.argv[1], sys.argv[2])
