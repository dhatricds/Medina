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
        "ltr type",
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
    if not text:
        return ""
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
    # Skip cells longer than 35 chars — real header labels are short;
    # long cells are notes/description text that happen to contain
    # keywords (e.g. "GENERAL NOTES: A. CATALOG NUMBER...").
    _MAX_HEADER_CELL_LEN = 35
    for field, patterns in _COLUMN_PATTERNS.items():
        if field in used_fields:
            continue
        for pattern in patterns:
            for col_idx, cell in enumerate(normalised):
                if col_idx in mapped:
                    continue
                if len(cell) > _MAX_HEADER_CELL_LEN:
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

    # A valid header row must map at least 2 different fields (e.g. code +
    # description).  A single-column "match" is usually a false positive
    # from a title row like "LIGHT FIXTURE SCHEDULE" where "fixture"
    # substring-matches the code pattern.
    if best_idx == -1 or "code" not in best_mapping.values() or len(best_mapping) < 2:
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
    # Reject common table header values that aren't pure-alpha
    _REJECT_CODES = {"NO.", "NO", "#", "QTY", "CKT"}
    if code.upper().rstrip(".") in _REJECT_CODES or code.upper() in _REJECT_CODES:
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
    "energy compliance",
    "circuit description",
]

# Regex patterns that indicate a panel/breaker schedule table header.
# Matches "PANEL A", "PANEL B", "PANEL 1", "PANEL LP-1", etc.
# Does NOT match fixture descriptions: "FLAT PANEL", "LED PANEL",
# "PANEL RECESSED", "PANEL LED", "AT PANEL".
_PANEL_HEADER_RE = re.compile(
    r"(?<!\bflat\s)(?<!\bled\s)(?<!\bat\s)\bpanel\s+(?!led\b|recessed\b|light\b|lamp\b|troffer\b|luminaire\b)[a-z0-9]",
    re.IGNORECASE,
)


_LUMINAIRE_TABLE_KEYWORDS = [
    "luminaire schedule",
    "light fixture schedule",
    "lighting schedule",
    "fixture schedule",
    "ceiling fan schedule",
    "fan schedule",
]


def _is_luminaire_table(raw_table: list[list[str]]) -> bool:
    """Check if a table is likely a luminaire schedule (not control/panel)."""
    if not raw_table:
        return False
    # Positive keywords: check first 3 rows (title + header + possible subheader).
    pos_text = " ".join(
        " ".join(str(c) for c in row) for row in raw_table[:3]
    ).lower()

    # Positive match: explicitly a luminaire schedule
    for keyword in _LUMINAIRE_TABLE_KEYWORDS:
        if keyword in pos_text:
            return True

    # Negative keywords: check first 3 rows (title + header + subheader).
    # The _PANEL_HEADER_RE regex is smart enough to exclude fixture
    # descriptions like "FLAT PANEL RECESSED" and "AT PANEL LED".
    neg_text = " ".join(
        " ".join(str(c) for c in row) for row in raw_table[:3]
    ).lower()

    # Negative match: explicitly NOT a luminaire schedule
    for keyword in _NON_LUMINAIRE_TABLE_KEYWORDS:
        if keyword in neg_text:
            return False

    # Negative match: regex-based panel header detection
    # Catches "PANEL A", "PANEL B", "PANEL LP-1", etc.
    if _PANEL_HEADER_RE.search(neg_text):
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


def _parse_headerless_schedule(
    raw_table: list[list[str]],
    source_page: str = "",
) -> list[FixtureRecord]:
    """Parse a schedule table that has no standard column headers.

    Some small fixture schedules have a title row (e.g. "LIGHT FIXTURE
    SCHEDULE") followed by notes and data rows, but no explicit column
    headers like TYPE, DESCRIPTION, VOLTAGE, etc.  This function scans
    each row for a fixture-code-like first cell and maps the remaining
    cells to FixtureRecord fields by content heuristics.

    Returns a list of FixtureRecord objects, or an empty list.
    """
    # Guard: reject tables with garbled/reversed text (custom font encoding).
    # Concatenate all cell text and check for recognizable schedule keywords.
    # Real fixture schedules contain at least some of these words.
    all_text = " ".join(
        str(c) for row in raw_table for c in row if c
    ).lower()
    _SCHEDULE_SANITY_WORDS = {
        "led", "fixture", "luminaire", "lamp", "lumen", "watt",
        "volt", "dimm", "recessed", "surface", "pendant", "mount",
        "ceiling", "wall", "fluorescent", "light", "troffer",
        "downlight", "schedule", "description", "type",
    }
    found_words = sum(1 for w in _SCHEDULE_SANITY_WORDS if w in all_text)
    if found_words < 2:
        logger.debug(
            "Headerless fallback: table text on %s has only %d schedule "
            "keywords (need ≥2) — skipping (likely garbled text)",
            source_page or "unknown", found_words,
        )
        return []

    fixtures: list[FixtureRecord] = []

    for row in raw_table:
        if not row or not row[0]:
            continue
        cell0 = row[0].strip()
        if not cell0:
            continue

        # Extract fixture code from cell 0.
        # Handle merged "code quantity" patterns like "F1 1" → code "F1".
        code = _extract_code_from_cell(cell0)
        if not code:
            continue

        # Pure-alpha codes >3 chars are headers, not fixture codes.
        if code.isalpha() and len(code) > 3:
            continue

        # Must have at least one more non-empty cell (description etc.)
        non_empty = [c.strip() for c in row[1:] if c and c.strip()]
        if not non_empty:
            continue

        # Map remaining cells to fixture fields by content analysis.
        fields = _map_cells_by_content(row[1:])
        fixture = FixtureRecord(
            code=code,
            description=fields.get("description", ""),
            fixture_style=fields.get("fixture_style", ""),
            voltage=fields.get("voltage", ""),
            mounting=fields.get("mounting", ""),
            lumens=fields.get("lumens", ""),
            cct=fields.get("cct", ""),
            dimming=fields.get("dimming", ""),
            max_va=fields.get("max_va", ""),
        )
        fixtures.append(fixture)
        logger.info(
            "Headerless fallback: extracted fixture %s from %s",
            code, source_page or "unknown",
        )

    return fixtures


# Regex patterns for content-based cell classification.
_VOLTAGE_RE = re.compile(
    r"(?:^|\b)(?:120|277|120/277|347|480|347/600|universal|univ)(?:\b|$)",
    re.IGNORECASE,
)
_CCT_RE = re.compile(
    r"(?:\b\d{4}\s*K\b|\b(?:30|35|40|50)00\s*(?:K|LED)\b)", re.IGNORECASE,
)
_MOUNTING_RE = re.compile(
    r"\b(?:recessed|surface|pendant|wall|ceiling|lay[- ]?in|grid|stem"
    r"|chain|track|pole|bracket|flush)\b",
    re.IGNORECASE,
)
_LUMENS_RE = re.compile(
    r"\b(?:lumen|lum|lumens)\b|\b\d+\s*(?:lm|LM)\b", re.IGNORECASE,
)
_DIMMING_RE = re.compile(
    r"\b(?:dimm|0-10\s*V|DALI|ELV|triac|non[- ]?dim|lutron)\b",
    re.IGNORECASE,
)
_WATTS_RE = re.compile(
    r"\b\d+\s*(?:VA|W|watts?|watt)\b", re.IGNORECASE,
)


def _extract_code_from_cell(cell: str) -> str:
    """Extract a fixture code from a cell that may contain merged data.

    Handles patterns like:
      "F1 1"  → "F1"  (code + quantity)
      "F1"    → "F1"
      "AL1 2" → "AL1"
    """
    cell = cell.strip()
    if not cell:
        return ""
    # If the entire cell is a short alphanumeric code, use it directly.
    if re.match(r"^[A-Za-z][A-Za-z0-9.\-/]{0,9}$", cell):
        return cell
    # Try splitting on whitespace — first token might be the code.
    parts = cell.split()
    if len(parts) >= 2:
        candidate = parts[0]
        # Check if candidate looks like a fixture code and the rest is numeric
        # (quantity) or other data.
        if re.match(r"^[A-Za-z][A-Za-z0-9.\-/]{0,9}$", candidate):
            # Remaining parts should be short (quantity, note marker, etc.)
            remainder = " ".join(parts[1:])
            if len(remainder) <= 5 or remainder.isdigit():
                return candidate
    return ""


def _map_cells_by_content(cells: list[str]) -> dict[str, str]:
    """Map cells to fixture fields using content-based heuristics.

    For headerless tables, we determine what each cell contains by
    checking for voltage patterns, CCT patterns, etc.  The first long
    text cell is treated as the description.
    """
    fields: dict[str, str] = {}
    used: set[int] = set()

    clean = [(i, c.strip()) for i, c in enumerate(cells) if c and c.strip()]

    # Pass 1: identify cells by strong content patterns.
    for i, text in clean:
        if i in used:
            continue
        text_lower = text.lower()
        if _CCT_RE.search(text) and "cct" not in fields:
            fields["cct"] = text
            used.add(i)
        elif _VOLTAGE_RE.search(text) and "voltage" not in fields:
            # Make sure it's not a long description that happens to mention voltage
            if len(text) < 20:
                fields["voltage"] = text
                used.add(i)
        elif _DIMMING_RE.search(text) and "dimming" not in fields:
            fields["dimming"] = text
            used.add(i)
        elif _LUMENS_RE.search(text) and "lumens" not in fields:
            fields["lumens"] = text
            used.add(i)
        elif _MOUNTING_RE.search(text) and "mounting" not in fields:
            if len(text) < 30:
                fields["mounting"] = text
                used.add(i)
        elif _WATTS_RE.search(text) and "max_va" not in fields:
            if len(text) < 15:
                fields["max_va"] = text
                used.add(i)

    # Pass 2: the longest remaining cell is likely the description.
    remaining = [(i, text) for i, text in clean if i not in used]
    if remaining:
        # Sort by length descending — longest is description.
        remaining.sort(key=lambda x: len(x[1]), reverse=True)
        desc_i, desc_text = remaining[0]
        if len(desc_text) > 10:
            fields["description"] = desc_text
            used.add(desc_i)

    # Pass 3: if there's a catalog-number-like cell, use it as fixture_style.
    for i, text in clean:
        if i in used:
            continue
        # Catalog numbers often have dashes, slashes, and mixed case: "RMCA-4-FL/TR-..."
        if len(text) > 5 and re.search(r"[-/]", text) and not text[0].isdigit():
            fields["fixture_style"] = text
            used.add(i)
            break

    return fields


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
        # Fallback for headerless schedule tables: some small tables have
        # a title row ("LIGHT FIXTURE SCHEDULE") followed by notes and
        # data rows but no explicit column headers (TYPE, DESCRIPTION, etc.).
        # Try to extract fixture codes directly from data rows.
        fallback = _parse_headerless_schedule(raw_table, source_page)
        if fallback:
            return fallback
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
