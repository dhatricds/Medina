"""Schedule Agent: Extract fixture schedule tables (Stage 4).

Like the estimator reading the luminaire schedule table, creating
inventory entries with specs (code, description, voltage, etc.).

Strategy: pdfplumber-first (accurate text extraction), VLM-fallback
(handles non-standard formats, rasterized PDFs).  VLM is tried on
any schedule page where pdfplumber finds 0 valid fixtures.

Usage:
    uv run python -m medina.team.run_schedule <source> <work_dir>
"""

from __future__ import annotations

import base64
import io
import json
import logging
import re
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("medina.team.schedule")


# Header words that should never be treated as fixture codes.
_HEADER_WORDS = frozenset({
    "SCHEDULE", "SCHEDULES", "LUMINAIRE", "FIXTURE", "FIXTURES",
    "LIGHTING", "TYPE", "DESCRIPTION", "MARK", "SYMBOL", "CATALOG",
    "MOUNTING", "VOLTAGE", "DIMMING", "WATTS", "WATTAGE",
    "NO", "NO.", "#", "QTY", "QUANTITY", "CKT", "CIRCUIT",
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


_MAX_VLM_PIXEL = 8000  # Max dimension for VLM APIs


def _render_for_vlm(
    source_path: Path,
    pdf_page_index: int,
    config,
    source_key: str = "",
    project_id: str = "",
) -> tuple[bytes, int]:
    """Render a page image sized for VLM API limits.

    Returns (image_bytes, actual_dpi).
    """
    from medina.pdf.renderer import render_page_to_image
    from PIL import Image

    sched_render_dpi = 200
    try:
        from medina.runtime_params import get_param
        sched_render_dpi = get_param(
            "schedule_render_dpi", source_key=source_key, project_id=project_id,
        )
    except Exception:
        pass
    dpi = min(config.render_dpi, sched_render_dpi)

    img_bytes = render_page_to_image(source_path, pdf_page_index, dpi=dpi)
    b64_size = len(base64.b64encode(img_bytes))
    img = Image.open(io.BytesIO(img_bytes))
    max_dim = max(img.size)

    while (b64_size > 5_000_000 or max_dim > _MAX_VLM_PIXEL) and dpi > 72:
        dpi = max(72, dpi - 20)
        img_bytes = render_page_to_image(source_path, pdf_page_index, dpi=dpi)
        b64_size = len(base64.b64encode(img_bytes))
        img = Image.open(io.BytesIO(img_bytes))
        max_dim = max(img.size)

    return img_bytes, dpi


def _try_vlm_extraction(
    page,
    pdf_pages: dict,
    config,
    found_plan_codes: set[str],
    source_key: str = "",
    project_id: str = "",
) -> list:
    """Try VLM extraction on a single page. Returns list of fixtures or []."""
    from medina.schedule.vlm_extractor import extract_schedule_vlm

    spdf = pdf_pages.get(page.page_number)
    if spdf is None:
        return []

    label = page.sheet_code or str(page.page_number)
    try:
        img_bytes, actual_dpi = _render_for_vlm(
            page.source_path, page.pdf_page_index,
            config, source_key, project_id,
        )
        from PIL import Image
        img = Image.open(io.BytesIO(img_bytes))
        b64_size = len(base64.b64encode(img_bytes))
        logger.info(
            "[SCHEDULE] VLM render: %s at %d DPI, %dx%d px, %.1f MB",
            label, actual_dpi, img.size[0], img.size[1],
            b64_size / 1_000_000,
        )
        vlm_fixtures = extract_schedule_vlm(
            page, img_bytes, config,
            plan_codes_hint=(
                found_plan_codes if found_plan_codes else None
            ),
        )
        if vlm_fixtures:
            logger.info(
                "[SCHEDULE] VLM extracted %d fixtures from %s: %s",
                len(vlm_fixtures), label,
                [f.code for f in vlm_fixtures],
            )
        return vlm_fixtures
    except Exception as e:
        logger.warning("[SCHEDULE] VLM failed for %s: %s", label, e)
        return []


def run(source: str, work_dir: str, hints=None, source_key: str = "", project_id: str = "") -> dict:
    """Run stage 4: SCHEDULE EXTRACTION."""
    from medina.pdf.loader import load
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

    # Use page classifications from search_result.json (preserves VLM
    # fallback classifications that text-based re-classification would lose).
    pages = [PageInfo.model_validate(p) for p in search_data["pages"]]

    # Build a map from page_number to the search-agent's classification.
    search_type_map: dict[int, PageType] = {
        p.page_number: p.page_type for p in pages
    }

    # Apply search classifications to the loaded pages (which have pdf
    # page objects attached for pdfplumber access).
    for p in pages_raw:
        if p.page_number in search_type_map:
            p.page_type = search_type_map[p.page_number]

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

    config = get_config()

    # ── Step 1: Extract fixture codes from plan pages (for cross-reference) ──
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

    # ── Step 2: pdfplumber extraction (primary — accurate text) ──
    fixtures = []
    if schedule_pages:
        fixtures = parse_all_schedules(schedule_pages, pdf_pages)
        if fixtures:
            logger.info(
                "[SCHEDULE] pdfplumber extracted %d fixtures: %s",
                len(fixtures),
                [f.code for f in fixtures],
            )

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

    # ── Step 3: Filter invalid fixture codes ──
    before_filter = len(fixtures)
    fixtures = [f for f in fixtures if _is_valid_fixture_code(f.code)]
    if before_filter > len(fixtures):
        logger.info(
            "[SCHEDULE] Filtered out %d invalid fixture code(s)",
            before_filter - len(fixtures),
        )

    # ── Step 4: VLM fallback when pdfplumber found 0 ──
    # Also pre-screen schedule pages to identify luminaire vs panel schedule.
    # Include plan pages as VLM candidates when they have embedded schedule
    # tables that pdfplumber couldn't parse (combo pages).
    vlm_candidate_pages = list(schedule_pages)
    if not fixtures and plan_pages and config.has_vlm_key:
        # Plan pages with embedded schedule tables are VLM candidates too
        vlm_candidate_pages.extend(plan_pages)
    if not fixtures and vlm_candidate_pages and config.has_vlm_key:
        luminaire_candidates = list(vlm_candidate_pages)

        # Pre-screen when multiple schedule pages exist
        if len(vlm_candidate_pages) > 1:
            from medina.schedule.vlm_extractor import check_schedule_type_vlm
            from medina.pdf.renderer import render_page_to_image

            screened: list = []
            for spage in vlm_candidate_pages:
                spdf = pdf_pages.get(spage.page_number)
                if spdf is None:
                    continue
                label = spage.sheet_code or str(spage.page_number)
                try:
                    screen_img = render_page_to_image(
                        spage.source_path, spage.pdf_page_index, dpi=100,
                    )
                    stype = check_schedule_type_vlm(spage, screen_img, config)
                    if stype in ("luminaire", "mixed", "unknown"):
                        screened.append(spage)
                    else:
                        logger.info(
                            "[SCHEDULE] Skipping %s — VLM identified as %s schedule",
                            label, stype,
                        )
                except Exception as e:
                    logger.warning(
                        "[SCHEDULE] Pre-screen failed for %s: %s — keeping it",
                        label, e,
                    )
                    screened.append(spage)
            if screened:
                luminaire_candidates = screened

        # Try VLM on each candidate
        for spage in luminaire_candidates:
            label = spage.sheet_code or str(spage.page_number)
            logger.info(
                "[SCHEDULE] pdfplumber found 0 — trying VLM on %s", label,
            )
            vlm_fixtures = _try_vlm_extraction(
                spage, pdf_pages, config, found_plan_codes,
                source_key, project_id,
            )
            fixtures.extend(vlm_fixtures)

    # ── Step 5: Cross-reference against plan page codes ──
    if fixtures and found_plan_codes:
        from medina.schedule.vlm_extractor import crossref_vlm_codes
        fixtures = crossref_vlm_codes(fixtures, found_plan_codes)

    # ── Step 6: Filter and deduplicate ──
    # Filter again after cross-reference
    fixtures = [f for f in fixtures if _is_valid_fixture_code(f.code)]

    seen: set[str] = set()
    deduped = []
    for f in fixtures:
        if f.code not in seen:
            seen.add(f.code)
            deduped.append(f)
    fixtures = deduped

    # ── Step 7: Apply user feedback hints ──
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
