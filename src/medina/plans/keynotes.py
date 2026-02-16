"""Extract and count keynotes from lighting plan pages."""

from __future__ import annotations

import logging
import re
from typing import Any

from medina.exceptions import KeyNoteExtractionError
from medina.models import KeyNote, PageInfo

logger = logging.getLogger(__name__)

# Patterns to identify the keynotes section header.
_KEYNOTES_HEADER_PATTERNS = [
    re.compile(r'KEY\s*NOTES\s*:', re.IGNORECASE),
    re.compile(r'KEY\s*NOTES\b', re.IGNORECASE),
    re.compile(r'KEYED\s+SHEET\s+NOTES?\s*:', re.IGNORECASE),
    re.compile(r'KEYED\s+SHEET\s+NOTES?\b', re.IGNORECASE),
    re.compile(r'KEYED\s+NOTES\s*:', re.IGNORECASE),
    re.compile(r'KEYED\s+NOTES\b', re.IGNORECASE),
    re.compile(r'KEYNOTES\s*:', re.IGNORECASE),
    re.compile(r'KEYNOTES\b', re.IGNORECASE),
]

# Pattern to match a numbered keynote entry:
# "1. text", "1) text", "1 - text", or "1 text" (space-only separator).
_KEYNOTE_ENTRY_RE = re.compile(
    r'^\s*(\d+)\s*[.):\-]?\s+([A-Z].+)',
    re.MULTILINE,
)

# Pattern to match fixture code references in keynote text.
_FIXTURE_REF_RE = re.compile(
    r'(?:TYPE\s+|FIXTURE\s+)?([A-Z]{1,2}\d{1,2})\b',
    re.IGNORECASE,
)


def _find_keynotes_section(text: str) -> str | None:
    """Locate the KEY NOTES section within a page's text.

    Returns the text from the keynotes header to the end of the section
    (detected by blank lines, scale markers, or plan descriptions),
    or ``None`` if no keynotes section is found.
    """
    for pattern in _KEYNOTES_HEADER_PATTERNS:
        match = pattern.search(text)
        if match:
            remaining = text[match.start():]
            return _trim_section(remaining)
    return None


# Patterns that indicate the end of the keynotes section.
_SECTION_END_PATTERNS = [
    re.compile(r'^\d+/\d+"\s*=', re.MULTILINE),  # Scale: 3/16" = 1'-0"
    re.compile(r'^\s*[A-Z]{2,}\s+[A-Z]{2,}\s+[A-Z]{2,}\s+(LEVEL|PLAN|LAYOUT)', re.MULTILINE),
    re.compile(r'^\s*N\s+\d+$', re.MULTILINE),  # Sheet number like "N 105"
    re.compile(r'^\s*OF$', re.MULTILINE),  # Part of sheet numbering
]


def _trim_section(section_text: str) -> str:
    """Trim the keynotes section to remove trailing non-keynote content.

    Stops at the first line that looks like it's outside the keynotes
    section (scale markers, plan descriptions, etc.).
    """
    lines = section_text.split("\n")
    trimmed: list[str] = [lines[0]]  # Keep the header

    consecutive_non_entry = 0
    entry_started = False

    for line in lines[1:]:
        stripped = line.strip()

        # Check for section-end indicators.
        is_end = False
        for end_pattern in _SECTION_END_PATTERNS:
            if end_pattern.match(stripped):
                is_end = True
                break

        if is_end:
            break

        # Check if this line looks like a keynote entry or continuation.
        is_entry = bool(_KEYNOTE_ENTRY_RE.match(line))
        is_continuation = (
            not is_entry
            and stripped
            and entry_started
            and len(stripped) > 10
        )

        if is_entry:
            entry_started = True
            consecutive_non_entry = 0
            trimmed.append(line)
        elif is_continuation:
            consecutive_non_entry = 0
            trimmed.append(line)
        elif not stripped:
            # Blank line — could be end of section.
            consecutive_non_entry += 1
            if consecutive_non_entry >= 2 and entry_started:
                break
        else:
            consecutive_non_entry += 1
            if consecutive_non_entry >= 2 and entry_started:
                break

    return "\n".join(trimmed)


def _parse_keynote_entries(section_text: str) -> list[tuple[str, str]]:
    """Parse numbered keynote entries from the keynotes section text.

    Returns list of ``(number_str, keynote_text)`` tuples.
    Filters out false positives (unreasonable numbers, short text).
    """
    raw_entries: list[tuple[str, str]] = []
    lines = section_text.split("\n")

    current_num: str | None = None
    current_text_parts: list[str] = []

    for line in lines:
        entry_match = _KEYNOTE_ENTRY_RE.match(line)
        if entry_match:
            # Save previous entry if any.
            if current_num is not None:
                raw_entries.append((
                    current_num,
                    " ".join(current_text_parts).strip(),
                ))
            current_num = entry_match.group(1)
            current_text_parts = [entry_match.group(2).strip()]
        elif current_num is not None and line.strip():
            # Continuation line for the current keynote.
            current_text_parts.append(line.strip())

    # Save the last entry.
    if current_num is not None:
        raw_entries.append((
            current_num,
            " ".join(current_text_parts).strip(),
        ))

    # Filter: validate entries look like real keynotes.
    entries: list[tuple[str, str]] = []
    for num_str, text in raw_entries:
        # Keynote numbers are typically 1-99.
        try:
            num_val = int(num_str)
        except ValueError:
            continue
        if num_val > 99:
            logger.debug("Skipping keynote #%s: number too high", num_str)
            continue

        # Text should be meaningful (not just fixture codes or addresses).
        if len(text) < 15:
            logger.debug(
                "Skipping keynote #%s: text too short (%d chars)",
                num_str,
                len(text),
            )
            continue

        entries.append((num_str, text))

    return entries


def _find_fixture_references(
    keynote_text: str,
    known_codes: list[str] | None = None,
) -> list[str]:
    """Find fixture code references within a keynote's text.

    If ``known_codes`` is provided, only returns codes that are in the
    known list. Otherwise returns all matches.
    """
    matches = _FIXTURE_REF_RE.findall(keynote_text)
    refs = list(dict.fromkeys(m.upper() for m in matches))  # deduplicate
    if known_codes:
        known_upper = {c.upper() for c in known_codes}
        refs = [r for r in refs if r in known_upper]
    return refs


def _check_enclosed_by_shape(
    cx: float,
    cy: float,
    lines: list[Any],
    inner_r: float = 2.0,
    outer_r: float = 10.0,
) -> int:
    """Check if a point is enclosed by line endpoints in all quadrants.

    Keynote symbols (diamonds, hexagons, etc.) have line endpoints
    surrounding the number in all four quadrants. Returns the number
    of quadrants (0–4) that have nearby line endpoints.
    """
    import math

    quadrants: set[str] = set()
    for ln in lines:
        for px, py in [(ln["x0"], ln["top"]), (ln["x1"], ln["bottom"])]:
            dist = math.sqrt((px - cx) ** 2 + (py - cy) ** 2)
            if inner_r < dist < outer_r:
                dx = px - cx
                dy = py - cy
                if dx >= 0 and dy <= 0:
                    quadrants.add("TR")
                elif dx >= 0 and dy > 0:
                    quadrants.add("BR")
                elif dx < 0 and dy > 0:
                    quadrants.add("BL")
                elif dx < 0 and dy <= 0:
                    quadrants.add("TL")
            if len(quadrants) == 4:
                return 4
    return len(quadrants)


def _count_keynote_occurrences(
    pdf_page: Any,
    keynote_numbers: list[str],
    page_width: float,
    page_height: float,
) -> dict[str, int]:
    """Count keynote symbols on the plan using geometric shape detection.

    Keynote numbers on plans appear inside geometric shapes (diamonds,
    hexagons, triangles, circles). This function identifies them by
    detecting line endpoints that surround each candidate number in
    all four quadrants (top-right, bottom-right, bottom-left, top-left).

    Two-step filtering:
    1. High-confidence: numbers enclosed in all 4 quadrants (score=4)
    2. Include score=3 candidates IF their font height matches the
       modal font height from high-confidence candidates.
    """
    from collections import Counter

    counts: dict[str, int] = {n: 0 for n in keynote_numbers}
    if not keynote_numbers:
        return counts

    try:
        words = pdf_page.extract_words(
            x_tolerance=3,
            y_tolerance=3,
            keep_blank_chars=False,
        )
    except Exception:
        logger.warning("Failed to extract words for keynote counting")
        return counts

    lines = pdf_page.lines or []
    if not lines:
        logger.debug("No lines on page — falling back to text-only counting")
        return _count_keynote_text_only(
            words, keynote_numbers, page_width, page_height
        )

    # Filter for candidate keynote numbers in the drawing area.
    drawing_max_x = page_width * 0.70
    title_min_y = page_height * 0.90
    kn_set = set(keynote_numbers)

    candidates: list[dict[str, Any]] = []
    for w in words:
        text = w["text"].strip()
        if text not in kn_set:
            continue
        cx = (w["x0"] + w["x1"]) / 2
        cy = (w["top"] + w["bottom"]) / 2
        if cx > drawing_max_x or cy > title_min_y:
            continue

        q_count = _check_enclosed_by_shape(cx, cy, lines)
        font_h = round(w["bottom"] - w["top"], 1)
        candidates.append({
            "text": text,
            "quadrants": q_count,
            "font_h": font_h,
        })

    if not candidates:
        return counts

    # Step 1: Find modal font_h from high-confidence candidates.
    high_conf = [c for c in candidates if c["quadrants"] >= 4]
    if high_conf:
        font_counts = Counter(c["font_h"] for c in high_conf)
        modal_font_h = font_counts.most_common(1)[0][0]
    else:
        mid_conf = [c for c in candidates if c["quadrants"] >= 3]
        if mid_conf:
            font_counts = Counter(c["font_h"] for c in mid_conf)
            modal_font_h = font_counts.most_common(1)[0][0]
        else:
            # No geometric shapes detected — fall back to text-only.
            logger.debug(
                "No geometric keynote shapes detected — "
                "falling back to text-only counting"
            )
            return _count_keynote_text_only(
                words, keynote_numbers, page_width, page_height
            )

    # Step 2: Count candidates with >= 3 quadrants AND matching font_h.
    for c in candidates:
        if c["quadrants"] >= 3 and c["font_h"] == modal_font_h:
            counts[c["text"]] += 1

    return counts


def _count_keynote_text_only(
    words: list[Any],
    keynote_numbers: list[str],
    page_width: float,
    page_height: float,
) -> dict[str, int]:
    """Fallback: count keynote numbers by text matching only.

    Used when no geometric line data is available on the page.
    """
    counts: dict[str, int] = {n: 0 for n in keynote_numbers}
    kn_set = set(keynote_numbers)
    drawing_max_x = page_width * 0.70
    title_min_y = page_height * 0.90

    for w in words:
        cx = (w["x0"] + w["x1"]) / 2
        cy = (w["top"] + w["bottom"]) / 2
        if cx > drawing_max_x or cy > title_min_y:
            continue
        text = w["text"].strip()
        if text in kn_set:
            counts[text] += 1

    return counts


def _extract_keynotes_region_text(pdf_page: Any) -> str:
    """Extract text from the keynotes region of the page.

    Keynotes are typically in the right portion of the page
    (right ~30%), above the title block. We crop to this area
    to avoid mixing with drawing text from the left side.

    Falls back to full-page text if the cropped region yields nothing.
    """
    width = pdf_page.width
    height = pdf_page.height

    # Try right-side crop (keynotes legend area)
    # Typically right 30%, top 90% (avoiding title block)
    regions = [
        (width * 0.70, 0, width, height * 0.85),    # Right 30%, top 85%
        (width * 0.65, 0, width, height * 0.85),    # Right 35%, top 85%
        (width * 0.60, 0, width, height * 0.80),    # Right 40%, top 80%
    ]

    for bbox in regions:
        try:
            cropped = pdf_page.within_bbox(bbox)
            text = cropped.extract_text() or ""
        except Exception:
            continue

        if text and any(
            p.search(text) for p in _KEYNOTES_HEADER_PATTERNS
        ):
            logger.debug(
                "Keynotes found in cropped region "
                "(x0=%.0f, y0=%.0f, x1=%.0f, y1=%.0f)",
                *bbox,
            )
            return text

    # Fallback: use full page text
    try:
        return pdf_page.extract_text() or ""
    except Exception:
        return ""


def extract_keynotes_from_plan(
    page_info: PageInfo,
    pdf_page: Any,
    known_fixture_codes: list[str] | None = None,
) -> tuple[list[KeyNote], dict[str, int]]:
    """Extract keynotes and count their occurrences on a single plan page.

    Uses spatial extraction to isolate the keynotes legend area (right
    portion of the page) from the main drawing area.

    Args:
        page_info: Page metadata.
        pdf_page: pdfplumber page object.
        known_fixture_codes: Optional list of known fixture codes for
            matching references in keynote text.

    Returns:
        Tuple of ``(keynotes_list, counts_dict)`` where ``counts_dict``
        maps ``keynote_number -> count_on_this_page``.

    Raises:
        KeyNoteExtractionError: If extraction fails critically.
    """
    sheet = page_info.sheet_code or f"page_{page_info.page_number}"
    logger.info("Extracting keynotes from plan %s", sheet)

    try:
        region_text = _extract_keynotes_region_text(pdf_page)
    except Exception as exc:
        raise KeyNoteExtractionError(
            f"Failed to extract text from plan {sheet}: {exc}"
        ) from exc

    keynotes: list[KeyNote] = []
    counts: dict[str, int] = {}

    # Find the keynotes section.
    section_text = _find_keynotes_section(region_text)
    if section_text is None:
        logger.debug("No keynotes section found on plan %s", sheet)
        return keynotes, counts

    # Parse numbered entries.
    entries = _parse_keynote_entries(section_text)
    if not entries:
        logger.debug(
            "Keynotes header found but no numbered entries on plan %s", sheet
        )
        return keynotes, counts

    logger.info("Found %d keynote entries on plan %s", len(entries), sheet)

    keynote_numbers = [num for num, _text in entries]

    # Count occurrences of keynote numbers on the drawing.
    page_width = pdf_page.width
    page_height = pdf_page.height
    counts = _count_keynote_occurrences(
        pdf_page, keynote_numbers, page_width, page_height
    )

    # Build KeyNote objects.
    for num, text in entries:
        refs = _find_fixture_references(text, known_fixture_codes)
        keynote = KeyNote(
            number=num,
            text=text,
            counts_per_plan={sheet: counts.get(num, 0)},
            total=counts.get(num, 0),
            fixture_references=refs,
        )
        keynotes.append(keynote)

        if counts.get(num, 0) > 0:
            logger.debug(
                "Plan %s: keynote %s appears %d times",
                sheet, num, counts[num],
            )

    return keynotes, counts


def extract_all_keynotes(
    plan_pages: list[PageInfo],
    pdf_pages: dict[int, Any],
    known_fixture_codes: list[str] | None = None,
) -> tuple[list[KeyNote], dict[str, dict[str, int]]]:
    """Extract keynotes from all plan pages and merge results.

    Keynotes with the same number across different plans are merged into
    a single ``KeyNote`` object with per-plan counts.

    Args:
        plan_pages: List of page metadata for lighting plan pages.
        pdf_pages: Mapping of page_number to pdfplumber page object.
        known_fixture_codes: Optional list of known fixture codes.

    Returns:
        Tuple of ``(merged_keynotes, all_counts)`` where
        ``all_counts = {sheet_code: {keynote_number: count}}``.
    """
    # Merged keynotes keyed by number (as string).
    merged: dict[str, KeyNote] = {}
    all_counts: dict[str, dict[str, int]] = {}

    for page_info in plan_pages:
        sheet = page_info.sheet_code or f"page_{page_info.page_number}"
        pdf_page = pdf_pages.get(page_info.page_number)
        if pdf_page is None:
            logger.warning(
                "No PDF page object for plan %s (page %d), skipping keynotes",
                sheet, page_info.page_number,
            )
            all_counts[sheet] = {}
            continue

        try:
            page_keynotes, page_counts = extract_keynotes_from_plan(
                page_info, pdf_page, known_fixture_codes
            )
        except KeyNoteExtractionError:
            logger.exception("Error extracting keynotes from plan %s", sheet)
            all_counts[sheet] = {}
            continue

        all_counts[sheet] = page_counts

        # Merge keynotes: if the same number already exists, update its
        # per-plan counts and accumulate fixture references.
        for kn in page_keynotes:
            num_str = str(kn.number)
            if num_str in merged:
                existing = merged[num_str]
                existing.counts_per_plan[sheet] = kn.counts_per_plan.get(
                    sheet, 0
                )
                existing.total = sum(existing.counts_per_plan.values())
                # Merge fixture references (deduplicate).
                for ref in kn.fixture_references:
                    if ref not in existing.fixture_references:
                        existing.fixture_references.append(ref)
                # Use the longer text if they differ (more complete).
                if len(kn.text) > len(existing.text):
                    existing.text = kn.text
            else:
                merged[num_str] = kn

    # Ensure all merged keynotes have entries for all plans (0 if absent).
    all_sheets = [
        p.sheet_code or f"page_{p.page_number}" for p in plan_pages
    ]
    for kn in merged.values():
        for sheet in all_sheets:
            if sheet not in kn.counts_per_plan:
                kn.counts_per_plan[sheet] = 0
        kn.total = sum(kn.counts_per_plan.values())

    # Sort by keynote number.
    sorted_keynotes = sorted(
        merged.values(),
        key=lambda k: (int(k.number) if str(k.number).isdigit() else 0),
    )

    logger.info(
        "Extracted %d unique keynotes across %d plan pages",
        len(sorted_keynotes), len(plan_pages),
    )
    return sorted_keynotes, all_counts
