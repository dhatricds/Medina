"""Count fixture occurrences on lighting plan pages using text extraction.

Primary method: character-level pair detection from ``page.chars`` with
modal font-size filtering.  This avoids the word-splitting bug where
``extract_words()`` separates tightly-kerned labels like "A1" into
separate "A" and "1" tokens, and the grid-label false-positive bug
where large-font structural labels (e.g. column grid "E3") are counted
as fixtures.
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from typing import Any

from medina.exceptions import FixtureCountError
from medina.models import PageInfo

logger = logging.getLogger(__name__)

# Fraction of page dimensions used for exclusion zones.
_TITLE_BLOCK_X_FRAC = 0.80  # Title block starts at rightmost 20%
_TITLE_BLOCK_Y_FRAC = 0.85  # Title block starts at bottom 15%
_LEGEND_COL_X_FRAC = 0.85   # Notes/keynotes/legend column starts at rightmost 15%
_BORDER_FRAC = 0.02          # 2% border on all sides

# Maximum gap (pts) between consecutive characters in a fixture label.
_MAX_CHAR_GAP = 6.0
# Maximum vertical offset (pts) between consecutive characters.
_MAX_CHAR_DY = 3.0
# Gap within which an adjacent alphanumeric character blocks a boundary.
_BOUNDARY_GAP = 5.0
# Font-size tolerance multiplier for modal filtering (1.5 = ±50%).
_FONT_SIZE_TOLERANCE = 1.5
# Tighter tolerance for short fixture codes (≤2 chars) which are
# more prone to false positives from annotations at different sizes.
_SHORT_CODE_FONT_TOLERANCE = 1.15
# Minimum Euclidean distance (pts) between matches of the same short
# fixture code.  Matches closer than this are de-duplicated as the
# same physical fixture (duplicate labels, leader lines, etc.).
_SHORT_CODE_DEDUP_DIST = 70.0


# ---------------------------------------------------------------------------
# Exclusion-zone helpers (unchanged)
# ---------------------------------------------------------------------------

def _is_in_exclusion_zone(
    x: float,
    y: float,
    page_width: float,
    page_height: float,
    viewport_bbox: tuple[float, float, float, float] | None = None,
    legend_col_x_frac: float | None = None,
    title_block_x_frac: float | None = None,
    page_bbox: tuple[float, float, float, float] | None = None,
) -> bool:
    """Check whether a coordinate falls inside an exclusion zone.

    Exclusion zones:
    - Legend column: rightmost 15% at any height (notes, keynotes, stamps)
    - Title block: rightmost 20% AND bottom 15% (the corner box)
    - Border: outermost 2% on all four sides

    When *viewport_bbox* is set, exclusion zone fractions are computed
    relative to the viewport dimensions instead of the full page.
    Characters outside the viewport are always excluded.

    When *page_bbox* is set, use it as the actual coordinate space
    (handles PDFs with non-zero origin, e.g., bbox starting at x=-1224).
    """
    lcx = legend_col_x_frac if legend_col_x_frac is not None else _LEGEND_COL_X_FRAC
    tbx = title_block_x_frac if title_block_x_frac is not None else _TITLE_BLOCK_X_FRAC

    # Origin-aware: use page_bbox for actual coordinate space
    if page_bbox is not None:
        px0, py0, px1, py1 = page_bbox
    else:
        px0, py0, px1, py1 = 0.0, 0.0, page_width, page_height
    pw = px1 - px0
    ph = py1 - py0

    if viewport_bbox is not None:
        vx0, vy0, vx1, vy1 = viewport_bbox
        # Must be inside viewport
        if x < vx0 or x > vx1 or y < vy0 or y > vy1:
            return True
        vw = vx1 - vx0
        vh = vy1 - vy0
        # Compute border zones relative to viewport
        min_x = vx0 + vw * _BORDER_FRAC
        max_x = vx0 + vw * (1 - _BORDER_FRAC)
        min_y = vy0 + vh * _BORDER_FRAC
        max_y = vy0 + vh * (1 - _BORDER_FRAC)
        if x < min_x or x > max_x or y < min_y or y > max_y:
            return True
        # Legend and title block exclusions use FULL PAGE dimensions —
        # the legend/notes panel sits outside the viewport on the full page,
        # so computing these relative to viewport width clips real fixtures.
        if x > px0 + pw * lcx:
            return True
        if x > px0 + pw * tbx and y > py0 + ph * _TITLE_BLOCK_Y_FRAC:
            return True
        return False

    min_x = px0 + pw * _BORDER_FRAC
    max_x = px0 + pw * (1 - _BORDER_FRAC)
    min_y = py0 + ph * _BORDER_FRAC
    max_y = py0 + ph * (1 - _BORDER_FRAC)
    if x < min_x or x > max_x or y < min_y or y > max_y:
        return True

    if x > px0 + pw * lcx:
        return True

    if x > px0 + pw * tbx and y > py0 + ph * _TITLE_BLOCK_Y_FRAC:
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


# ---------------------------------------------------------------------------
# Character-level fixture detection (new — fixes BUG-001 & BUG-002)
# ---------------------------------------------------------------------------

def _find_char_sequences(
    chars: list[dict[str, Any]],
    code: str,
    page_width: float,
    page_height: float,
    schedule_bbox: tuple[float, float, float, float] | None,
    viewport_bbox: tuple[float, float, float, float] | None = None,
    iso_gap: float = 15.0,
    legend_col_x_frac: float | None = None,
    title_block_x_frac: float | None = None,
    page_bbox: tuple[float, float, float, float] | None = None,
) -> list[dict[str, Any]]:
    """Find character sequences on the page that spell *code*.

    Returns a list of match dicts with keys:
      ``x0``, ``top``, ``x1``, ``bottom``, ``cx``, ``cy``, ``font_size``,
      ``char_index`` (index into *chars* of the first character).
    """
    code_len = len(code)
    matches: list[dict[str, Any]] = []

    # For single-char codes, pre-build a y-binned spatial index for isolation
    # checks.  Bin chars by row (y rounded to nearest 3pt) for fast neighbor
    # lookup.  Two-char+ codes don't need isolation — word-boundary checks
    # are sufficient and isolation would reject valid labels on dense plans.
    _y_bins: dict[int, list[tuple[int, float, float]]] | None = None
    if code_len == 1:
        _y_bins = {}
        for ci, ch in enumerate(chars):
            y_bin = int(ch["top"] / 3)
            entry = (ci, ch["x0"], ch["x1"])
            for yb in (y_bin - 1, y_bin, y_bin + 1):
                _y_bins.setdefault(yb, []).append(entry)

    for i in range(len(chars) - code_len + 1):
        # --- 1. Check spelling ---
        valid = True
        for j in range(code_len):
            if chars[i + j]["text"] != code[j]:
                valid = False
                break
            # Adjacency with previous character in the sequence.
            if j > 0:
                prev = chars[i + j - 1]
                curr = chars[i + j]
                dx = curr["x0"] - prev["x1"]
                dy = abs(curr["top"] - prev["top"])
                if dx > _MAX_CHAR_GAP or dx < -2 or dy > _MAX_CHAR_DY:
                    valid = False
                    break
        if not valid:
            continue

        # --- 2. Word-boundary check (leading) ---
        # Use abs(dx) — content-stream order doesn't guarantee spatial order,
        # so a large negative dx means the previous char is far away, not adjacent.
        if i > 0:
            prev_c = chars[i - 1]
            dx_before = chars[i]["x0"] - prev_c["x1"]
            dy_before = abs(chars[i]["top"] - prev_c["top"])
            if (abs(dx_before) < _BOUNDARY_GAP
                    and dy_before < _MAX_CHAR_DY
                    and prev_c["text"].isalnum()):
                continue

        # --- 3. Word-boundary check (trailing) ---
        end_i = i + code_len
        if end_i < len(chars):
            next_c = chars[end_i]
            last_c = chars[end_i - 1]
            dx_after = next_c["x0"] - last_c["x1"]
            dy_after = abs(next_c["top"] - last_c["top"])
            if (abs(dx_after) < _BOUNDARY_GAP
                    and dy_after < _MAX_CHAR_DY
                    and next_c["text"].isalnum()):
                continue

        # --- 4. Isolation check for single-char codes ---
        # Single-char fixture codes (e.g., "A", "B") appear everywhere in
        # engineering text.  True fixture labels are spatially isolated —
        # no other character within ~15 pts horizontally on the same line.
        # For multi-char codes the word-boundary checks suffice; applying
        # isolation to them causes false rejections on dense plans.
        if code_len == 1 and _y_bins is not None:
            _ISO_GAP = iso_gap
            first_c = chars[i]
            last_c = chars[i + code_len - 1]
            match_x0 = first_c["x0"]
            match_x1 = last_c["x1"]
            match_y = first_c["top"]
            y_bin = int(match_y / 3)
            isolated = True
            # Check nearby chars via spatial index
            match_indices = set(range(i, i + code_len))
            for yb in (y_bin - 1, y_bin, y_bin + 1):
                for ci, cx0, cx1 in _y_bins.get(yb, []):
                    if ci in match_indices:
                        continue
                    if cx1 > match_x0 - _ISO_GAP and cx0 < match_x1 + _ISO_GAP:
                        isolated = False
                        break
                if not isolated:
                    break
            if not isolated:
                continue

        # --- 5. Position / exclusion filtering ---
        first = chars[i]
        last = chars[i + code_len - 1]
        cx = (first["x0"] + last["x1"]) / 2
        cy = (first["top"] + first["bottom"]) / 2

        if _is_in_exclusion_zone(cx, cy, page_width, page_height, viewport_bbox,
                                legend_col_x_frac=legend_col_x_frac,
                                title_block_x_frac=title_block_x_frac,
                                page_bbox=page_bbox):
            continue
        if schedule_bbox and _is_in_bbox(cx, cy, schedule_bbox):
            continue

        font_size = first.get("size", first.get("height", 0))
        matches.append({
            "x0": first["x0"],
            "top": first["top"],
            "x1": last["x1"],
            "bottom": last["bottom"],
            "cx": cx,
            "cy": cy,
            "font_size": font_size,
            "char_index": i,
        })

    return matches


def _apply_font_size_filter(
    all_matches: dict[str, list[dict[str, Any]]],
    tolerance: float = _FONT_SIZE_TOLERANCE,
    short_code_tolerance: float = _SHORT_CODE_FONT_TOLERANCE,
) -> dict[str, list[dict[str, Any]]]:
    """Remove matches whose font size deviates from the modal fixture size.

    The modal font size is computed across **all** fixture-code matches
    (not per-code) so that grid-line labels, room numbers, and title text
    — which are typically 1.5–3× larger — are rejected.
    """
    all_sizes: list[float] = []
    for matches in all_matches.values():
        all_sizes.extend(m["font_size"] for m in matches)

    if not all_sizes:
        return all_matches

    # Bin to nearest 0.5 pt for a stable mode.
    rounded = [round(s * 2) / 2 for s in all_sizes]
    size_counts = Counter(rounded)
    modal_size = size_counts.most_common(1)[0][0]

    if modal_size <= 0:
        return all_matches

    lo = modal_size / tolerance
    hi = modal_size * tolerance

    filtered: dict[str, list[dict[str, Any]]] = {}
    for code, matches in all_matches.items():
        # Single-char codes get a tighter font tolerance to reject
        # annotation text at slightly different sizes.  Two-char+ codes
        # keep the normal tolerance since they're less ambiguous.
        if len(code) == 1:
            code_lo = modal_size / short_code_tolerance
            code_hi = modal_size * short_code_tolerance
        else:
            code_lo, code_hi = lo, hi

        kept = [m for m in matches if code_lo <= round(m["font_size"] * 2) / 2 <= code_hi]
        removed = len(matches) - len(kept)
        if removed:
            logger.debug(
                "Font-size filter removed %d/%d matches for %s "
                "(modal=%.1f, range=%.1f–%.1f)",
                removed, len(matches), code, modal_size, code_lo, code_hi,
            )
        filtered[code] = kept

    return filtered


# ---------------------------------------------------------------------------
# Spatial de-duplication for short codes
# ---------------------------------------------------------------------------

def _deduplicate_nearby_matches(
    matches: list[dict[str, Any]],
    min_distance: float = _SHORT_CODE_DEDUP_DIST,
) -> list[dict[str, Any]]:
    """Merge matches of the same fixture code that are spatially close.

    On some drawings the same fixture label appears twice near a single
    fixture symbol (e.g., one inside the symbol and one on a leader line).
    This creates duplicate counts for the same physical fixture.

    Uses greedy clustering: sort by position, mark every match within
    *min_distance* of an already-kept match as a duplicate.
    """
    if len(matches) <= 1:
        return matches

    # Sort by y then x for stable ordering.
    ordered = sorted(matches, key=lambda m: (m["cy"], m["cx"]))
    kept: list[dict[str, Any]] = []

    for m in ordered:
        is_dup = False
        for k in kept:
            dist = ((m["cx"] - k["cx"]) ** 2
                    + (m["cy"] - k["cy"]) ** 2) ** 0.5
            if dist < min_distance:
                is_dup = True
                break
        if not is_dup:
            kept.append(m)

    return kept


# ---------------------------------------------------------------------------
# Cross-reference filtering for sheet-code fixtures
# ---------------------------------------------------------------------------

_CROSSREF_WORDS = {"see", "sheet", "refer", "reference", "plan", "dwg", "drawing"}


def _is_near_crossref(
    match: dict[str, Any],
    words: list[dict[str, Any]],
    max_dx: float = 60.0,
    max_dy: float = 10.0,
) -> bool:
    """Return True if a cross-reference word appears just left of *match*."""
    mx, my = match["cx"], match["cy"]
    for w in words:
        wx = (w["x0"] + w["x1"]) / 2
        wy = (w["top"] + w["bottom"]) / 2
        if wx < mx and abs(wy - my) < max_dy and (mx - wx) < max_dx:
            if w["text"].lower().strip(".,;:()") in _CROSSREF_WORDS:
                return True
    return False


def _extract_plan_words(
    pdf_page: Any,
    schedule_bbox: tuple[float, float, float, float] | None = None,
    viewport_bbox: tuple[float, float, float, float] | None = None,
) -> list[dict[str, Any]]:
    """Extract words from a pdfplumber page, filtering out exclusion zones.

    Used only for cross-reference context lookup (not for counting).
    """
    page_width = pdf_page.width
    page_height = pdf_page.height
    page_bbox = tuple(pdf_page.bbox)

    words = pdf_page.extract_words(
        x_tolerance=3,
        y_tolerance=3,
        keep_blank_chars=False,
    )

    filtered: list[dict[str, Any]] = []
    for w in words:
        cx = (w["x0"] + w["x1"]) / 2
        cy = (w["top"] + w["bottom"]) / 2
        if _is_in_exclusion_zone(cx, cy, page_width, page_height, viewport_bbox,
                                page_bbox=page_bbox):
            continue
        if schedule_bbox and _is_in_bbox(cx, cy, schedule_bbox):
            continue
        filtered.append(w)

    return filtered


# ---------------------------------------------------------------------------
# Legacy word-level helpers (kept for backward compatibility)
# ---------------------------------------------------------------------------

def _build_code_pattern(code: str) -> re.Pattern[str]:
    """Build a regex pattern that matches a fixture code with word boundaries."""
    m = re.match(r'^([A-Za-z]+)(\d+)$', code)
    if m:
        letters, digits = m.group(1), m.group(2)
        escaped = re.escape(letters) + r'-?' + re.escape(digits)
    else:
        escaped = re.escape(code)
    return re.compile(
        r'(?<![A-Za-z0-9])' + escaped + r'(?![A-Za-z0-9])',
        re.IGNORECASE,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def count_fixtures_on_plan(
    page_info: PageInfo,
    pdf_page: Any,
    fixture_codes: list[str],
    plan_sheet_codes: list[str] | None = None,
    return_positions: bool = False,
    rejected_positions: dict[str, list[dict[str, float]]] | None = None,
    added_positions: dict[str, list[dict[str, float]]] | None = None,
    runtime_params: dict[str, Any] | None = None,
) -> dict[str, int] | dict[str, dict]:
    """Count occurrences of each fixture code on a single lighting plan page.

    Uses **character-level** detection from ``page.chars`` with modal
    font-size filtering.  For fixture codes that match a plan sheet code,
    an additional cross-reference filter removes occurrences preceded by
    words like "SEE", "SHEET", etc.

    Args:
        page_info: Page metadata.
        pdf_page: pdfplumber page object.
        fixture_codes: List of fixture type codes to search for
            (e.g., ``["A1", "B6", "D7"]``).
        plan_sheet_codes: Optional list of known plan sheet codes. Fixture
            codes that match a sheet code get extra filtering to avoid
            counting cross-reference labels (e.g., "SEE E1A").
        return_positions: If True, return enriched dict with positions.
        rejected_positions: Optional per-code list of positions the user
            flagged as incorrect. Matches near these positions are excluded.
            Format: ``{fixture_code: [{x0, top, x1, bottom, cx, cy}, ...]}``
        added_positions: Optional per-code list of positions the user
            identified as missed fixtures. These are added to the count.
            Format: ``{fixture_code: [{x0, top, x1, bottom, cx, cy}, ...]}``

    Returns:
        If ``return_positions`` is False: ``{fixture_code: count}``.
        If True: ``{fixture_code: {"count": int, "positions": [...]}}``
        where each position has ``x0, top, x1, bottom, cx, cy``.

    Raises:
        FixtureCountError: If text extraction fails critically.
    """
    # Resolve runtime parameter overrides (local, thread-safe)
    p = runtime_params or {}
    eff_title_block_x = p.get("title_block_frac", _TITLE_BLOCK_X_FRAC)
    eff_legend_col_x = p.get("legend_col_x_frac", _LEGEND_COL_X_FRAC)
    eff_font_tol = p.get("font_size_tolerance_multi", _FONT_SIZE_TOLERANCE)
    eff_short_font_tol = p.get("font_size_tolerance_single", _SHORT_CODE_FONT_TOLERANCE)
    eff_dedup_dist = p.get("dedup_distance", _SHORT_CODE_DEDUP_DIST)
    eff_iso_gap = p.get("isolation_distance", 15.0)

    sheet = page_info.sheet_code or f"page_{page_info.page_number}"
    logger.info("Counting fixtures on plan %s (page %d)", sheet, page_info.page_number)

    if not fixture_codes:
        logger.warning("No fixture codes provided for plan %s", sheet)
        return {} if not return_positions else {}

    try:
        chars = pdf_page.chars
    except Exception as exc:
        raise FixtureCountError(
            f"Failed to extract characters from plan {sheet}: {exc}"
        ) from exc

    if not chars:
        logger.warning("No characters found on plan %s", sheet)
        if return_positions:
            return {code: {"count": 0, "positions": []} for code in fixture_codes}
        return {code: 0 for code in fixture_codes}

    page_width = pdf_page.width
    page_height = pdf_page.height
    page_bbox = tuple(pdf_page.bbox)
    schedule_bbox = _find_schedule_table_bbox(pdf_page)
    viewport_bbox = page_info.viewport_bbox

    # --- Step 1: character-level detection for every code ---
    all_matches: dict[str, list[dict[str, Any]]] = {}
    for code in fixture_codes:
        all_matches[code] = _find_char_sequences(
            chars, code, page_width, page_height, schedule_bbox,
            viewport_bbox=viewport_bbox,
            iso_gap=eff_iso_gap,
            legend_col_x_frac=eff_legend_col_x,
            title_block_x_frac=eff_title_block_x,
            page_bbox=page_bbox,
        )

    # --- Step 2: modal font-size filtering ---
    all_matches = _apply_font_size_filter(
        all_matches, tolerance=eff_font_tol, short_code_tolerance=eff_short_font_tol,
    )

    # --- Step 2.5: spatial de-duplication for single-char codes ---
    # Single-char fixture codes (e.g. "A") can appear twice near the same
    # fixture symbol.  Merge matches within _SHORT_CODE_DEDUP_DIST.
    for code in fixture_codes:
        if len(code) == 1 and len(all_matches.get(code, [])) > 1:
            before = len(all_matches[code])
            all_matches[code] = _deduplicate_nearby_matches(all_matches[code], min_distance=eff_dedup_dist)
            removed = before - len(all_matches[code])
            if removed:
                logger.debug(
                    "De-dup removed %d/%d matches for %s on %s",
                    removed, before, code, sheet,
                )

    # --- Step 3: cross-reference filtering for sheet-code fixtures ---
    sheet_code_set = {c.upper() for c in (plan_sheet_codes or [])}
    if sheet_code_set:
        words: list[dict[str, Any]] | None = None  # lazy-load
        for code in fixture_codes:
            if code.upper() not in sheet_code_set:
                continue
            if words is None:
                words = _extract_plan_words(pdf_page, schedule_bbox, viewport_bbox)
            before = len(all_matches[code])
            all_matches[code] = [
                m for m in all_matches[code]
                if not _is_near_crossref(m, words)
            ]
            removed = before - len(all_matches[code])
            if removed:
                logger.debug(
                    "Cross-ref filter removed %d/%d matches for %s on %s",
                    removed, before, code, sheet,
                )

    # --- Step 4: rejected position filtering (human-in-the-loop) ---
    # The user flagged specific marker positions as incorrect.  Remove any
    # match whose center is within 15 pts of a rejected position so the
    # pipeline doesn't repeat the same mistake.
    _REJECT_RADIUS = 15.0
    if rejected_positions:
        for code in fixture_codes:
            rejects = rejected_positions.get(code, [])
            if not rejects or not all_matches.get(code):
                continue
            before = len(all_matches[code])
            kept = []
            for m in all_matches[code]:
                is_rejected = False
                for rp in rejects:
                    dist = ((m["cx"] - rp["cx"]) ** 2
                            + (m["cy"] - rp["cy"]) ** 2) ** 0.5
                    if dist < _REJECT_RADIUS:
                        is_rejected = True
                        break
                if not is_rejected:
                    kept.append(m)
            all_matches[code] = kept
            removed = before - len(kept)
            if removed:
                logger.info(
                    "User rejection filter removed %d/%d matches for %s on %s",
                    removed, before, code, sheet,
                )

    # --- Step 5: inject user-added positions (human-in-the-loop) ---
    # The user clicked on the plan where the pipeline missed a fixture.
    # Add these as real matches so the count includes them and the
    # positions show up in the output.  Skip any added position that
    # is already near an existing match (within 15pts) to avoid doubles.
    if added_positions:
        for code in fixture_codes:
            adds = added_positions.get(code, [])
            if not adds:
                continue
            existing = all_matches.get(code, [])
            injected = 0
            for ap in adds:
                already_found = False
                for m in existing:
                    dist = ((m["cx"] - ap["cx"]) ** 2
                            + (m["cy"] - ap["cy"]) ** 2) ** 0.5
                    if dist < _REJECT_RADIUS:
                        already_found = True
                        break
                if not already_found:
                    all_matches.setdefault(code, []).append({
                        "x0": ap.get("x0", ap["cx"] - 10),
                        "top": ap.get("top", ap["cy"] - 10),
                        "x1": ap.get("x1", ap["cx"] + 10),
                        "bottom": ap.get("bottom", ap["cy"] + 10),
                        "cx": ap["cx"],
                        "cy": ap["cy"],
                        "font_size": 0,  # user-added, no font
                        "char_index": -1,  # sentinel: not from text
                        "user_added": True,
                    })
                    injected += 1
            if injected:
                logger.info(
                    "User added %d position(s) for %s on %s",
                    injected, code, sheet,
                )

    # --- Build final counts ---
    counts: dict[str, int] = {}
    for code in fixture_codes:
        counts[code] = len(all_matches[code])
        if counts[code] > 0:
            logger.debug(
                "Plan %s: fixture %s found %d times%s",
                sheet, code, counts[code],
                " (sheet-code filtered)" if code.upper() in sheet_code_set else "",
            )

    total = sum(counts.values())
    logger.info(
        "Plan %s: found %d total fixture instances across %d types",
        sheet, total, sum(1 for c in counts.values() if c > 0),
    )

    if return_positions:
        result: dict[str, dict] = {}
        for code in fixture_codes:
            result[code] = {
                "count": counts[code],
                "positions": [
                    {
                        "x0": m["x0"],
                        "top": m["top"],
                        "x1": m["x1"],
                        "bottom": m["bottom"],
                        "cx": m["cx"],
                        "cy": m["cy"],
                    }
                    for m in all_matches[code]
                ],
            }
        return result

    return counts


def count_all_plans(
    plan_pages: list[PageInfo],
    pdf_pages: dict[int, Any],
    fixture_codes: list[str],
    plan_sheet_codes: list[str] | None = None,
    return_positions: bool = False,
    all_rejected_positions: dict[str, dict[str, list[dict[str, float]]]] | None = None,
    all_added_positions: dict[str, dict[str, list[dict[str, float]]]] | None = None,
    runtime_params: dict[str, Any] | None = None,
) -> dict[str, dict[str, int]] | tuple[dict[str, dict[str, int]], dict]:
    """Count fixtures on all lighting plan pages.

    Args:
        plan_pages: List of page metadata for lighting plan pages.
        pdf_pages: Mapping of page_number to pdfplumber page object.
        fixture_codes: Fixture type codes to search for.
        plan_sheet_codes: Optional list of known plan sheet codes for
            cross-reference filtering.
        return_positions: If True, also return position data.
        all_rejected_positions: Optional per-code per-plan rejected
            positions from user feedback.  Format:
            ``{fixture_code: {sheet_code: [{x0, top, ...}, ...]}}``.
        all_added_positions: Optional per-code per-plan user-added
            positions from feedback.  Format same as rejected.

    Returns:
        If ``return_positions`` is False:
            ``{sheet_code: {fixture_code: count}}``.
        If True:
            Tuple of ``(counts_dict, positions_dict)`` where
            ``positions_dict = {sheet_code: {"page_width": float,
            "page_height": float, "fixtures": {code: [pos, ...]}}}``.
    """
    results: dict[str, dict[str, int]] = {}
    all_positions: dict[str, dict] = {}

    for page_info in plan_pages:
        sheet = page_info.sheet_code or f"page_{page_info.page_number}"
        pdf_page = pdf_pages.get(page_info.page_number)
        if pdf_page is None:
            logger.warning(
                "No PDF page object for plan %s (page %d), skipping",
                sheet, page_info.page_number,
            )
            results[sheet] = {code: 0 for code in fixture_codes}
            if return_positions:
                all_positions[sheet] = {
                    "page_width": 0, "page_height": 0, "fixtures": {},
                }
            continue

        # Build per-code rejected/added positions for this specific plan page
        plan_rejects: dict[str, list[dict[str, float]]] | None = None
        if all_rejected_positions:
            plan_rejects = {}
            for code, per_plan in all_rejected_positions.items():
                rp = per_plan.get(sheet, [])
                if rp:
                    plan_rejects[code] = rp
            if not plan_rejects:
                plan_rejects = None

        plan_adds: dict[str, list[dict[str, float]]] | None = None
        if all_added_positions:
            plan_adds = {}
            for code, per_plan in all_added_positions.items():
                ap = per_plan.get(sheet, [])
                if ap:
                    plan_adds[code] = ap
            if not plan_adds:
                plan_adds = None

        try:
            raw = count_fixtures_on_plan(
                page_info, pdf_page, fixture_codes,
                plan_sheet_codes=plan_sheet_codes,
                return_positions=return_positions,
                rejected_positions=plan_rejects,
                added_positions=plan_adds,
                runtime_params=runtime_params,
            )
        except FixtureCountError:
            logger.exception("Error counting fixtures on plan %s", sheet)
            raw = {code: 0 for code in fixture_codes}

        if return_positions and isinstance(raw, dict) and raw:
            first_val = next(iter(raw.values()), None)
            if isinstance(first_val, dict):
                # Enriched format: {code: {"count": int, "positions": [...]}}
                results[sheet] = {
                    code: raw[code]["count"] for code in fixture_codes
                }
                # Normalize positions from native bbox space to
                # (0,0)-origin image space for rendering overlay.
                bbox = tuple(pdf_page.bbox)
                ox, oy = bbox[0], bbox[1]
                fixtures_pos: dict[str, list[dict]] = {}
                for code in fixture_codes:
                    raw_list = raw[code]["positions"]
                    if ox != 0.0 or oy != 0.0:
                        fixtures_pos[code] = [
                            {
                                "x0": p["x0"] - ox,
                                "top": p["top"] - oy,
                                "x1": p["x1"] - ox,
                                "bottom": p["bottom"] - oy,
                                "cx": p["cx"] - ox,
                                "cy": p["cy"] - oy,
                            }
                            for p in raw_list
                        ]
                    else:
                        fixtures_pos[code] = raw_list
                all_positions[sheet] = {
                    "page_width": pdf_page.width,
                    "page_height": pdf_page.height,
                    "fixtures": fixtures_pos,
                }
            else:
                results[sheet] = raw  # type: ignore[assignment]
        else:
            results[sheet] = raw  # type: ignore[assignment]

    if return_positions:
        return results, all_positions
    return results
