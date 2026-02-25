"""Detect and split multi-viewport pages into separate sub-plans.

Some electrical PDF pages contain multiple viewports (sub-plans) on a
single sheet — e.g., "LEVEL 1 ENLARGED LIGHTING PLAN" and "MEZZANINE
ENLARGED LIGHTING PLAN" side by side.  This module auto-detects viewport
boundaries so each sub-plan gets its own fixture counts.

Algorithm:
1. Extract words from the bottom ~15% of the page (viewport titles live here).
2. Group words into title lines, check for lighting keywords.
3. Filter out non-lighting viewports (power, systems, demolition).
4. Derive short label from title ("Level 1" → "L1", "Mezzanine" → "MEZ").
5. Calculate column boundaries as midpoints between adjacent viewport centers.
6. Return list[Viewport] — empty if ≤1 lighting viewport (no split needed).
"""

from __future__ import annotations

import logging
import re
from typing import Any

from medina.models import PageInfo, PageType, Viewport

logger = logging.getLogger(__name__)

# Keywords that identify a lighting viewport title.
_LIGHTING_KEYWORDS = re.compile(
    r"lighting\s+plan|enlarged\s+lighting|lighting\s+layout",
    re.IGNORECASE,
)

# Keywords that disqualify a viewport as non-lighting.
_NON_LIGHTING_KEYWORDS = re.compile(
    r"power\s+plan|power\s+&|systems\s+plan|demolition|demo\s+plan|"
    r"signal\s+plan|fire\s+alarm|mechanical|plumbing",
    re.IGNORECASE,
)

# Patterns to extract a short label from the viewport title.
_LABEL_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"level\s+(\d+)", re.IGNORECASE), "L{0}"),
    (re.compile(r"(mezzanine|mezz)", re.IGNORECASE), "MEZ"),
    (re.compile(r"(basement|bsmt)", re.IGNORECASE), "BSM"),
    (re.compile(r"(\d+)\s*(st|nd|rd|th)\s*floor", re.IGNORECASE), "FL{0}"),
    (re.compile(r"floor\s+(\d+)", re.IGNORECASE), "FL{0}"),
    (re.compile(r"(roof|rooftop)", re.IGNORECASE), "RF"),
    (re.compile(r"(penthouse|penth)", re.IGNORECASE), "PH"),
    (re.compile(r"(garage|parking)", re.IGNORECASE), "GAR"),
    (re.compile(r"area\s+([A-Z0-9]+)", re.IGNORECASE), "A{0}"),
]


def _derive_label(title: str) -> str:
    """Derive a short label from a viewport title string.

    Examples:
        "LEVEL 1 ENLARGED LIGHTING PLAN" → "L1"
        "MEZZANINE ENLARGED LIGHTING PLAN" → "MEZ"
        "2ND FLOOR LIGHTING PLAN" → "FL2"
        "AREA B LIGHTING PLAN" → "AB"
    """
    for pattern, template in _LABEL_PATTERNS:
        m = pattern.search(title)
        if m:
            if "{0}" in template:
                return template.format(m.group(1))
            return template
    # Fallback: use first significant word (skip "enlarged", "lighting", etc.)
    skip = {"enlarged", "lighting", "plan", "electrical", "layout", "partial"}
    for word in title.split():
        if word.lower() not in skip and len(word) > 1:
            return word[:3].upper()
    return "VP"


def _group_title_lines(
    words: list[dict[str, Any]],
    y_tolerance: float = 5.0,
) -> list[list[dict[str, Any]]]:
    """Group words into horizontal lines by similar y position."""
    if not words:
        return []

    sorted_words = sorted(words, key=lambda w: (w["top"], w["x0"]))
    lines: list[list[dict[str, Any]]] = []
    current_line: list[dict[str, Any]] = [sorted_words[0]]

    for w in sorted_words[1:]:
        if abs(w["top"] - current_line[-1]["top"]) <= y_tolerance:
            current_line.append(w)
        else:
            lines.append(current_line)
            current_line = [w]
    lines.append(current_line)

    return lines


def _split_line_by_x_gap(
    line_words: list[dict[str, Any]],
    page_width: float,
    gap_threshold_frac: float = 0.03,
) -> list[list[dict[str, Any]]]:
    """Split a horizontal line into segments at large x-gaps.

    When multiple viewport titles sit on the same y-line (e.g., all at
    y=1808), ``_group_title_lines`` merges them into one string.  This
    function detects large horizontal gaps between word clusters and
    splits the line so each viewport title becomes its own segment.

    Args:
        line_words: Words from a single horizontal line, sorted by x0.
        page_width: Full page width in PDF points.
        gap_threshold_frac: Minimum gap as fraction of page width to
            trigger a split.  Default 0.03 (~90px on a 3024-wide page).

    Returns:
        List of word-lists — one per segment.  Returns ``[line_words]``
        unchanged if no large gaps exist.
    """
    if len(line_words) <= 1:
        return [line_words]

    sorted_words = sorted(line_words, key=lambda w: w["x0"])
    gap_threshold = page_width * gap_threshold_frac

    segments: list[list[dict[str, Any]]] = []
    current_segment: list[dict[str, Any]] = [sorted_words[0]]

    for w in sorted_words[1:]:
        gap = w["x0"] - current_segment[-1]["x1"]
        if gap > gap_threshold:
            segments.append(current_segment)
            current_segment = [w]
        else:
            current_segment.append(w)
    segments.append(current_segment)

    return segments


def detect_viewports(
    pdf_page: Any,
    page_info: PageInfo,
    viewport_separation_threshold: float | None = None,
) -> list[Viewport]:
    """Detect multiple lighting viewports on a single page.

    Looks for viewport titles in the bottom ~15% of the page. If 2+
    lighting viewports are found, returns them with computed bounding
    boxes. Otherwise returns an empty list (no splitting needed).

    Args:
        pdf_page: pdfplumber page object.
        page_info: Page metadata.

    Returns:
        List of Viewport objects. Empty if ≤1 lighting viewport found.
    """
    width = pdf_page.width
    height = pdf_page.height

    # Viewport titles typically appear in the bottom 15% of the page,
    # above the title block (which is in the rightmost ~25%).
    # Exclude the rightmost 25% (title block area) to avoid false positives
    # from the page title that repeats "LIGHTING PLAN" in the title block.
    title_block_x = width * 0.75
    title_region_bbox = (0, height * 0.82, title_block_x, height * 0.97)
    try:
        cropped = pdf_page.within_bbox(title_region_bbox)
        words = cropped.extract_words(x_tolerance=3, y_tolerance=3)
    except Exception:
        return []

    if not words:
        return []

    # Group words into lines, then split each line at large x-gaps so
    # that multiple viewport titles on the same y-line are separated.
    raw_lines = _group_title_lines(words)
    segments: list[list[dict[str, Any]]] = []
    for line_words in raw_lines:
        segments.extend(_split_line_by_x_gap(line_words, width))

    lighting_titles: list[dict[str, Any]] = []
    non_lighting_titles: list[dict[str, Any]] = []

    for seg_words in segments:
        seg_text = " ".join(w["text"] for w in seg_words)
        # Must mention a lighting/power/systems plan to be a viewport title.
        is_lighting = bool(_LIGHTING_KEYWORDS.search(seg_text))
        is_non_lighting = bool(_NON_LIGHTING_KEYWORDS.search(seg_text))

        if not is_lighting and not is_non_lighting:
            continue

        # Compute center x of this title segment.
        x_center = sum(
            (w["x0"] + w["x1"]) / 2 for w in seg_words
        ) / len(seg_words)

        # Offset y back to full-page coordinates.
        y_center = title_region_bbox[1] + (
            sum((w["top"] + w["bottom"]) / 2 for w in seg_words)
            / len(seg_words)
        )

        entry = {
            "text": seg_text,
            "x_center": x_center,
            "y_center": y_center,
            "x0": min(w["x0"] for w in seg_words),
            "x1": max(w["x1"] for w in seg_words),
        }

        if is_lighting and not is_non_lighting:
            lighting_titles.append(entry)
        else:
            non_lighting_titles.append(entry)

    if len(lighting_titles) < 2:
        return []

    # Sort by x position (left to right).
    lighting_titles.sort(key=lambda t: t["x_center"])
    non_lighting_titles.sort(key=lambda t: t["x_center"])

    # Require minimum horizontal separation between viewport centers.
    # With x-gap splitting, each segment is already a distinct title.
    # This guard catches multi-line title wrapping where the same title
    # appears on consecutive lines at nearly the same x position.
    # 10% of page width is enough — on a 4-viewport page each viewport
    # is ~25% wide so centers are ~18% apart (well above 10%).
    sep_threshold = viewport_separation_threshold if viewport_separation_threshold is not None else 0.10
    min_separation = width * sep_threshold
    max_gap = 0.0
    for i in range(1, len(lighting_titles)):
        gap = abs(lighting_titles[i]["x_center"] - lighting_titles[i - 1]["x_center"])
        max_gap = max(max_gap, gap)
    if max_gap < min_separation:
        logger.debug(
            "Viewport titles too close together (max gap=%.0f < min=%.0f) "
            "on %s — not splitting",
            max_gap, min_separation,
            page_info.sheet_code or f"page {page_info.page_number}",
        )
        return []

    # Calculate viewport boundaries as midpoints between adjacent titles.
    # For the rightmost lighting viewport, use the midpoint to the first
    # non-lighting title to its right (if any) instead of the full page
    # width.  This prevents power/systems viewports from being included.
    rightmost_lighting_center = lighting_titles[-1]["x_center"]
    right_boundary = width
    for nlt in non_lighting_titles:
        if nlt["x_center"] > rightmost_lighting_center:
            right_boundary = (rightmost_lighting_center + nlt["x_center"]) / 2
            break

    viewports: list[Viewport] = []
    for i, title in enumerate(lighting_titles):
        if i == 0:
            x0 = 0.0
        else:
            x0 = (lighting_titles[i - 1]["x_center"] + title["x_center"]) / 2

        if i == len(lighting_titles) - 1:
            x1 = right_boundary
        else:
            x1 = (title["x_center"] + lighting_titles[i + 1]["x_center"]) / 2

        label = _derive_label(title["text"])
        viewports.append(Viewport(
            label=label,
            title=title["text"],
            bbox=(x0, 0, x1, height),
            page_type=PageType.LIGHTING_PLAN,
        ))

    logger.info(
        "Detected %d lighting viewports on %s: %s",
        len(viewports),
        page_info.sheet_code or f"page {page_info.page_number}",
        [(v.label, f"x={v.bbox[0]:.0f}-{v.bbox[2]:.0f}") for v in viewports],
    )

    return viewports


def split_page_into_viewports(
    page_info: PageInfo,
    viewports: list[Viewport],
) -> list[PageInfo]:
    """Create virtual PageInfo objects for each viewport.

    Each virtual page shares the same physical page but has a composite
    sheet_code (e.g., "E601-L1") and a viewport_bbox that restricts
    counting to that portion of the page.

    Args:
        page_info: Original page metadata.
        viewports: Detected viewports.

    Returns:
        List of PageInfo objects with composite sheet_codes.
        If viewports is empty, returns [page_info] unchanged.
    """
    if not viewports:
        return [page_info]

    parent_code = page_info.sheet_code or f"P{page_info.page_number}"
    virtual_pages: list[PageInfo] = []

    for vp in viewports:
        composite_code = f"{parent_code}-{vp.label}"
        virtual = PageInfo(
            page_number=page_info.page_number,
            sheet_code=composite_code,
            sheet_title=vp.title,
            page_type=vp.page_type,
            source_path=page_info.source_path,
            pdf_page_index=page_info.pdf_page_index,
            viewport_bbox=vp.bbox,
            parent_sheet_code=parent_code,
        )
        virtual_pages.append(virtual)

    logger.info(
        "Split %s into %d viewports: %s",
        parent_code,
        len(virtual_pages),
        [vp.sheet_code for vp in virtual_pages],
    )

    return virtual_pages
