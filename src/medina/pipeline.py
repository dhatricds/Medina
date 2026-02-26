"""Pipeline orchestrator — wires all 7 stages together."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from medina.config import MedinaConfig, get_config
from medina.models import (
    ExtractionResult,
    FixtureRecord,
    KeyNote,
    PageInfo,
    PageType,
    SheetIndexEntry,
)

logger = logging.getLogger(__name__)


def run_pipeline(
    source: str | Path,
    config: MedinaConfig | None = None,
    use_vision: bool = False,
    progress_callback: Any = None,
) -> ExtractionResult:
    """Run the full extraction pipeline on a PDF or folder.

    Args:
        source: Path to a PDF file or folder of PDFs.
        config: Optional configuration override.
        use_vision: Whether to use vision API for counting.
        progress_callback: Optional callable(stage, message) for progress updates.

    Returns:
        ExtractionResult with all extracted data and QA report.
    """
    if config is None:
        config = get_config()

    source = Path(source)
    project_name = source.stem if source.is_file() else source.name

    def report(stage: str, msg: str) -> None:
        logger.info("[%s] %s", stage, msg)
        if progress_callback:
            progress_callback(stage, msg)

    # --- Stage 1: LOAD ---
    report("LOAD", f"Loading from {source}")
    from medina.pdf.loader import load
    pages, pdf_pages = load(source)
    report("LOAD", f"Loaded {len(pages)} pages")

    # --- Stage 2: DISCOVER ---
    report("DISCOVER", "Searching for sheet index...")
    from medina.pdf.sheet_index import discover_sheet_index
    sheet_index = discover_sheet_index(pages, pdf_pages)
    report("DISCOVER", f"Found {len(sheet_index)} sheet index entries")

    # --- Stage 3: CLASSIFY ---
    report("CLASSIFY", "Classifying pages...")
    from medina.pdf.classifier import classify_pages
    pages = classify_pages(pages, pdf_pages, sheet_index)

    plan_pages_info = [
        p for p in pages if p.page_type == PageType.LIGHTING_PLAN
    ]
    schedule_pages_info = [
        p for p in pages if p.page_type == PageType.SCHEDULE
    ]
    plan_codes = [p.sheet_code for p in plan_pages_info if p.sheet_code]
    schedule_codes = [
        p.sheet_code for p in schedule_pages_info if p.sheet_code
    ]

    report(
        "CLASSIFY",
        f"Found {len(plan_pages_info)} lighting plans, "
        f"{len(schedule_pages_info)} schedule pages",
    )

    # --- VLM Classification Fallback ---
    # When no sheet index exists and we're missing plan or schedule pages,
    # use Claude Vision to classify unidentified pages.
    if (
        not sheet_index
        and (not plan_pages_info or not schedule_pages_info)
        and config.has_vlm_key
    ):
        vlm_candidates = [
            p for p in pages
            if p.page_type in (
                PageType.OTHER, PageType.POWER_PLAN, PageType.DETAIL,
            )
        ]
        if vlm_candidates:
            report(
                "CLASSIFY",
                f"No sheet index — running VLM fallback on "
                f"{len(vlm_candidates)} candidate page(s)...",
            )
            try:
                from medina.pdf.vlm_classifier import classify_pages_vlm
                vlm_results = classify_pages_vlm(
                    vlm_candidates, config,
                )
                for page in pages:
                    if page.page_number in vlm_results:
                        vlm_types = vlm_results[page.page_number]
                        # LIGHTING_PLAN priority — combo extraction
                        # handles the schedule part
                        if PageType.LIGHTING_PLAN in vlm_types:
                            page.page_type = PageType.LIGHTING_PLAN
                        elif PageType.SCHEDULE in vlm_types:
                            page.page_type = PageType.SCHEDULE
                # Refresh lists after VLM reclassification
                plan_pages_info = [
                    p for p in pages
                    if p.page_type == PageType.LIGHTING_PLAN
                ]
                schedule_pages_info = [
                    p for p in pages
                    if p.page_type == PageType.SCHEDULE
                ]
                plan_codes = [
                    p.sheet_code for p in plan_pages_info
                    if p.sheet_code
                ]
                schedule_codes = [
                    p.sheet_code for p in schedule_pages_info
                    if p.sheet_code
                ]
                report(
                    "CLASSIFY",
                    f"After VLM: {len(plan_pages_info)} lighting plans, "
                    f"{len(schedule_pages_info)} schedule pages",
                )
            except Exception as e:
                logger.warning("VLM classification fallback failed: %s", e)

    # --- Stage 4: SCHEDULE EXTRACTION ---
    report("SCHEDULE", "Extracting fixture schedules...")
    fixtures: list[FixtureRecord] = []
    if schedule_pages_info:
        from medina.schedule.parser import parse_all_schedules
        fixtures = parse_all_schedules(schedule_pages_info, pdf_pages)

    # Combo page: also check plan pages for embedded schedule tables.
    # This is safe because _is_luminaire_table() in parser.py filters
    # non-luminaire tables, and deduplication below handles overlaps.
    if plan_pages_info:
        from medina.schedule.parser import parse_all_schedules
        combo_fixtures = parse_all_schedules(plan_pages_info, pdf_pages)
        if combo_fixtures:
            report(
                "SCHEDULE",
                f"Found {len(combo_fixtures)} fixture type(s) on "
                f"plan page(s) (combo page)",
            )
            fixtures.extend(combo_fixtures)

    # Pre-extract fixture codes from plan pages (used as VLM hints
    # and for cross-referencing after extraction).
    found_plan_codes: set[str] = set()
    if plan_pages_info:
        from medina.schedule.vlm_extractor import (
            extract_plan_fixture_codes,
        )
        plan_pdf_pages = {
            p.page_number: pdf_pages[p.page_number]
            for p in plan_pages_info
            if p.page_number in pdf_pages
        }
        found_plan_codes = extract_plan_fixture_codes(plan_pdf_pages)
        if found_plan_codes:
            report(
                "SCHEDULE",
                f"Found {len(found_plan_codes)} fixture codes on "
                f"plan pages: {sorted(found_plan_codes)}",
            )

    # VLM fallback: if pdfplumber found no fixtures, try VLM.
    # Prefer dedicated schedule pages; if none exist, try plan pages
    # (combo pages may have embedded image-based schedule tables).
    vlm_sched_candidates = (
        schedule_pages_info if schedule_pages_info else plan_pages_info
    )
    if not fixtures and vlm_sched_candidates and config.has_vlm_key:
        from medina.schedule.vlm_extractor import (
            extract_schedule_vlm,
        )
        from medina.pdf.renderer import render_page_to_image

        for spage in vlm_sched_candidates:
            spdf = pdf_pages.get(spage.page_number)
            if spdf is None:
                continue

            sheet_label = (
                spage.sheet_code or str(spage.page_number)
            )
            report(
                "SCHEDULE",
                f"pdfplumber found 0 fixtures on {sheet_label} "
                f"— trying VLM fallback",
            )
            try:
                # Use higher DPI for schedule pages — fixture
                # codes like AL1 vs A1 need clear resolution.
                # Start at 200 DPI and reduce if too large.
                sched_dpi = min(config.render_dpi, 200)
                img_bytes = render_page_to_image(
                    spage.source_path,
                    spage.pdf_page_index,
                    dpi=sched_dpi,
                )
                # Check base64 size and reduce DPI if needed
                import base64
                b64_size = len(base64.b64encode(img_bytes))
                while b64_size > 5_000_000 and sched_dpi > 72:
                    sched_dpi = max(72, sched_dpi - 20)
                    logger.info(
                        "Image too large (%d bytes), "
                        "retrying at %d DPI",
                        b64_size, sched_dpi,
                    )
                    img_bytes = render_page_to_image(
                        spage.source_path,
                        spage.pdf_page_index,
                        dpi=sched_dpi,
                    )
                    b64_size = len(
                        base64.b64encode(img_bytes)
                    )
                vlm_fixtures = extract_schedule_vlm(
                    spage, img_bytes, config,
                    plan_codes_hint=(
                        found_plan_codes if found_plan_codes
                        else None
                    ),
                )
                fixtures.extend(vlm_fixtures)
                report(
                    "SCHEDULE",
                    f"VLM extracted {len(vlm_fixtures)} fixture "
                    f"types from {sheet_label}",
                )
            except Exception as e:
                logger.warning(
                    "VLM schedule extraction failed for %s: %s",
                    sheet_label,
                    e,
                )
                report(
                    "SCHEDULE",
                    f"VLM extraction failed for {sheet_label}: {e}",
                )

    report("SCHEDULE", f"Extracted {len(fixtures)} fixture types")

    # Cross-reference VLM-extracted codes against plan page text.
    # This corrects misread codes (e.g., "A1" -> "AL1") by checking
    # what codes actually appear on the lighting plan pages.
    if fixtures and found_plan_codes:
        from medina.schedule.vlm_extractor import crossref_vlm_codes
        fixtures = crossref_vlm_codes(fixtures, found_plan_codes)
        report(
            "SCHEDULE",
            f"Cross-referenced codes against {len(found_plan_codes)} "
            f"plan codes",
        )

    # Deduplicate fixtures by code (keep the first occurrence)
    seen_codes: set[str] = set()
    deduped: list[FixtureRecord] = []
    for f in fixtures:
        if f.code not in seen_codes:
            seen_codes.add(f.code)
            deduped.append(f)
        else:
            logger.info("Removing duplicate fixture code: %s", f.code)
    if len(deduped) < len(fixtures):
        report(
            "SCHEDULE",
            f"Removed {len(fixtures) - len(deduped)} duplicate "
            f"fixture code(s)",
        )
    fixtures = deduped

    fixture_codes = [f.code for f in fixtures]

    # --- Stage 5: COUNT (per-plan) ---
    report("COUNT", "Counting fixtures on lighting plans...")
    all_plan_counts: dict[str, dict[str, int]] = {}
    all_keynote_counts: dict[str, dict[str, int]] = {}
    all_keynotes: list[KeyNote] = []

    all_plan_positions: dict = {}
    all_keynote_positions: dict = {}

    if plan_pages_info and fixture_codes:
        # Always run text-based counting
        from medina.plans.text_counter import count_all_plans
        counts_result = count_all_plans(
            plan_pages_info, pdf_pages, fixture_codes,
            return_positions=True,
        )
        if isinstance(counts_result, tuple):
            all_plan_counts, all_plan_positions = counts_result
        else:
            all_plan_counts = counts_result

        # Vision-based counting — triggers when:
        #   1. User explicitly requested --use-vision, OR
        #   2. Any single-char fixture codes exist (unreliable with text)
        has_short_codes = any(len(fc) == 1 for fc in fixture_codes)
        if has_short_codes and not use_vision:
            short_list = [fc for fc in fixture_codes if len(fc) == 1]
            report(
                "COUNT",
                f"Short fixture codes {short_list} — auto-triggering VLM recount",
            )
        should_run_vlm = (use_vision or has_short_codes) and config.has_vlm_key
        if should_run_vlm:
            report("COUNT", "Running vision-based counting (VLM)...")
            try:
                from medina.pdf.renderer import render_page_to_image
                from medina.plans.vision_counter import (
                    count_all_plans_vision,
                )

                # Use lower DPI for VLM (8000px API limit).
                vision_dpi = min(config.render_dpi, 150)

                # Render all plan pages to images
                page_images: dict[int, bytes] = {}
                for pinfo in plan_pages_info:
                    code = pinfo.sheet_code or str(pinfo.page_number)
                    try:
                        img_bytes = render_page_to_image(
                            pinfo.source_path,
                            pinfo.pdf_page_index,
                            dpi=vision_dpi,
                        )
                        page_images[pinfo.page_number] = img_bytes
                        report("COUNT", f"Rendered {code} for vision")
                    except Exception as e:
                        logger.warning(
                            "Render failed for %s: %s", code, e
                        )

                # Run vision counting on all plans
                vision_counts = count_all_plans_vision(
                    plan_pages_info, page_images,
                    fixture_codes, config,
                )

                # Smart merge:
                # - Single-char codes: VLM helps when within ±2
                # - Multi-char codes: text is reliable, skip VLM
                _MERGE_TOLERANCE = 2
                for plan_code, v_counts in vision_counts.items():
                    t_counts = all_plan_counts.get(plan_code, {})
                    merged: dict[str, int] = {}
                    for fc in fixture_codes:
                        vc = v_counts.get(fc, 0)
                        tc = t_counts.get(fc, 0)
                        if len(fc) > 1:
                            merged[fc] = tc
                            continue
                        diff = abs(vc - tc)
                        if tc == 0 and vc > 0:
                            merged[fc] = vc
                        elif diff <= _MERGE_TOLERANCE:
                            merged[fc] = max(vc, tc)
                        else:
                            merged[fc] = tc
                    all_plan_counts[plan_code] = merged
                    logger.info(
                        "Merged text+vision for %s: %s",
                        plan_code, merged,
                    )

            except ImportError:
                logger.warning("Vision counter not available")
            except Exception as e:
                logger.warning("Vision counting failed: %s", e)

    # Count keynotes
    if plan_pages_info:
        report("COUNT", "Extracting keynotes...")
        from medina.plans.keynotes import extract_all_keynotes
        kn_result = extract_all_keynotes(
            plan_pages_info, pdf_pages, return_positions=True,
        )
        if len(kn_result) == 3:
            all_keynotes, all_keynote_counts, all_keynote_positions = kn_result
        else:
            all_keynotes, all_keynote_counts = kn_result[0], kn_result[1]

        # The text-based keynote counter uses geometric shape
        # detection (finds numbers inside diamond/hexagon shapes).
        # VLM fallback is only used when the text-based detection
        # found zero counts for all keynotes on a plan page.
        if config.has_vlm_key and all_keynotes:
            keynote_numbers = [
                str(kn.number) for kn in all_keynotes
            ]

            # Check if any plan has low keynote counts — triggers when
            # total count < number of keynotes (geometric/text detection
            # likely failed if each keynote isn't found at least once).
            plans_needing_vlm = []
            for pinfo in plan_pages_info:
                code = pinfo.sheet_code or str(pinfo.page_number)
                page_counts = all_keynote_counts.get(code, {})
                plan_kn_nums = [
                    n for n in page_counts
                    if page_counts.get(n) is not None
                ]
                total = sum(
                    page_counts.get(n, 0) for n in plan_kn_nums
                )
                num_kn = len(plan_kn_nums) or len(keynote_numbers)
                if total < num_kn:
                    plans_needing_vlm.append(pinfo)

            if plans_needing_vlm:
                report(
                    "COUNT",
                    f"VLM keynote fallback for "
                    f"{len(plans_needing_vlm)} plan(s)...",
                )
                try:
                    from medina.pdf.renderer import render_page_to_image
                    from medina.plans.vision_keynote_counter import (
                        count_keynotes_vision,
                    )

                    vlm_dpi = min(config.render_dpi, 200)

                    for pinfo in plans_needing_vlm:
                        code = (
                            pinfo.sheet_code
                            or str(pinfo.page_number)
                        )
                        try:
                            img_bytes = render_page_to_image(
                                pinfo.source_path,
                                pinfo.pdf_page_index,
                                dpi=vlm_dpi,
                            )
                            vlm_counts = count_keynotes_vision(
                                pinfo, img_bytes,
                                keynote_numbers, config,
                            )
                            all_keynote_counts[code] = vlm_counts
                            report(
                                "COUNT",
                                f"VLM keynote counts for {code}: "
                                f"{vlm_counts}",
                            )
                        except Exception as e:
                            logger.warning(
                                "VLM keynote counting failed "
                                "for %s: %s",
                                code, e,
                            )
                except ImportError:
                    logger.warning(
                        "VLM keynote counter not available"
                    )

    report("COUNT", f"Counted fixtures on {len(all_plan_counts)} plans")

    # --- Aggregate per-plan counts into fixtures ---
    for fixture in fixtures:
        fixture.counts_per_plan = {
            plan_code: plan_counts.get(fixture.code, 0)
            for plan_code, plan_counts in all_plan_counts.items()
        }
        fixture.total = sum(fixture.counts_per_plan.values())

    # Aggregate keynote counts
    for keynote in all_keynotes:
        keynote.counts_per_plan = {
            plan_code: kn_counts.get(str(keynote.number), 0)
            for plan_code, kn_counts in all_keynote_counts.items()
        }
        keynote.total = sum(keynote.counts_per_plan.values())

    # Build intermediate result
    result = ExtractionResult(
        source=project_name,
        sheet_index=sheet_index,
        pages=pages,
        fixtures=fixtures,
        keynotes=all_keynotes,
        schedule_pages=schedule_codes,
        plan_pages=plan_codes,
    )

    # --- Stage 6: QA ---
    report("QA", "Running QA verification...")
    from medina.qa.confidence import compute_confidence
    qa_report = compute_confidence(result, config.qa_confidence_threshold)
    result.qa_report = qa_report

    from medina.qa.report import format_qa_report
    qa_text = format_qa_report(qa_report, project_name)
    logger.info("\n%s", qa_text)
    report("QA", f"Confidence: {qa_report.overall_confidence:.1%}")

    # Attach position data for click-to-highlight (transient, not serialized)
    result._fixture_positions = all_plan_positions  # type: ignore[attr-defined]
    result._keynote_positions = all_keynote_positions  # type: ignore[attr-defined]

    # --- Stage 7: OUTPUT is handled by the caller ---
    report("DONE", "Pipeline complete")
    return result


def run_and_save(
    source: str | Path,
    output_path: str | Path,
    output_format: str = "both",
    config: MedinaConfig | None = None,
    use_vision: bool = False,
    progress_callback: Any = None,
) -> ExtractionResult:
    """Run pipeline and save output files."""
    result = run_pipeline(
        source, config, use_vision, progress_callback
    )

    output_path = Path(output_path)

    if output_format in ("excel", "both"):
        excel_path = output_path.with_suffix(".xlsx")
        from medina.output.excel import write_excel
        write_excel(result, excel_path)

    if output_format in ("json", "both"):
        json_path = output_path.with_suffix(".json")
        from medina.output.json_out import write_json
        write_json(result, json_path)

    # Write positions file for click-to-highlight
    fixture_pos = getattr(result, "_fixture_positions", {})
    keynote_pos = getattr(result, "_keynote_positions", {})
    if fixture_pos or keynote_pos:
        from medina.output.json_out import write_positions_json
        positions_path = Path(str(output_path) + "_positions.json")
        write_positions_json(fixture_pos, keynote_pos, positions_path)

    return result
