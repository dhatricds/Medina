"""Sheet index discovery and parsing from cover/legend pages."""

from __future__ import annotations

import logging
import re
from typing import Any

from medina.models import PageInfo, PageType, SheetIndexEntry

logger = logging.getLogger(__name__)

# Keywords used to infer page type from sheet description.
_TYPE_KEYWORDS: list[tuple[list[str], PageType]] = [
    # Demolition MUST be checked before lighting plan so that
    # "DEMOLITION LIGHTING PLAN" is classified as demolition.
    (["demolition", "demo plan", "demo "], PageType.DEMOLITION_PLAN),
    (["lighting plan", "lighting layout", "lighting area",
      "electrical lighting"],
     PageType.LIGHTING_PLAN),
    (["schedule"], PageType.SCHEDULE),
    (
        ["symbol", "abbreviation", "legend"],
        PageType.SYMBOLS_LEGEND,
    ),
    (["power plan", "power layout", "power area"], PageType.POWER_PLAN),
    (["signal plan", "signal layout"], PageType.OTHER),
    (["site plan", "site layout"], PageType.SITE_PLAN),
    (["fire alarm"], PageType.FIRE_ALARM),
    (["riser"], PageType.RISER),
    (["detail"], PageType.DETAIL),
    (
        ["cover sheet", "title sheet", "coversheet"],
        PageType.COVER,
    ),
]

# Pattern to match a sheet code at the start of a text line.
# Examples: E200, E1A, E7A, E001, CS, E1.11R, FE10691-013
_LINE_CODE_RE = re.compile(
    r"^([A-Za-z]{1,3}[\d]+(?:\.\d+)?[A-Za-z]{0,2})\b"
)

# Pattern for lines that look like "E200  LIGHTING PLAN - LOWER LEVEL"
_TEXT_INDEX_RE = re.compile(
    r"^([A-Za-z]{1,3}[\d]+(?:\.\d+)?[A-Za-z]{0,2})"
    r"\s{2,}"
    r"(.+)$",
)

# Pattern for non-standard codes like "FE10691-013  SCHEDULES"
_NONSTANDARD_INDEX_RE = re.compile(
    r"^([A-Za-z]{1,3}\d{3,}[-]\d{2,3})"
    r"\s{2,}"
    r"(.+)$",
)

# Alternate pattern: "SHEET NUMBER  SHEET NAME" style (code on right)
_REVERSE_INDEX_RE = re.compile(
    r"^(.+?)\s{2,}"
    r"([A-Za-z]{1,3}[\d]+(?:\.\d+)?[A-Za-z]{0,2})$",
)


def discover_sheet_index(
    pages: list[PageInfo],
    pdf_pages: dict[int, Any],
) -> list[SheetIndexEntry]:
    """Find and parse the sheet index from the cover/legend page.

    Searches for the sheet index on likely cover/legend pages and
    returns parsed entries with inferred page types.

    Args:
        pages: List of loaded PageInfo objects.
        pdf_pages: Dict mapping page_number to pdfplumber page.

    Returns:
        List of SheetIndexEntry. May be empty if no index is found.
    """
    candidate_pages = _find_candidate_pages(pages)
    logger.debug(
        "Sheet index candidate pages: %s",
        [p.page_number for p in candidate_pages],
    )

    for page_info in candidate_pages:
        pdfp_page = pdf_pages.get(page_info.page_number)
        if pdfp_page is None:
            continue

        entries = _try_table_extraction(pdfp_page)
        if entries:
            logger.info(
                "Sheet index found via table extraction on "
                "page %d (%d entries)",
                page_info.page_number,
                len(entries),
            )
            return entries

        entries = _try_text_extraction(pdfp_page)
        if entries:
            logger.info(
                "Sheet index found via text extraction on "
                "page %d (%d entries)",
                page_info.page_number,
                len(entries),
            )
            return entries

    logger.warning("No sheet index found on any candidate page")
    return []


def _find_candidate_pages(
    pages: list[PageInfo],
) -> list[PageInfo]:
    """Identify pages most likely to contain the sheet index.

    Prioritises: page 1, then pages with cover/symbol/legend
    indicators in their sheet_code or sheet_title.
    """
    candidates: list[PageInfo] = []
    rest: list[PageInfo] = []

    cover_keywords = (
        "cover", "symbol", "abbreviation", "legend",
        "title sheet", "e000", "e0", "cs",
    )

    for page in pages:
        searchable = " ".join(
            filter(
                None,
                [
                    page.sheet_code,
                    page.sheet_title,
                    str(page.source_path.stem),
                ],
            )
        ).lower()

        if any(kw in searchable for kw in cover_keywords):
            candidates.append(page)
        else:
            rest.append(page)

    # Always include page 1 as a candidate if not already there.
    if pages and pages[0] not in candidates:
        candidates.insert(0, pages[0])

    # Also check page 2 in case page 1 is a cover with no index.
    if len(pages) > 1 and pages[1] not in candidates:
        candidates.append(pages[1])

    return candidates


# ── Table-based extraction ──────────────────────────────────────


def _try_table_extraction(
    page: Any,
) -> list[SheetIndexEntry]:
    """Attempt to extract the sheet index from pdfplumber tables."""
    try:
        tables = page.extract_tables(
            table_settings={
                "vertical_strategy": "lines",
                "horizontal_strategy": "lines",
                "snap_tolerance": 5,
                "join_tolerance": 5,
            }
        )
    except Exception as exc:
        logger.debug("Table extraction failed: %s", exc)
        tables = []

    if not tables:
        # Try with text strategy as fallback.
        try:
            tables = page.extract_tables(
                table_settings={
                    "vertical_strategy": "text",
                    "horizontal_strategy": "text",
                    "snap_tolerance": 5,
                    "join_tolerance": 5,
                }
            )
        except Exception:
            tables = []

    entries: list[SheetIndexEntry] = []
    for table in tables:
        parsed = _parse_table_for_index(table)
        entries.extend(parsed)

    return entries


def _parse_table_for_index(
    table: list[list[str | None]],
) -> list[SheetIndexEntry]:
    """Parse a single pdfplumber table looking for sheet index rows."""
    if not table or len(table) < 2:
        return []

    # Try to identify which columns hold the code and description.
    code_col, desc_col = _identify_columns(table)
    if code_col is None or desc_col is None:
        return []

    entries: list[SheetIndexEntry] = []
    _code_re = re.compile(
        r"^[A-Za-z]{1,3}[\d]+(?:[.\-]\d+)?[A-Za-z]{0,2}$"
    )

    # Determine start row: skip header if it exists.
    start = 1
    if table[0]:
        first_cell = (table[0][code_col] or "").strip()
        # If the first row has a valid sheet code in the code col,
        # there is no header row — start from row 0.
        if _code_re.match(first_cell):
            start = 0

    for row in table[start:]:
        if not row or len(row) <= max(code_col, desc_col):
            continue

        raw_code = (row[code_col] or "").strip()
        raw_desc = (row[desc_col] or "").strip()

        if not raw_code or not raw_desc:
            continue

        # Handle multi-line cells: pdfplumber sometimes merges
        # adjacent rows into a single cell with newlines.
        code_lines = raw_code.split("\n")
        desc_lines = raw_desc.split("\n")

        # If code and desc have matching number of lines,
        # treat each line pair as a separate entry.
        if len(code_lines) > 1 and len(code_lines) == len(desc_lines):
            for c_line, d_line in zip(code_lines, desc_lines):
                code = c_line.strip()
                desc = d_line.strip()
                if code and desc and _code_re.match(code):
                    entries.append(
                        SheetIndexEntry(
                            sheet_code=code.upper(),
                            description=desc,
                            inferred_type=_infer_type(desc),
                        )
                    )
            continue

        # Single-value cell: clean up whitespace.
        code = re.sub(r"\s+", " ", raw_code).strip()
        desc = re.sub(r"\s+", " ", raw_desc).strip()

        # Validate that code looks like a sheet code.
        # Standard: E200, E1A, CS, E1.11R
        # Non-standard: FE10691-013
        if not _code_re.match(code):
            continue

        entries.append(
            SheetIndexEntry(
                sheet_code=code.upper(),
                description=desc,
                inferred_type=_infer_type(desc),
            )
        )

    return entries


def _identify_columns(
    table: list[list[str | None]],
) -> tuple[int | None, int | None]:
    """Identify the code and description column indices."""
    if not table:
        return None, None

    header = table[0]
    if not header:
        return None, None

    code_col: int | None = None
    desc_col: int | None = None

    code_labels = (
        "sheet", "number", "no", "code", "dwg", "drawing",
    )
    desc_labels = (
        "description", "name", "title", "sheet name",
    )

    # Find all candidate columns for code and desc.
    code_candidates: list[int] = []
    desc_candidates: list[int] = []

    for idx, cell in enumerate(header):
        cell_lower = " ".join(
            (cell or "").strip().lower().split()
        )
        if not cell_lower:
            continue
        if any(lbl in cell_lower for lbl in code_labels):
            code_candidates.append(idx)
        if any(lbl in cell_lower for lbl in desc_labels):
            desc_candidates.append(idx)

    if code_candidates:
        code_col = code_candidates[-1]  # prefer rightmost
    if desc_candidates:
        # Prefer the desc column closest to (and after) the code col
        if code_col is not None:
            after = [d for d in desc_candidates if d > code_col]
            if after:
                desc_col = min(after)
            else:
                desc_col = desc_candidates[-1]
        else:
            desc_col = desc_candidates[-1]

    # If headers weren't recognized, heuristic: first col with
    # short alphanumeric values is the code, widest text is desc.
    if code_col is None or desc_col is None:
        return _guess_columns(table)

    return code_col, desc_col


def _guess_columns(
    table: list[list[str | None]],
) -> tuple[int | None, int | None]:
    """Heuristic to guess code and description columns."""
    if len(table) < 2:
        return None, None

    num_cols = max(len(row) for row in table if row)
    if num_cols < 2:
        return None, None

    # Score each column: short alphanumeric → likely code,
    # long text → likely description.
    code_scores = [0] * num_cols
    desc_scores = [0] * num_cols

    sheet_code_re = re.compile(
        r"^[A-Za-z]{1,3}\d+(?:\.\d+)?[A-Za-z]{0,2}$"
    )

    for row in table[1:]:
        if not row:
            continue
        for col_idx in range(min(len(row), num_cols)):
            val = (row[col_idx] or "").strip()
            if not val:
                continue
            if sheet_code_re.match(val):
                code_scores[col_idx] += 2
            elif len(val) <= 10:
                code_scores[col_idx] += 1
            if len(val) > 15:
                desc_scores[col_idx] += 1

    best_code = max(
        range(num_cols), key=lambda i: code_scores[i]
    )
    best_desc = max(
        (i for i in range(num_cols) if i != best_code),
        key=lambda i: desc_scores[i],
        default=None,
    )

    if code_scores[best_code] == 0 or best_desc is None:
        return None, None

    return best_code, best_desc


# ── Text-based extraction ───────────────────────────────────────


def _try_text_extraction(
    page: Any,
) -> list[SheetIndexEntry]:
    """Attempt to parse the sheet index from raw page text."""
    try:
        text = page.extract_text() or ""
    except Exception as exc:
        logger.debug("Text extraction failed: %s", exc)
        return []

    if not text:
        return []

    lines = text.split("\n")
    entries: list[SheetIndexEntry] = []

    for line in lines:
        line = line.strip()
        if not line:
            continue

        parsed = _parse_index_line(line)
        if isinstance(parsed, list):
            entries.extend(parsed)
        elif parsed:
            entries.append(parsed)

    # Deduplicate by sheet_code
    seen: set[str] = set()
    deduped: list[SheetIndexEntry] = []
    for entry in entries:
        if entry.sheet_code not in seen:
            seen.add(entry.sheet_code)
            deduped.append(entry)

    # Only return if we found a reasonable number of entries.
    if len(deduped) >= 2:
        return deduped
    return []


# Embedded pattern: sheet code appears mid-line
# e.g. "... MW MICROWAVE E000 ELECTRICAL SYMBOLS AND ABBREVIATIONS ..."
_EMBEDDED_CODE_RE = re.compile(
    r"(E\d{1,3}[A-Za-z]?)\s+"
    r"([A-Z][A-Z][A-Z /&,.\-]+(?:PLAN|SCHEDULE|LEVEL|SHEET"
    r"|ABBREVIATION|SYMBOL|LEGEND|DETAIL|DIAGRAM|LAYOUT"
    r"|RISER|ALARM)[A-Z /&,.\-]*)",
)


def _parse_index_line(
    line: str,
) -> SheetIndexEntry | list[SheetIndexEntry] | None:
    """Try to parse a single line as a sheet index entry."""
    # Pattern: "E200  LIGHTING PLAN - LOWER LEVEL"
    match = _TEXT_INDEX_RE.match(line)
    if not match:
        # Try non-standard pattern: "FE10691-013  SCHEDULES"
        match = _NONSTANDARD_INDEX_RE.match(line)
    if match:
        code = match.group(1).strip().upper()
        desc = match.group(2).strip()
        return SheetIndexEntry(
            sheet_code=code,
            description=desc,
            inferred_type=_infer_type(desc),
        )

    # Reverse pattern: "LIGHTING PLAN  E200"
    match = _REVERSE_INDEX_RE.match(line)
    if match:
        desc = match.group(1).strip()
        code = match.group(2).strip().upper()
        return SheetIndexEntry(
            sheet_code=code,
            description=desc,
            inferred_type=_infer_type(desc),
        )

    # Embedded pattern: code + description found mid-line
    # (common when pdfplumber merges columns)
    matches = _EMBEDDED_CODE_RE.findall(line)
    if matches:
        results: list[SheetIndexEntry] = []
        for code_str, desc_str in matches:
            code = code_str.strip().upper()
            desc = desc_str.strip()
            # Clean trailing artifacts
            desc = re.sub(
                r"\s*(CONSTRUCTION DOCUMENTS|NO\.|DATE).*$",
                "",
                desc,
            ).strip()
            if desc:
                results.append(SheetIndexEntry(
                    sheet_code=code,
                    description=desc,
                    inferred_type=_infer_type(desc),
                ))
        if results:
            return results

    return None


# ── Type inference ──────────────────────────────────────────────


def _infer_type(description: str) -> PageType | None:
    """Infer the page type from a sheet description string."""
    desc_lower = description.lower()
    for keywords, page_type in _TYPE_KEYWORDS:
        if any(kw in desc_lower for kw in keywords):
            return page_type
    return None
