"""Count fixture occurrences on lighting plan pages using text extraction."""

from __future__ import annotations

import logging
import re
from typing import Any

from medina.exceptions import FixtureCountError
from medina.models import PageInfo

logger = logging.getLogger(__name__)

# Fraction of page dimensions used for exclusion zones.
_TITLE_BLOCK_X_FRAC = 0.80  # Title block starts at rightmost 20%
_TITLE_BLOCK_Y_FRAC = 0.85  # Title block starts at bottom 15%
_BORDER_FRAC = 0.02          # 2% border on all sides


def _build_code_pattern(code: str) -> re.Pattern[str]:
    """Build a regex pattern that matches a fixture code with word boundaries.

    Handles variations like "A1", "(A1)", "A-1", and ensures "A1" does not
    match inside "A10" or "EA1".
    """
    # Escape the code for regex safety, then allow an optional hyphen
    # between the letter(s) and digit(s).
    m = re.match(r'^([A-Za-z]+)(\d+)$', code)
    if m:
        letters, digits = m.group(1), m.group(2)
        escaped = re.escape(letters) + r'-?' + re.escape(digits)
    else:
        escaped = re.escape(code)

    # Use word boundaries but also allow the code to be wrapped in parens
    # or brackets, which is common on electrical drawings.
    return re.compile(
        r'(?<![A-Za-z0-9])' + escaped + r'(?![A-Za-z0-9])',
        re.IGNORECASE,
    )


def _is_in_exclusion_zone(
    x: float,
    y: float,
    page_width: float,
    page_height: float,
) -> bool:
    """Check whether a coordinate falls inside an exclusion zone.

    Exclusion zones:
    - Title block: rightmost 20% AND bottom 15% (the corner box)
    - Border: outermost 2% on all four sides
    """
    # Border exclusion
    min_x = page_width * _BORDER_FRAC
    max_x = page_width * (1 - _BORDER_FRAC)
    min_y = page_height * _BORDER_FRAC
    max_y = page_height * (1 - _BORDER_FRAC)
    if x < min_x or x > max_x or y < min_y or y > max_y:
        return True

    # Title block exclusion (bottom-right corner)
    if x > page_width * _TITLE_BLOCK_X_FRAC and y > page_height * _TITLE_BLOCK_Y_FRAC:
        return True

    return False


_SCHEDULE_TABLE_KEYWORDS = [
    "luminaire", "fixture", "mark", "lamp", "lumen",
    "voltage", "mounting", "watt",
]


def _find_schedule_table_bbox(
    pdf_page: Any,
) -> tuple[float, float, float, float] | None:
    """Find the bounding box of a luminaire/fixture schedule table on the page.

    Scans all tables and picks the one with the most schedule-specific header
    keywords (MARK, LUMINAIRE, FIXTURE, etc.). Requires at least 3 matches
    to avoid false positives from notes sections that mention fixtures.
    """
    try:
        tables = pdf_page.find_tables(table_settings={
            "vertical_strategy": "lines",
            "horizontal_strategy": "lines",
            "snap_tolerance": 5,
            "join_tolerance": 5,
        })
    except Exception:
        return None

    if not tables:
        return None

    best_bbox = None
    best_matches = 0

    for table in tables:
        try:
            rows = table.extract()
        except Exception:
            continue
        if not rows:
            continue
        # Only check the header row (first row) — not data rows which
        # may contain fixture-related words in general notes.
        header_text = " ".join(
            str(cell).lower() for cell in rows[0] if cell
        )
        matches = sum(1 for kw in _SCHEDULE_TABLE_KEYWORDS if kw in header_text)
        if matches > best_matches:
            best_matches = matches
            best_bbox = table.bbox

    if best_matches >= 3:
        logger.debug(
            "Found schedule table on plan page (bbox: %s, %d keyword matches)",
            best_bbox, best_matches,
        )
        return best_bbox

    return None


def _is_in_bbox(
    x: float,
    y: float,
    bbox: tuple[float, float, float, float],
    margin: float = 2.0,
) -> bool:
    """Check whether a coordinate falls inside a bounding box."""
    x0, top, x1, bottom = bbox
    return (x0 - margin) <= x <= (x1 + margin) and (top - margin) <= y <= (bottom + margin)


def _extract_plan_words(
    pdf_page: Any,
) -> list[dict[str, Any]]:
    """Extract words from a pdfplumber page, filtering out exclusion zones.

    Filters out:
    - Title block (bottom-right corner)
    - Border area (outermost 2%)
    - Luminaire schedule table (if embedded in the plan page)

    Returns a list of word dicts with keys: text, x0, top, x1, bottom.
    """
    page_width = pdf_page.width
    page_height = pdf_page.height

    words = pdf_page.extract_words(
        x_tolerance=3,
        y_tolerance=3,
        keep_blank_chars=False,
    )

    schedule_bbox = _find_schedule_table_bbox(pdf_page)

    filtered: list[dict[str, Any]] = []
    for w in words:
        cx = (w["x0"] + w["x1"]) / 2
        cy = (w["top"] + w["bottom"]) / 2
        if _is_in_exclusion_zone(cx, cy, page_width, page_height):
            continue
        if schedule_bbox and _is_in_bbox(cx, cy, schedule_bbox):
            continue
        filtered.append(w)

    return filtered


_CROSSREF_WORDS = {"see", "sheet", "refer", "reference", "plan", "dwg", "drawing"}


def _count_word_matches_filtered(
    words: list[dict[str, Any]],
    code: str,
    pattern: re.Pattern[str],
    is_sheet_code: bool,
) -> int:
    """Count per-word matches, filtering out cross-reference context.

    For fixture codes that also match a plan sheet code, only count
    occurrences that are NOT preceded by cross-reference words like
    "SEE", "SHEET", "REFER TO", etc.
    """
    count = 0
    for i, w in enumerate(words):
        if not pattern.fullmatch(w["text"].strip("()[]")):
            continue
        if is_sheet_code:
            # Check preceding word(s) for cross-reference indicators.
            skip = False
            for lookback in range(1, min(4, i + 1)):
                prev_text = words[i - lookback]["text"].lower().strip(".,;:()")
                if prev_text in _CROSSREF_WORDS:
                    skip = True
                    break
            if skip:
                continue
        count += 1
    return count


def count_fixtures_on_plan(
    page_info: PageInfo,
    pdf_page: Any,
    fixture_codes: list[str],
    plan_sheet_codes: list[str] | None = None,
) -> dict[str, int]:
    """Count occurrences of each fixture code on a single lighting plan page.

    Args:
        page_info: Page metadata.
        pdf_page: pdfplumber page object.
        fixture_codes: List of fixture type codes to search for
            (e.g., ``["A1", "B6", "D7"]``).
        plan_sheet_codes: Optional list of known plan sheet codes. Fixture
            codes that match a sheet code get extra filtering to avoid
            counting cross-reference labels (e.g., "SEE E1A").

    Returns:
        Dict mapping fixture_code to count on this specific page.

    Raises:
        FixtureCountError: If text extraction fails critically.
    """
    sheet = page_info.sheet_code or f"page_{page_info.page_number}"
    logger.info("Counting fixtures on plan %s (page %d)", sheet, page_info.page_number)

    if not fixture_codes:
        logger.warning("No fixture codes provided for plan %s", sheet)
        return {}

    sheet_code_set = {c.upper() for c in (plan_sheet_codes or [])}

    try:
        words = _extract_plan_words(pdf_page)
    except Exception as exc:
        raise FixtureCountError(
            f"Failed to extract text from plan {sheet}: {exc}"
        ) from exc

    if not words:
        logger.warning(
            "No text elements found on plan %s after exclusion filtering", sheet
        )
        return {code: 0 for code in fixture_codes}

    counts: dict[str, int] = {}
    for code in fixture_codes:
        pattern = _build_code_pattern(code)
        is_sheet_code = code.upper() in sheet_code_set

        # Per-word matching with cross-reference filtering.
        word_count = _count_word_matches_filtered(
            words, code, pattern, is_sheet_code,
        )

        if not is_sheet_code:
            # Also try concatenated text match (catches codes split across
            # word elements). Only for non-sheet-code fixtures since we
            # can't do context filtering on concatenated text.
            all_text = " ".join(w["text"] for w in words)
            text_count = len(pattern.findall(all_text))
            final_count = max(text_count, word_count)
        else:
            final_count = word_count

        counts[code] = final_count

        if final_count > 0:
            logger.debug(
                "Plan %s: fixture %s found %d times%s",
                sheet, code, final_count,
                " (sheet-code filtered)" if is_sheet_code else "",
            )

    total = sum(counts.values())
    logger.info(
        "Plan %s: found %d total fixture instances across %d types",
        sheet, total, sum(1 for c in counts.values() if c > 0),
    )
    return counts


def count_all_plans(
    plan_pages: list[PageInfo],
    pdf_pages: dict[int, Any],
    fixture_codes: list[str],
    plan_sheet_codes: list[str] | None = None,
) -> dict[str, dict[str, int]]:
    """Count fixtures on all lighting plan pages.

    Args:
        plan_pages: List of page metadata for lighting plan pages.
        pdf_pages: Mapping of page_number to pdfplumber page object.
        fixture_codes: Fixture type codes to search for.
        plan_sheet_codes: Optional list of known plan sheet codes for
            cross-reference filtering.

    Returns:
        ``{sheet_code: {fixture_code: count}}`` for every plan page.
    """
    results: dict[str, dict[str, int]] = {}

    for page_info in plan_pages:
        sheet = page_info.sheet_code or f"page_{page_info.page_number}"
        pdf_page = pdf_pages.get(page_info.page_number)
        if pdf_page is None:
            logger.warning(
                "No PDF page object for plan %s (page %d), skipping",
                sheet, page_info.page_number,
            )
            results[sheet] = {code: 0 for code in fixture_codes}
            continue

        try:
            counts = count_fixtures_on_plan(
                page_info, pdf_page, fixture_codes,
                plan_sheet_codes=plan_sheet_codes,
            )
        except FixtureCountError:
            logger.exception("Error counting fixtures on plan %s", sheet)
            counts = {code: 0 for code in fixture_codes}

        results[sheet] = counts

    return results
