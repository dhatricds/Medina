"""Parse raw schedule tables into FixtureRecord objects."""

from __future__ import annotations

import logging
import re
from typing import Any

from medina.exceptions import ScheduleExtractionError
from medina.models import FixtureRecord, PageInfo
from medina.schedule.extractor import extract_schedule_tables

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Column-name mapping: each target field has a ranked list of patterns.
# Patterns are checked case-insensitively via substring matching.
# ---------------------------------------------------------------------------

_COLUMN_PATTERNS: dict[str, list[str]] = {
    "code": [
        "fixture id",
        "id",
        "mark",
        "fixture type",
        "fixture letter",
        "type",
        "fixture",
        "symbol",
        "designation",
    ],
    "description": [
        "fixture description",
        "luminaire type",
        "description",
        "desc",
    ],
    "mounting": [
        "mounting type",
        "mounting style",
        "mounting",
        "mount",
        "mtg",
    ],
    "fixture_style": [
        "fixture style",
        "fixture type",
        "style",
        "catalog",
    ],
    "voltage": [
        "voltage",
        "volts",
    ],
    "lumens": [
        "rated lumen",
        "lumen output",
        "light output",
        "lumens",
        "lumen/watts",
        "lum",
        "lamps",
    ],
    "cct": [
        "color temperature",
        "color temp",
        "color",
        "cct",
        "kelvin",
    ],
    "dimming": [
        "ballast/driver",
        "ballast driver",
        "dimming",
        "dim",
        "driver",
        "ballast",
    ],
    "max_va": [
        "max wattage",
        "max va",
        "input watts",
        "wattage",
        "watts",
        "va",
    ],
}

# Fields that are considered "strong" header indicators (helps identify
# the header row when many column names look ambiguous).
_STRONG_FIELDS = {"code", "description", "voltage", "mounting", "lumens"}


def _normalise(text: str) -> str:
    """Lower-case, strip, and collapse whitespace for matching."""
    return " ".join(text.lower().split())


def _map_columns(header_row: list[str]) -> dict[int, str]:
    """Map column indices to FixtureRecord field names.

    Returns a dict ``{column_index: field_name}``.
    A column is only mapped once; the first (highest-priority) pattern wins.
    """
    mapped: dict[int, str] = {}
    used_fields: set[str] = set()

    # Build normalised header list.
    normalised = [_normalise(cell) for cell in header_row]

    # Iterate fields in a stable order; for each field try patterns from
    # highest to lowest priority. Short patterns (<=3 chars) require
    # exact match to avoid false substring hits (e.g. "tag" in "voltage").
    for field, patterns in _COLUMN_PATTERNS.items():
        if field in used_fields:
            continue
        for pattern in patterns:
            for col_idx, cell in enumerate(normalised):
                if col_idx in mapped:
                    continue
                if len(pattern) <= 3:
                    match = pattern == cell
                else:
                    match = pattern == cell or pattern in cell
                if match:
                    mapped[col_idx] = field
                    used_fields.add(field)
                    break
            if field in used_fields:
                break

    # Special handling: single-letter "V" for voltage (only if voltage not
    # already mapped) — must be an exact match.
    if "voltage" not in used_fields:
        for col_idx, cell in enumerate(normalised):
            if col_idx not in mapped and cell == "v":
                mapped[col_idx] = "voltage"
                used_fields.add("voltage")
                break

    return mapped


def _score_header_candidate(row: list[str]) -> int:
    """Score how likely *row* is the header row.

    Higher score = more likely a header.
    """
    mapping = _map_columns(row)
    if not mapping:
        return 0
    score = len(mapping)
    # Bonus for mapping strong indicator fields.
    for field in _STRONG_FIELDS:
        if field in mapping.values():
            score += 2
    return score


def _merge_header_rows(
    row1: list[str], row2: list[str],
) -> list[str]:
    """Merge two header rows, combining content where row1 is a group header."""
    merged = []
    for i in range(max(len(row1), len(row2))):
        v1 = row1[i].strip() if i < len(row1) else ""
        v2 = row2[i].strip() if i < len(row2) else ""
        if v1 and v2:
            merged.append(f"{v1} {v2}")
        else:
            merged.append(v1 or v2)
    return merged


def _find_header_row(
    table: list[list[str]],
) -> tuple[int, dict[int, str]]:
    """Find the header row index and its column mapping.

    Also handles split headers where row 0 has group names and row 1
    has sub-column names.

    Returns (row_index, column_mapping).

    Raises ScheduleExtractionError if no usable header is found.
    """
    best_idx = -1
    best_score = 0
    best_mapping: dict[int, str] = {}

    search_limit = min(len(table), 10)
    for idx in range(search_limit):
        score = _score_header_candidate(table[idx])
        if score > best_score:
            best_score = score
            best_idx = idx
            best_mapping = _map_columns(table[idx])

    # Try merging consecutive rows as split headers.
    for idx in range(min(search_limit - 1, len(table) - 1)):
        merged = _merge_header_rows(table[idx], table[idx + 1])
        score = _score_header_candidate(merged)
        if score > best_score:
            best_score = score
            best_idx = idx + 1  # Data starts after row idx+1
            best_mapping = _map_columns(merged)

    if best_idx == -1 or "code" not in best_mapping.values():
        raise ScheduleExtractionError(
            "Could not identify a header row with a fixture type/code column"
        )

    return best_idx, best_mapping


def _extract_embedded_data_row(
    header_row: list[str],
    col_map: dict[int, str],
) -> list[str] | None:
    """Extract embedded data values from a merged header+data row.

    When pdfplumber merges the header label and first data value into
    a single cell (e.g. ``"MARK A"`` or ``"MARK\\nA"``), this function
    strips the known header keyword from each mapped cell and returns
    the remaining text as a synthetic data row.

    Returns None if no embedded data is detected.
    """
    # Collect all header keywords that matched for each column.
    # We need to know which keyword matched so we can strip it.
    synth: list[str] = [""] * len(header_row)
    has_embedded = False

    for col_idx, field_name in col_map.items():
        if col_idx >= len(header_row):
            continue
        cell = header_row[col_idx]

        # Try newline split first (original cells before extractor clean).
        if "\n" in cell:
            parts = cell.split("\n", 1)
            remainder = parts[1].strip()
            if remainder:
                synth[col_idx] = remainder
                has_embedded = True
            continue

        # Space-separated: find the most specific (longest) matching
        # header keyword and strip it from the cell.  The longest
        # pattern match leaves the shortest remainder — if the remainder
        # is empty the cell is purely a header label with no embedded data.
        cell_lower = _normalise(cell)
        patterns = _COLUMN_PATTERNS.get(field_name, [])
        best_remainder: str | None = None
        best_pattern_len = -1
        for pattern in patterns:
            if len(pattern) <= 3:
                # Short pattern: must be exact prefix word
                if cell_lower.startswith(pattern + " "):
                    remainder = cell[len(pattern):].strip()
                    if len(pattern) > best_pattern_len:
                        best_pattern_len = len(pattern)
                        best_remainder = remainder
                elif cell_lower == pattern:
                    # Exact match — no embedded data. Use longest pattern.
                    if len(pattern) > best_pattern_len:
                        best_pattern_len = len(pattern)
                        best_remainder = ""
            else:
                if pattern in cell_lower:
                    # Find the position after the pattern match
                    pos = cell_lower.find(pattern)
                    end = pos + len(pattern)
                    remainder = cell[end:].strip()
                    if len(pattern) > best_pattern_len:
                        best_pattern_len = len(pattern)
                        best_remainder = remainder
        if best_remainder:
            synth[col_idx] = best_remainder
            has_embedded = True

    return synth if has_embedded else None


def _is_data_row(row: list[str], code_col: int) -> bool:
    """Return True if *row* looks like a fixture data row.

    A data row must have a non-empty code cell that looks like a fixture
    identifier (short alphanumeric, e.g. "A1", "B6", "D7", "EX-1").
    """
    if code_col >= len(row):
        return False
    code = row[code_col].strip()
    if not code:
        return False
    # Reject obvious non-fixture values: very long strings or strings that
    # are clearly sub-headers/notes.
    if len(code) > 15:
        return False
    # A fixture code is typically 1-4 alphanumeric characters, optionally
    # with a dash or period.
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9.\-/]*$", code):
        return False
    # Pure-alphabetic codes longer than 3 chars are table headers
    # (e.g., "SCHEDULES", "LIGHTING", "FIXTURE"), not fixture codes.
    # Real pure-alpha fixture codes are short: A, B, EX, SL, WL.
    if code.isalpha() and len(code) > 3:
        return False
    return True


def _row_to_fixture(
    row: list[str],
    col_map: dict[int, str],
) -> FixtureRecord:
    """Convert a raw row + column mapping into a FixtureRecord."""
    fields: dict[str, str] = {}
    for col_idx, field_name in col_map.items():
        if col_idx < len(row):
            fields[field_name] = row[col_idx].strip()
        else:
            fields[field_name] = ""

    return FixtureRecord(
        code=fields.get("code", ""),
        description=fields.get("description", ""),
        fixture_style=fields.get("fixture_style", ""),
        voltage=fields.get("voltage", ""),
        mounting=fields.get("mounting", ""),
        lumens=fields.get("lumens", ""),
        cct=fields.get("cct", ""),
        dimming=fields.get("dimming", ""),
        max_va=fields.get("max_va", ""),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


_NON_LUMINAIRE_TABLE_KEYWORDS = [
    "lighting control",
    "control device",
    "override switch",
    "floorbox",
    "poke thru",
    "panel schedule",
    "panelboard",
    "branch panel",
    "breaker function",
    "breaker schedule",
    "motor schedule",
    "equipment schedule",
    "equipment connection",
    "mechanical equipment",
    "branch circuit",
    "panel totals",
    "connected load",
    "revision",
    "ceiling fan sched",
    "energy compliance",
    "circuit description",
]

# Regex patterns that indicate a panel/breaker schedule table header.
# "PANEL A", "PANEL B", "PANEL 1", "PANEL LP-1", etc.
_PANEL_HEADER_RE = re.compile(r"\bpanel\s+[a-z0-9]", re.IGNORECASE)


_LUMINAIRE_TABLE_KEYWORDS = [
    "luminaire schedule",
    "light fixture schedule",
    "lighting schedule",
    "fixture schedule",
]


def _is_luminaire_table(raw_table: list[list[str]]) -> bool:
    """Check if a table is likely a luminaire schedule (not control/panel)."""
    if not raw_table:
        return False
    # Check first 3 rows for keywords
    header_text = " ".join(
        " ".join(str(c) for c in row) for row in raw_table[:3]
    ).lower()

    # Positive match: explicitly a luminaire schedule
    for keyword in _LUMINAIRE_TABLE_KEYWORDS:
        if keyword in header_text:
            return True

    # Negative match: explicitly NOT a luminaire schedule
    for keyword in _NON_LUMINAIRE_TABLE_KEYWORDS:
        if keyword in header_text:
            return False

    # Negative match: regex-based panel header detection
    # Catches "PANEL A", "PANEL B", "PANEL LP-1", etc.
    if _PANEL_HEADER_RE.search(header_text):
        return False

    # Ambiguous: allow through (parser will try to find fixture columns)
    return True


def _looks_like_panel_schedule(fixtures: list[FixtureRecord]) -> bool:
    """Detect if parsed fixtures are actually panel schedule circuit entries.

    Panel schedules have mostly numeric codes (circuit numbers like 1, 3, 5).
    Luminaire schedules have alphanumeric codes (A1, AL1, B6, EX1).
    If ≥60% of codes are purely numeric AND there are more than 5 entries,
    the table is almost certainly a panel schedule.
    """
    if len(fixtures) <= 5:
        return False
    numeric_count = sum(
        1 for f in fixtures if f.code.strip().isdigit()
    )
    ratio = numeric_count / len(fixtures)
    return ratio >= 0.6


def parse_schedule_table(
    raw_table: list[list[str]],
    source_page: str = "",
) -> list[FixtureRecord]:
    """Parse a single raw table into FixtureRecord objects.

    Identifies the header row, maps columns to FixtureRecord fields, then
    iterates data rows below the header.

    Args:
        raw_table: Table as list-of-rows; each row is a list of cell strings.
        source_page: Sheet code or identifier for logging.

    Returns:
        List of parsed FixtureRecord objects (may be empty).
    """
    if not raw_table:
        return []

    if not _is_luminaire_table(raw_table):
        logger.debug(
            "Skipping non-luminaire table on %s",
            source_page or "unknown page",
        )
        return []

    try:
        header_idx, col_map = _find_header_row(raw_table)
    except ScheduleExtractionError:
        logger.debug(
            "No valid header row found in table on %s — skipping table",
            source_page or "unknown page",
        )
        return []

    # Determine which column index holds the fixture code.
    code_col: int | None = None
    for idx, field in col_map.items():
        if field == "code":
            code_col = idx
            break
    if code_col is None:
        return []

    logger.debug(
        "Header row %d on %s — mapped columns: %s",
        header_idx,
        source_page or "unknown",
        {v: k for k, v in col_map.items()},
    )

    fixtures: list[FixtureRecord] = []

    # Check for merged header+data cells: the header cell may contain
    # the first data value appended after the header keyword.
    # This happens when pdfplumber merges the header label and first
    # data row into one cell. After extractor normalisation, the cell
    # looks like "MARK A" (space-separated) instead of "MARK\nA".
    # Strategy: for each mapped column, try to strip the matched header
    # keyword from the cell text — any remainder is embedded data.
    header_row = raw_table[header_idx]
    synth_row = _extract_embedded_data_row(header_row, col_map)
    if synth_row and _is_data_row(synth_row, code_col):
        fixture = _row_to_fixture(synth_row, col_map)
        fixtures.append(fixture)
        logger.info(
            "Extracted fixture %s from merged header cell "
            "on %s",
            fixture.code,
            source_page or "unknown",
        )

    for row_idx in range(header_idx + 1, len(raw_table)):
        row = raw_table[row_idx]
        if not _is_data_row(row, code_col):
            continue
        fixture = _row_to_fixture(row, col_map)
        fixtures.append(fixture)

    # Post-parse validation: reject tables that look like panel schedules.
    # Panel schedules have mostly/all numeric circuit codes (1, 3, 5, 7...).
    # Luminaire schedules have alphanumeric codes (A1, AL1, B6, EX1).
    if fixtures and _looks_like_panel_schedule(fixtures):
        logger.info(
            "Rejecting %d entries from table on %s — "
            "codes look like panel circuit numbers, not fixture types",
            len(fixtures),
            source_page or "unknown",
        )
        return []

    logger.info(
        "Parsed %d fixture(s) from table on %s",
        len(fixtures),
        source_page or "unknown",
    )
    return fixtures


def parse_all_schedules(
    schedule_pages: list[PageInfo],
    pdf_pages: dict[int, Any],
) -> list[FixtureRecord]:
    """Extract and parse fixtures from all schedule pages.

    Calls the extractor and parser for each page, then deduplicates by
    fixture code (keeping the record with the most populated fields).

    Args:
        schedule_pages: Pages identified as containing luminaire schedules.
        pdf_pages: Mapping of page_number to pdfplumber page object.

    Returns:
        Deduplicated list of FixtureRecord objects.
    """
    all_fixtures: list[FixtureRecord] = []

    for page_info in schedule_pages:
        pdf_page = pdf_pages.get(page_info.page_number)
        if pdf_page is None:
            logger.warning(
                "No pdfplumber page for page_number=%d (%s), skipping",
                page_info.page_number,
                page_info.sheet_code,
            )
            continue

        try:
            tables = extract_schedule_tables(page_info, pdf_page)
        except ScheduleExtractionError:
            logger.warning(
                "Table extraction failed on %s",
                page_info.sheet_code,
                exc_info=True,
            )
            continue

        source = page_info.sheet_code or str(page_info.page_number)
        for table in tables:
            fixtures = parse_schedule_table(table, source_page=source)
            for f in fixtures:
                f.schedule_page = source
            all_fixtures.extend(fixtures)

    # Deduplicate by fixture code, keeping the most complete record.
    deduped = _deduplicate_fixtures(all_fixtures)

    logger.info(
        "Total unique fixtures parsed from %d schedule page(s): %d",
        len(schedule_pages),
        len(deduped),
    )
    return deduped


def _field_completeness(fixture: FixtureRecord) -> int:
    """Count how many optional spec fields are non-empty."""
    count = 0
    for field in (
        "description",
        "fixture_style",
        "voltage",
        "mounting",
        "lumens",
        "cct",
        "dimming",
        "max_va",
    ):
        if getattr(fixture, field, ""):
            count += 1
    return count


def _deduplicate_fixtures(
    fixtures: list[FixtureRecord],
) -> list[FixtureRecord]:
    """Deduplicate fixtures by code, keeping the most complete record."""
    by_code: dict[str, FixtureRecord] = {}
    for f in fixtures:
        key = f.code.strip()
        if not key:
            continue
        existing = by_code.get(key)
        if existing is None or _field_completeness(f) > _field_completeness(
            existing
        ):
            by_code[key] = f

    return list(by_code.values())
