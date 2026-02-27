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
    (re.compile(r"area\s+['\"]?([A-Z0-9]+)['\"]?", re.IGNORECASE), "A{0}"),
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


def _scan_region_for_titles(
    pdf_page: Any,
    region_bbox: tuple[float, float, float, float],
    page_width: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Scan a region for viewport titles, returning lighting and non-lighting lists."""
    try:
        cropped = pdf_page.within_bbox(region_bbox)
        words = cropped.extract_words(x_tolerance=3, y_tolerance=3)
    except Exception:
        return [], []

    if not words:
        return [], []

    raw_lines = _group_title_lines(words)
    segments: list[list[dict[str, Any]]] = []
    for line_words in raw_lines:
        segments.extend(_split_line_by_x_gap(line_words, page_width))

    lighting_titles: list[dict[str, Any]] = []
    non_lighting_titles: list[dict[str, Any]] = []

    for seg_words in segments:
        seg_text = " ".join(w["text"] for w in seg_words)
        is_lighting = bool(_LIGHTING_KEYWORDS.search(seg_text))
        is_non_lighting = bool(_NON_LIGHTING_KEYWORDS.search(seg_text))

        if not is_lighting and not is_non_lighting:
            continue

        x_center = sum(
            (w["x0"] + w["x1"]) / 2 for w in seg_words
        ) / len(seg_words)

        # Offset y back to full-page coordinates.
        y_center = region_bbox[1] + (
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

    return lighting_titles, non_lighting_titles


def detect_viewports(
    pdf_page: Any,
    page_info: PageInfo,
    viewport_separation_threshold: float | None = None,
) -> list[Viewport]:
    """Detect multiple lighting viewports on a single page.

    First scans the bottom ~15% (standard layout). If that finds <2
    lighting viewports, falls back to a full-page scan to support grid
    layouts where viewport titles appear in the middle of the page.

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

    lighting_titles, non_lighting_titles = _scan_region_for_titles(
        pdf_page, title_region_bbox, width,
    )

    # Fallback: scan the full page (excluding title block column AND
    # the rightmost notes column) for grid layouts where viewport titles
    # appear anywhere on the page.  Use a tighter x cutoff (65% instead
    # of 75%) to exclude general notes text that mentions "LIGHTING".
    is_grid_layout = False
    if len(lighting_titles) < 2:
        notes_cutoff_x = width * 0.65
        full_region = (0, 0, notes_cutoff_x, height)
        full_lighting, full_non_lighting = _scan_region_for_titles(
            pdf_page, full_region, width,
        )
        # Extra filter: in full-page mode, require viewport titles to have
        # a structured format — they must contain a qualifier like
        # "LEVEL", "FLOOR", "AREA", "ENLARGED", "PARTIAL" alongside the
        # lighting keyword.  Bare "LIGHTING PLAN" matches in notes are
        # rejected.
        _VP_QUALIFIER = re.compile(
            r"level|floor|area|enlarged|partial|basement|mezzanine|"
            r"roof|penthouse|garage|upper|lower|main",
            re.IGNORECASE,
        )
        full_lighting = [
            t for t in full_lighting
            if _VP_QUALIFIER.search(t["text"])
        ]
        full_non_lighting = [
            t for t in full_non_lighting
            if _VP_QUALIFIER.search(t["text"])
        ]
        if len(full_lighting) >= 2:
            lighting_titles = full_lighting
            non_lighting_titles = full_non_lighting
            is_grid_layout = True
            logger.debug(
                "Bottom-15%% scan found %d viewport(s) — full-page scan "
                "found %d lighting viewports on %s (grid layout)",
                0, len(full_lighting),
                page_info.sheet_code or f"page {page_info.page_number}",
            )

    if len(lighting_titles) < 2:
        return []

    # Sort by x position (left to right).
    lighting_titles.sort(key=lambda t: t["x_center"])
    non_lighting_titles.sort(key=lambda t: t["x_center"])

    # Require minimum separation between viewport centers (horizontal
    # OR vertical).  This guard catches multi-line title wrapping where
    # the same title appears on consecutive lines at nearly the same
    # position.  For grid layouts, viewports may be vertically stacked
    # at the same x-position, so check y-separation as well.
    sep_threshold = viewport_separation_threshold if viewport_separation_threshold is not None else 0.10
    min_x_sep = width * sep_threshold
    min_y_sep = height * sep_threshold
    max_x_gap = 0.0
    max_y_gap = 0.0
    for i in range(1, len(lighting_titles)):
        x_gap = abs(lighting_titles[i]["x_center"] - lighting_titles[i - 1]["x_center"])
        y_gap = abs(lighting_titles[i]["y_center"] - lighting_titles[i - 1]["y_center"])
        max_x_gap = max(max_x_gap, x_gap)
        max_y_gap = max(max_y_gap, y_gap)
    if max_x_gap < min_x_sep and max_y_gap < min_y_sep:
        logger.debug(
            "Viewport titles too close together (max x_gap=%.0f < %.0f, "
            "max y_gap=%.0f < %.0f) on %s — not splitting",
            max_x_gap, min_x_sep, max_y_gap, min_y_sep,
            page_info.sheet_code or f"page {page_info.page_number}",
        )
        return []

    # For grid layouts, group titles by y-row and compute per-row
    # bounding boxes (vertical splits per row, not full-page columns).
    if is_grid_layout:
        return _build_grid_viewports(
            lighting_titles, non_lighting_titles, width, height,
            page_info,
        )

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


def _build_grid_viewports(
    lighting_titles: list[dict[str, Any]],
    non_lighting_titles: list[dict[str, Any]],
    width: float,
    height: float,
    page_info: PageInfo,
) -> list[Viewport]:
    """Build viewports for grid layouts with multiple rows of viewports.

    Groups titles by y-row and creates a 2D bounding box for each
    lighting viewport (x boundaries from column position, y boundaries
    from row position).
    """
    all_titles = lighting_titles + non_lighting_titles

    # Group titles by y-row (cluster by y_center with tolerance)
    y_tolerance = height * 0.03  # 3% of page height
    all_titles_sorted = sorted(all_titles, key=lambda t: t["y_center"])

    rows: list[list[dict[str, Any]]] = []
    current_row: list[dict[str, Any]] = [all_titles_sorted[0]]
    for t in all_titles_sorted[1:]:
        if abs(t["y_center"] - current_row[-1]["y_center"]) <= y_tolerance:
            current_row.append(t)
        else:
            rows.append(current_row)
            current_row = [t]
    rows.append(current_row)

    if len(rows) < 1:
        return []

    # Compute y boundaries between rows
    row_y_centers = [
        sum(t["y_center"] for t in row) / len(row) for row in rows
    ]

    viewports: list[Viewport] = []

    for row_idx, row_titles in enumerate(rows):
        # Y boundaries: from midpoint with previous row to midpoint with next row
        if row_idx == 0:
            y0 = 0.0
        else:
            y0 = (row_y_centers[row_idx - 1] + row_y_centers[row_idx]) / 2

        if row_idx == len(rows) - 1:
            y1 = height
        else:
            y1 = (row_y_centers[row_idx] + row_y_centers[row_idx + 1]) / 2

        # Sort this row by x, separate lighting from non-lighting
        row_lighting = sorted(
            [t for t in row_titles if t in lighting_titles],
            key=lambda t: t["x_center"],
        )
        row_non_lighting = sorted(
            [t for t in row_titles if t in non_lighting_titles],
            key=lambda t: t["x_center"],
        )

        if not row_lighting:
            continue

        # X boundaries — same logic as single-row viewports
        rightmost_center = row_lighting[-1]["x_center"]
        right_boundary = width
        for nlt in row_non_lighting:
            if nlt["x_center"] > rightmost_center:
                right_boundary = (rightmost_center + nlt["x_center"]) / 2
                break

        # Left boundary from non-lighting to the left
        leftmost_center = row_lighting[0]["x_center"]
        left_boundary = 0.0
        for nlt in reversed(row_non_lighting):
            if nlt["x_center"] < leftmost_center:
                left_boundary = (nlt["x_center"] + leftmost_center) / 2
                break

        for i, title in enumerate(row_lighting):
            if i == 0:
                x0 = left_boundary
            else:
                x0 = (row_lighting[i - 1]["x_center"] + title["x_center"]) / 2

            if i == len(row_lighting) - 1:
                x1 = right_boundary
            else:
                x1 = (title["x_center"] + row_lighting[i + 1]["x_center"]) / 2

            label = _derive_label(title["text"])
            viewports.append(Viewport(
                label=label,
                title=title["text"],
                bbox=(x0, y0, x1, y1),
                page_type=PageType.LIGHTING_PLAN,
            ))

    if viewports:
        logger.info(
            "Detected %d lighting viewports (grid layout) on %s: %s",
            len(viewports),
            page_info.sheet_code or f"page {page_info.page_number}",
            [(v.label, f"bbox=({v.bbox[0]:.0f},{v.bbox[1]:.0f},"
              f"{v.bbox[2]:.0f},{v.bbox[3]:.0f})") for v in viewports],
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
