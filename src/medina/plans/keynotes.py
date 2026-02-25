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
    re.compile(r'KEYED\s+PLAN\s+NOTES?\s*:', re.IGNORECASE),
    re.compile(r'KEYED\s+PLAN\s+NOTES?\b', re.IGNORECASE),
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


_MAX_KEYNOTE_NUMBER = 20


def _parse_keynote_entries(
    section_text: str,
    max_keynote_number: int | None = None,
) -> list[tuple[str, str]]:
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
        # Keynote numbers are typically 1-20 (most projects have 1-10).
        # Higher numbers are usually from general notes, specifications,
        # or address text that leaked into the keynote region.
        try:
            num_val = int(num_str)
        except ValueError:
            continue
        max_kn = max_keynote_number if max_keynote_number is not None else _MAX_KEYNOTE_NUMBER
        if num_val > max_kn:
            logger.debug("Skipping keynote #%s: number too high (>%d)", num_str, max_kn)
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
    min_seg_len: float = 3.0,
) -> int:
    """Check if a point is enclosed by line endpoints in all quadrants.

    Keynote symbols (diamonds, hexagons, etc.) have line endpoints
    surrounding the number in all four quadrants. Returns the number
    of quadrants (0–4) that have nearby line endpoints.

    Only considers endpoints from line segments whose length is at
    least ``min_seg_len`` — this filters out dense hatching/render
    artifacts that produce false enclosures on busy pages.
    """
    import math

    quadrants: set[str] = set()
    for ln in lines:
        # Skip tiny line segments (hatching, render artifacts).
        seg_len = math.sqrt(
            (ln["x1"] - ln["x0"]) ** 2 + (ln["bottom"] - ln["top"]) ** 2
        )
        if seg_len < min_seg_len:
            continue

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


def _check_shape_quality(
    cx: float,
    cy: float,
    shape_lines: list[Any],
    radius: float = 13.0,
) -> tuple[int, int, float]:
    """Assess whether nearby line segments form a coherent polygon enclosure.

    Real keynote symbols (hexagons, diamonds) have a small number of
    polygon edges at a consistent distance from the center, with vertices
    shared by exactly 2 edges (closed polygon).  Dense wiring/hatching
    produces many random segments that do NOT form a coherent polygon.

    Args:
        cx, cy: Center point of the candidate number.
        shape_lines: Pre-filtered lines with length in [3, 20] pt.
        radius: Maximum distance from center for both endpoints.

    Returns:
        Tuple of (shape_segs, pts_used_twice, std_mid_dist):
        - shape_segs: Segments with both endpoints within *radius*.
        - pts_used_twice: Vertex clusters shared by exactly 2 edges
          (indicator of a closed polygon).
        - std_mid_dist: Std-dev of midpoint distances from center
          (low for real shapes, high for random wiring).
    """
    import math
    from collections import Counter

    midpoint_dists: list[float] = []
    endpoints: list[tuple[int, int]] = []
    n_segs = 0

    for ln in shape_lines:
        x0, y0 = ln["x0"], ln["top"]
        x1, y1 = ln["x1"], ln["bottom"]

        d0 = math.sqrt((x0 - cx) ** 2 + (y0 - cy) ** 2)
        d1 = math.sqrt((x1 - cx) ** 2 + (y1 - cy) ** 2)

        if d0 <= radius and d1 <= radius:
            n_segs += 1
            mx = (x0 + x1) / 2
            my = (y0 + y1) / 2
            midpoint_dists.append(math.sqrt((mx - cx) ** 2 + (my - cy) ** 2))
            # Round to integer for vertex clustering.
            endpoints.append((round(x0), round(y0)))
            endpoints.append((round(x1), round(y1)))

    # Count vertices shared by exactly 2 polygon edges.
    ep_counts = Counter(endpoints)
    pts_x2 = sum(1 for c in ep_counts.values() if c == 2)

    # Standard deviation of midpoint distances (ring consistency).
    if len(midpoint_dists) >= 2:
        mean_d = sum(midpoint_dists) / len(midpoint_dists)
        var = sum((d - mean_d) ** 2 for d in midpoint_dists) / len(midpoint_dists)
        std_mid = math.sqrt(var)
    else:
        std_mid = 999.0

    return n_segs, pts_x2, std_mid



def _count_keynote_occurrences(
    pdf_page: Any,
    keynote_numbers: list[str],
    page_width: float,
    page_height: float,
    return_positions: bool = False,
    viewport_bbox: tuple[float, float, float, float] | None = None,
) -> dict[str, int] | tuple[dict[str, int], dict[str, list[dict]]]:
    """Count keynote symbols on the plan using geometric shape detection.

    Keynote numbers on plans appear inside geometric shapes (diamonds,
    hexagons, triangles, circles). This function identifies them by
    detecting line endpoints that surround each candidate number in
    all four quadrants (top-right, bottom-right, bottom-left, top-left).

    Three-step filtering:
    1. Quadrant check: find numbers enclosed in 3+ quadrants.
    2. Shape quality check (dense pages only): verify that nearby segments
       form a coherent polygon (closed vertices + consistent midpoint
       distance).  Shape-verified candidates determine the modal font_h.
    3. Final filter: quadrants >= 3 AND font_h matches modal.

    When *viewport_bbox* is set, only candidates within the viewport
    are considered (for multi-viewport page support).
    """
    import math
    from collections import Counter

    counts: dict[str, int] = {n: 0 for n in keynote_numbers}
    positions: dict[str, list[dict]] = {n: [] for n in keynote_numbers}
    if not keynote_numbers:
        return (counts, positions) if return_positions else counts

    try:
        words = pdf_page.extract_words(
            x_tolerance=3,
            y_tolerance=3,
            keep_blank_chars=False,
        )
    except Exception:
        logger.warning("Failed to extract words for keynote counting")
        return (counts, positions) if return_positions else counts

    lines = pdf_page.lines or []
    if not lines:
        logger.debug("No lines on page — falling back to text-only counting")
        result = _count_keynote_text_only(
            words, keynote_numbers, page_width, page_height,
            return_positions=return_positions,
            viewport_bbox=viewport_bbox,
        )
        return result

    # Compute drawing area boundaries.
    # When a viewport is set, use viewport-relative coordinates.
    # Use page.bbox for origin-aware coordinates on non-zero-origin PDFs.
    if viewport_bbox is not None:
        vx0, vy0, vx1, vy1 = viewport_bbox
        vw = vx1 - vx0
        vh = vy1 - vy0
        drawing_max_x = vx0 + vw * 0.70
        title_min_y = vy0 + vh * 0.90
    else:
        try:
            vx0, vy0, vx1, vy1 = pdf_page.bbox
        except Exception:
            vx0 = vy0 = 0.0
            vx1 = page_width
            vy1 = page_height
        vw = vx1 - vx0
        vh = vy1 - vy0
        drawing_max_x = vx0 + vw * 0.70
        title_min_y = vy0 + vh * 0.90

    kn_set = set(keynote_numbers)

    candidates: list[dict[str, Any]] = []
    for w in words:
        text = w["text"].strip()
        if text not in kn_set:
            continue
        cx = (w["x0"] + w["x1"]) / 2
        cy = (w["top"] + w["bottom"]) / 2
        # Must be inside viewport (if set)
        if viewport_bbox is not None:
            if cx < vx0 or cx > vx1 or cy < vy0 or cy > vy1:
                continue
        if cx > drawing_max_x or cy > title_min_y:
            continue

        q_count = _check_enclosed_by_shape(cx, cy, lines)
        font_h = round(w["bottom"] - w["top"], 1)
        candidates.append({
            "text": text,
            "quadrants": q_count,
            "font_h": font_h,
            "x0": w["x0"],
            "top": w["top"],
            "x1": w["x1"],
            "bottom": w["bottom"],
            "cx": cx,
            "cy": cy,
        })

    if not candidates:
        return (counts, positions) if return_positions else counts

    # ── Shape-quality-aware modal font_h detection ──────────────────
    # The quadrant check alone is unreliable — wall/equipment/conduit lines
    # create false enclosures around bare numbers (circuit numbers, room
    # labels, etc.).  Always run polygon closure analysis to find real
    # geometric shapes (hexagons, diamonds) and derive the correct modal
    # font_h from those.

    modal_font_h: float | None = None

    # Pre-filter to "shape-length" segments (3–20 pt) for efficiency.
    shape_lines: list[Any] = []
    for ln in lines:
        seg_len = math.sqrt(
            (ln["x1"] - ln["x0"]) ** 2
            + (ln["bottom"] - ln["top"]) ** 2
        )
        if 3.0 <= seg_len <= 20.0:
            shape_lines.append(ln)

    logger.debug(
        "Shape quality check: %d total lines, %d shape-length lines, "
        "%d candidates with quad>=3",
        len(lines), len(shape_lines),
        sum(1 for c in candidates if c["quadrants"] >= 3),
    )

    # Compute shape quality for candidates passing quadrant check.
    shape_verified: list[dict] = []
    for c in candidates:
        if c["quadrants"] < 3:
            continue
        segs, x2, std = _check_shape_quality(
            c["cx"], c["cy"], shape_lines,
        )
        c["shape_segs"] = segs
        c["pts_x2"] = x2
        c["std_mid"] = std
        # Real polygon: 4–12 edges, >=2 shared vertices, tight ring.
        # std < 2.0 separates real hexagons/diamonds (std ~0.7–1.5)
        # from false positives near structured wiring (std ~2.0–3.0).
        if 4 <= segs <= 12 and x2 >= 2 and std < 2.0:
            shape_verified.append(c)

    if len(shape_verified) >= 2:
        font_counts = Counter(c["font_h"] for c in shape_verified)
        modal_font_h = font_counts.most_common(1)[0][0]
        logger.debug(
            "Shape-verified modal font_h=%.1f from %d verified candidates",
            modal_font_h, len(shape_verified),
        )

    # Fallback: standard quadrant-based modal font_h (works on clean pages
    # where shape quality check finds no verified candidates — e.g. pages
    # with very few lines where shapes are simple strokes).
    if modal_font_h is None:
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
                result = _count_keynote_text_only(
                    words, keynote_numbers, page_width, page_height,
                    return_positions=return_positions,
                    viewport_bbox=viewport_bbox,
                )
                return result

    # ── Final filter: quadrants >= 3 AND matching font_h ────────────
    for c in candidates:
        if c["quadrants"] >= 3 and c["font_h"] == modal_font_h:
            counts[c["text"]] += 1
            if return_positions:
                positions[c["text"]].append({
                    "x0": c["x0"],
                    "top": c["top"],
                    "x1": c["x1"],
                    "bottom": c["bottom"],
                    "cx": c["cx"],
                    "cy": c["cy"],
                })

    return (counts, positions) if return_positions else counts


def _count_keynote_text_only(
    words: list[Any],
    keynote_numbers: list[str],
    page_width: float,
    page_height: float,
    return_positions: bool = False,
    viewport_bbox: tuple[float, float, float, float] | None = None,
) -> dict[str, int] | tuple[dict[str, int], dict[str, list[dict]]]:
    """Fallback: count keynote numbers by text matching only.

    Used when no geometric line data is available on the page.
    When *viewport_bbox* is set, only words within the viewport are counted.
    """
    counts: dict[str, int] = {n: 0 for n in keynote_numbers}
    positions: dict[str, list[dict]] = {n: [] for n in keynote_numbers}
    kn_set = set(keynote_numbers)

    if viewport_bbox is not None:
        vx0, vy0, vx1, vy1 = viewport_bbox
        vw = vx1 - vx0
        vh = vy1 - vy0
        drawing_max_x = vx0 + vw * 0.70
        title_min_y = vy0 + vh * 0.90
    else:
        vx0 = vy0 = 0.0
        vx1 = page_width
        vy1 = page_height
        drawing_max_x = page_width * 0.70
        title_min_y = page_height * 0.90

    for w in words:
        cx = (w["x0"] + w["x1"]) / 2
        cy = (w["top"] + w["bottom"]) / 2
        # Must be inside viewport
        if viewport_bbox is not None:
            if cx < vx0 or cx > vx1 or cy < vy0 or cy > vy1:
                continue
        if cx > drawing_max_x or cy > title_min_y:
            continue
        text = w["text"].strip()
        if text in kn_set:
            counts[text] += 1
            if return_positions:
                positions[text].append({
                    "x0": w["x0"],
                    "top": w["top"],
                    "x1": w["x1"],
                    "bottom": w["bottom"],
                    "cx": cx,
                    "cy": cy,
                })

    return (counts, positions) if return_positions else counts


def _find_keynotes_header_x(words: list[Any]) -> float | None:
    """Find the x0 position of the KEY NOTES header using word positions.

    Searches for "KEY" followed by "NOTES" (or similar patterns) in
    the word list.  Returns the x0 of the first word in the header,
    or ``None`` if not found.
    """
    for i, w in enumerate(words):
        upper = w["text"].upper().strip()
        # Single-word headers: "KEYNOTES", "KEYNOTES:"
        if upper in ("KEYNOTES", "KEYNOTES:"):
            return w["x0"]
        # Multi-word headers: "KEY NOTES:", "KEYED NOTES:", etc.
        if upper in ("KEY", "KEYED"):
            # Check the next few words for "NOTES" / "SHEET"
            for j in range(1, 4):
                if i + j >= len(words):
                    break
                nw = words[i + j]
                # Must be on same line (close y) and nearby x
                if (abs(nw["top"] - w["top"]) < 5
                        and nw["x0"] - w["x1"] < 30):
                    if "NOTE" in nw["text"].upper():
                        return w["x0"]
                    if nw["text"].upper().strip() in ("SHEET", "PLAN"):
                        # "KEYED SHEET NOTES" / "KEYED PLAN NOTES" — keep looking
                        continue
                else:
                    break
    return None


def _has_keynote_content(text: str) -> bool:
    """Check if text has a keynotes header AND at least one numbered entry.

    Uses a stricter entry regex (1-2 digit numbers only) to avoid false
    positives from addresses, dates, or other multi-digit numbers.
    """
    if not any(p.search(text) for p in _KEYNOTES_HEADER_PATTERNS):
        return False
    # Strict: only 1-2 digit numbers qualify as keynote entries.
    strict_entry = re.compile(
        r'^\s*(\d{1,2})\s*[.):\-]?\s+([A-Z].+)', re.MULTILINE,
    )
    return bool(strict_entry.search(text))


def _extract_keynotes_region_text(
    pdf_page: Any,
    viewport_bbox: tuple[float, float, float, float] | None = None,
) -> str:
    """Extract text from the keynotes region of the page.

    Uses a two-stage approach:
    1. Find the KEY NOTES header position using word extraction, then
       crop tightly around the header column.  This prevents drawing-area
       text (cross-references, fixture labels) from bleeding in.
    2. Fall back to progressively wider right-side crops if the header
       position cannot be determined or the tight crop misses entries.

    Falls back to full-page text if no cropped region yields keynotes.

    When *viewport_bbox* is set, all crops are relative to the viewport
    bounding box instead of the full page.
    """
    width = pdf_page.width
    height = pdf_page.height

    if viewport_bbox is not None:
        vx0, vy0, vx1, vy1 = viewport_bbox
        vw = vx1 - vx0
        vh = vy1 - vy0
    else:
        # Use page.bbox for origin-aware coordinates
        vx0, vy0, vx1, vy1 = pdf_page.bbox
        vw = vx1 - vx0
        vh = vy1 - vy0

    # Stage 1: Header-aware tight crop
    try:
        words = pdf_page.extract_words(x_tolerance=3, y_tolerance=3)
        # Filter words to viewport if set
        if viewport_bbox is not None:
            words = [
                w for w in words
                if w["x0"] >= vx0 and w["x1"] <= vx1
                and w["top"] >= vy0 and w["bottom"] <= vy1
            ]
        header_x = _find_keynotes_header_x(words)
        if header_x is not None:
            crop_left = max(vx0, header_x - 30)
            bbox = (crop_left, vy0, vx1, vy0 + vh * 0.85)
            try:
                cropped = pdf_page.within_bbox(bbox)
                text = cropped.extract_text() or ""
                if _has_keynote_content(text):
                    logger.debug(
                        "Keynotes found via header-aware crop "
                        "(x0=%.0f, header_x=%.0f)",
                        crop_left, header_x,
                    )
                    return text
            except Exception:
                pass
    except Exception:
        pass

    # Stage 2: Fixed right-side crop (fallback)
    regions = [
        (vx0 + vw * 0.70, vy0, vx1, vy0 + vh * 0.85),    # Right 30%, top 85%
        (vx0 + vw * 0.65, vy0, vx1, vy0 + vh * 0.85),    # Right 35%, top 85%
        (vx0 + vw * 0.60, vy0, vx1, vy0 + vh * 0.80),    # Right 40%, top 80%
    ]

    for bbox in regions:
        try:
            cropped = pdf_page.within_bbox(bbox)
            text = cropped.extract_text() or ""
        except Exception:
            continue

        if _has_keynote_content(text):
            logger.debug(
                "Keynotes found in cropped region "
                "(x0=%.0f, y0=%.0f, x1=%.0f, y1=%.0f)",
                *bbox,
            )
            return text

    # Fallback: use full viewport/page text
    if viewport_bbox is not None:
        try:
            cropped = pdf_page.within_bbox(viewport_bbox)
            return cropped.extract_text() or ""
        except Exception:
            pass
    try:
        return pdf_page.extract_text() or ""
    except Exception:
        return ""


def extract_keynotes_from_plan(
    page_info: PageInfo,
    pdf_page: Any,
    known_fixture_codes: list[str] | None = None,
    return_positions: bool = False,
) -> tuple[list[KeyNote], dict[str, int]] | tuple[list[KeyNote], dict[str, int], dict[str, list[dict]]]:
    """Extract keynotes and count their occurrences on a single plan page.

    Uses spatial extraction to isolate the keynotes legend area (right
    portion of the page) from the main drawing area.

    Args:
        page_info: Page metadata.
        pdf_page: pdfplumber page object.
        known_fixture_codes: Optional list of known fixture codes for
            matching references in keynote text.
        return_positions: If True, also return keynote positions.

    Returns:
        If ``return_positions`` is False:
            Tuple of ``(keynotes_list, counts_dict)``.
        If True:
            Tuple of ``(keynotes_list, counts_dict, positions_dict)``
            where ``positions_dict = {keynote_number: [pos, ...]}``.

    Raises:
        KeyNoteExtractionError: If extraction fails critically.
    """
    sheet = page_info.sheet_code or f"page_{page_info.page_number}"
    logger.info("Extracting keynotes from plan %s", sheet)

    viewport_bbox = page_info.viewport_bbox

    try:
        region_text = _extract_keynotes_region_text(pdf_page, viewport_bbox=viewport_bbox)
    except Exception as exc:
        raise KeyNoteExtractionError(
            f"Failed to extract text from plan {sheet}: {exc}"
        ) from exc

    keynotes: list[KeyNote] = []
    counts: dict[str, int] = {}
    kn_positions: dict[str, list[dict]] = {}

    # Find the keynotes section.
    section_text = _find_keynotes_section(region_text)

    # For viewport sub-plans, the shared KEYED NOTES panel may sit outside
    # the viewport bbox (e.g., at the far right of the full page).  If the
    # viewport-scoped search found nothing, retry with the full page.
    if section_text is None and viewport_bbox is not None:
        logger.debug(
            "No keynotes in viewport bbox for %s — retrying with full page",
            sheet,
        )
        try:
            full_text = _extract_keynotes_region_text(pdf_page, viewport_bbox=None)
            section_text = _find_keynotes_section(full_text)
        except Exception:
            pass

    if section_text is None:
        logger.debug("No keynotes section found on plan %s", sheet)
        return (keynotes, counts, kn_positions) if return_positions else (keynotes, counts)

    # Parse numbered entries.
    entries = _parse_keynote_entries(section_text)
    if not entries:
        logger.debug(
            "Keynotes header found but no numbered entries on plan %s", sheet
        )
        return (keynotes, counts, kn_positions) if return_positions else (keynotes, counts)

    # Deduplicate entries by keynote number — keep the first (longest) text
    # for each number.  Duplicate numbers often arise when the region crop
    # captures both a keynote section and adjacent general notes.
    seen_nums: dict[str, int] = {}
    deduped: list[tuple[str, str]] = []
    for num, text in entries:
        if num in seen_nums:
            # Keep the entry with longer text (more descriptive).
            idx = seen_nums[num]
            if len(text) > len(deduped[idx][1]):
                deduped[idx] = (num, text)
            logger.debug(
                "Duplicate keynote #%s on plan %s — merged", num, sheet,
            )
        else:
            seen_nums[num] = len(deduped)
            deduped.append((num, text))
    entries = deduped

    logger.info("Found %d keynote entries on plan %s", len(entries), sheet)

    keynote_numbers = [num for num, _text in entries]

    # Count occurrences of keynote numbers on the drawing.
    page_width = pdf_page.width
    page_height = pdf_page.height
    count_result = _count_keynote_occurrences(
        pdf_page, keynote_numbers, page_width, page_height,
        return_positions=return_positions,
        viewport_bbox=viewport_bbox,
    )
    if return_positions and isinstance(count_result, tuple):
        counts, kn_positions = count_result
    else:
        counts = count_result  # type: ignore[assignment]

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

    if return_positions:
        return keynotes, counts, kn_positions
    return keynotes, counts


def _process_single_plan(
    page_info: PageInfo,
    pdf_page: Any,
    known_fixture_codes: list[str] | None,
    return_positions: bool,
) -> tuple[list[KeyNote], dict[str, int], dict[str, list[dict]] | None]:
    """Process keynotes for a single (non-viewport-group) plan page.

    Returns (keynotes, counts, positions_or_None).
    """
    raw = extract_keynotes_from_plan(
        page_info, pdf_page, known_fixture_codes,
        return_positions=return_positions,
    )
    if return_positions and len(raw) == 3:
        return raw[0], raw[1], raw[2]
    return raw[0], raw[1], None


def _process_viewport_group(
    sibling_pages: list[PageInfo],
    pdf_pages: dict[int, Any],
    known_fixture_codes: list[str] | None,
    return_positions: bool,
) -> tuple[list[KeyNote], dict[str, dict[str, int]], dict[str, dict] | None]:
    """Process keynotes for a group of viewport siblings sharing one page.

    Keynote TEXT is extracted once from the full (unclipped) page since the
    shared KEYED NOTES panel sits outside individual viewport bboxes.
    Keynote COUNTING is done per-viewport using each viewport's bbox.

    Returns (keynotes, {sheet: counts}, positions_dict_or_None).
    """
    # All siblings share the same physical page.
    first = sibling_pages[0]
    pdf_page = pdf_pages.get(first.page_number)
    if pdf_page is None:
        sheet_codes = [p.sheet_code for p in sibling_pages]
        logger.warning("No PDF page for viewport group %s", sheet_codes)
        empty_counts = {
            (p.sheet_code or f"page_{p.page_number}"): {}
            for p in sibling_pages
        }
        return [], empty_counts, {} if return_positions else None

    page_width = pdf_page.width
    page_height = pdf_page.height

    # 1. Extract keynote TEXT once from full page (no viewport clipping).
    try:
        full_text = _extract_keynotes_region_text(pdf_page, viewport_bbox=None)
    except Exception as exc:
        logger.warning("Failed to extract keynote text for viewport group: %s", exc)
        empty_counts = {
            (p.sheet_code or f"page_{p.page_number}"): {}
            for p in sibling_pages
        }
        return [], empty_counts, {} if return_positions else None

    section_text = _find_keynotes_section(full_text)
    if section_text is None:
        logger.debug("No keynotes section in viewport group (parent=%s)", first.parent_sheet_code)
        empty_counts = {
            (p.sheet_code or f"page_{p.page_number}"): {}
            for p in sibling_pages
        }
        return [], empty_counts, {} if return_positions else None

    entries = _parse_keynote_entries(section_text)
    if not entries:
        logger.debug("Keynotes header found but no entries in viewport group")
        empty_counts = {
            (p.sheet_code or f"page_{p.page_number}"): {}
            for p in sibling_pages
        }
        return [], empty_counts, {} if return_positions else None

    # Deduplicate entries by keynote number.
    seen_nums: dict[str, int] = {}
    deduped: list[tuple[str, str]] = []
    for num, text in entries:
        if num in seen_nums:
            idx = seen_nums[num]
            if len(text) > len(deduped[idx][1]):
                deduped[idx] = (num, text)
        else:
            seen_nums[num] = len(deduped)
            deduped.append((num, text))
    entries = deduped

    keynote_numbers = [num for num, _ in entries]

    # 2. Count keynote symbols PER VIEWPORT using each viewport's bbox.
    group_counts: dict[str, dict[str, int]] = {}
    group_positions: dict[str, dict] = {} if return_positions else None
    combined_counts: dict[str, dict[str, int]] = {}  # {kn_number: {sheet: count}}

    for page_info in sibling_pages:
        sheet = page_info.sheet_code or f"page_{page_info.page_number}"
        viewport_bbox = page_info.viewport_bbox

        count_result = _count_keynote_occurrences(
            pdf_page, keynote_numbers, page_width, page_height,
            return_positions=return_positions,
            viewport_bbox=viewport_bbox,
        )
        if return_positions and isinstance(count_result, tuple):
            vp_counts, vp_positions = count_result
            # Normalize to (0,0)-origin image space.
            bbox = tuple(pdf_page.bbox)
            ox, oy = bbox[0], bbox[1]
            if ox != 0.0 or oy != 0.0:
                norm_pos: dict[str, list[dict]] = {}
                for kn_num, pos_list in vp_positions.items():
                    norm_pos[kn_num] = [
                        {
                            "x0": p["x0"] - ox, "top": p["top"] - oy,
                            "x1": p["x1"] - ox, "bottom": p["bottom"] - oy,
                            "cx": p["cx"] - ox, "cy": p["cy"] - oy,
                        }
                        for p in pos_list
                    ]
                vp_positions = norm_pos
            group_positions[sheet] = {
                "page_width": page_width,
                "page_height": page_height,
                "keynotes": vp_positions,
            }
        else:
            vp_counts = count_result

        group_counts[sheet] = vp_counts

        for num in keynote_numbers:
            combined_counts.setdefault(num, {})[sheet] = vp_counts.get(num, 0)

    # 3. Build ONE KeyNote per number with combined counts_per_plan.
    keynotes: list[KeyNote] = []
    for num, text in entries:
        refs = _find_fixture_references(text, known_fixture_codes)
        counts_per_plan = combined_counts.get(num, {})
        total = sum(counts_per_plan.values())
        keynotes.append(KeyNote(
            number=num,
            text=text,
            counts_per_plan=counts_per_plan,
            total=total,
            fixture_references=refs,
        ))
        if total > 0:
            logger.debug(
                "Viewport group: keynote %s total=%d (%s)",
                num, total, counts_per_plan,
            )

    logger.info(
        "Extracted %d keynotes for viewport group (parent=%s, siblings=%s)",
        len(keynotes),
        first.parent_sheet_code,
        [p.sheet_code for p in sibling_pages],
    )

    return keynotes, group_counts, group_positions


def extract_all_keynotes(
    plan_pages: list[PageInfo],
    pdf_pages: dict[int, Any],
    known_fixture_codes: list[str] | None = None,
    return_positions: bool = False,
) -> tuple[list[KeyNote], dict[str, dict[str, int]]] | tuple[list[KeyNote], dict[str, dict[str, int]], dict]:
    """Extract keynotes from all plan pages.

    Viewport siblings (pages sharing the same ``parent_sheet_code``) are
    processed as a group: keynote text is extracted once from the shared
    notes panel, and symbol counting is done per-viewport.  Non-viewport
    pages are processed individually.

    Args:
        plan_pages: List of page metadata for lighting plan pages.
        pdf_pages: Mapping of page_number to pdfplumber page object.
        known_fixture_codes: Optional list of known fixture codes.
        return_positions: If True, also return keynote positions.

    Returns:
        If ``return_positions`` is False:
            Tuple of ``(all_keynotes, all_counts)``.
        If True:
            Tuple of ``(all_keynotes, all_counts, all_positions)``
            where ``all_positions = {sheet_code: {"page_width": float,
            "page_height": float, "keynotes": {number: [pos, ...]}}}``.
    """
    all_keynotes: list[KeyNote] = []
    all_counts: dict[str, dict[str, int]] = {}
    all_positions: dict[str, dict] = {}

    # Group pages: viewport siblings share parent_sheet_code, others are solo.
    viewport_groups: dict[str, list[PageInfo]] = {}
    solo_pages: list[PageInfo] = []
    for pi in plan_pages:
        if pi.parent_sheet_code:
            viewport_groups.setdefault(pi.parent_sheet_code, []).append(pi)
        else:
            solo_pages.append(pi)

    # Process viewport sibling groups.
    for parent_code, siblings in viewport_groups.items():
        try:
            kn_list, grp_counts, grp_pos = _process_viewport_group(
                siblings, pdf_pages, known_fixture_codes, return_positions,
            )
        except KeyNoteExtractionError:
            logger.exception("Error extracting keynotes for viewport group %s", parent_code)
            for pi in siblings:
                sheet = pi.sheet_code or f"page_{pi.page_number}"
                all_counts[sheet] = {}
            continue

        all_keynotes.extend(kn_list)
        all_counts.update(grp_counts)
        if return_positions and grp_pos:
            all_positions.update(grp_pos)

    # Process solo (non-viewport) pages.
    for page_info in solo_pages:
        sheet = page_info.sheet_code or f"page_{page_info.page_number}"
        pdf_page = pdf_pages.get(page_info.page_number)
        if pdf_page is None:
            logger.warning(
                "No PDF page object for plan %s (page %d), skipping keynotes",
                sheet, page_info.page_number,
            )
            all_counts[sheet] = {}
            if return_positions:
                all_positions[sheet] = {
                    "page_width": 0, "page_height": 0, "keynotes": {},
                }
            continue

        try:
            page_kn, page_counts, page_pos = _process_single_plan(
                page_info, pdf_page, known_fixture_codes, return_positions,
            )
        except KeyNoteExtractionError:
            logger.exception("Error extracting keynotes from plan %s", sheet)
            all_counts[sheet] = {}
            continue

        all_counts[sheet] = page_counts
        all_keynotes.extend(page_kn)
        if return_positions and page_pos is not None:
            # Normalize to (0,0)-origin image space.
            bbox = tuple(pdf_page.bbox)
            ox, oy = bbox[0], bbox[1]
            if ox != 0.0 or oy != 0.0:
                norm_pos_solo: dict[str, list[dict]] = {}
                for kn_num, pos_list in page_pos.items():
                    norm_pos_solo[kn_num] = [
                        {
                            "x0": p["x0"] - ox, "top": p["top"] - oy,
                            "x1": p["x1"] - ox, "bottom": p["bottom"] - oy,
                            "cx": p["cx"] - ox, "cy": p["cy"] - oy,
                        }
                        for p in pos_list
                    ]
                page_pos = norm_pos_solo
            all_positions[sheet] = {
                "page_width": pdf_page.width,
                "page_height": pdf_page.height,
                "keynotes": page_pos,
            }

    # Sort by sheet (plan order), then by keynote number.
    all_sheets = [
        p.sheet_code or f"page_{p.page_number}" for p in plan_pages
    ]
    sheet_order = {s: i for i, s in enumerate(all_sheets)}

    def sort_key(kn: KeyNote) -> tuple[int, int]:
        # First plan this keynote belongs to determines sheet order.
        first_sheet = next(iter(kn.counts_per_plan), "")
        sheet_idx = sheet_order.get(first_sheet, 999)
        num = int(kn.number) if str(kn.number).isdigit() else 0
        return (sheet_idx, num)

    all_keynotes.sort(key=sort_key)

    logger.info(
        "Extracted %d keynotes across %d plan pages",
        len(all_keynotes), len(plan_pages),
    )
    if return_positions:
        return all_keynotes, all_counts, all_positions
    return all_keynotes, all_counts
