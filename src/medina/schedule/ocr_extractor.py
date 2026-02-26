"""OCR-based schedule extraction for rasterized/scanned schedule pages.

Renders the page at 300 DPI, crops to the schedule area, runs pytesseract
with multiple PSM modes, then parses fixture records from the OCR text
using a line-based parser.

Rasterized schedule pages have their table content embedded as images,
so pdfplumber can extract grid lines but not cell text.  OCR reads the
fixture codes more accurately than VLM on these pages.

This is the preferred fallback before VLM for schedule extraction.
"""
from __future__ import annotations

import io
import logging
import re
from typing import Any

from medina.models import FixtureRecord, PageInfo

logger = logging.getLogger(__name__)

# ── Fixture-code pattern ────────────────────────────────────────────
# Codes appear at the start of a line, optionally preceded by artifacts
# like [, |, _, etc.  Examples: "A1", "c2", "BB", "G3.", "vis", "$1"
_CODE_RE = re.compile(
    r'^[\[\]|_\- ]*'           # optional leading OCR artifacts
    r'([A-Za-z$]{1,3}\d{0,2})'  # 1-3 letters (or $) + optional digits
    r'(?:[\.\s_|]|$)'          # must be followed by separator or end-of-line
)
# Stricter pattern: code must be followed by a space and then description text
# (not a digit, which would indicate "N14" = OCR merging "N1" + "4").
_CODE_STRICT_RE = re.compile(
    r'^[\[\]|_\- ]*'
    r'([A-Za-z$]{1,3}\d{0,1})'  # 1-3 letters + at most 1 digit
    r'(?:[\.\s_|]+(?![0-9])|$)' # separator (not followed by digit) or end-of-line
)

# Pattern for PSM 6 table-row mode: code at start of line followed by
# a long description (e.g., "A 2X4 SPECIFICATION GRADE LENSED TROFFER...")
_TABLE_ROW_RE = re.compile(
    r"^['\"\u2018\u2019\u201c\u201d\[\]|_\- ]*"  # leading artifacts (incl. smart quotes)
    r"([A-Za-z$]{1,3}\d{0,2})"      # fixture code
    r"\s+"                           # whitespace separator
    r"(\d['\"\u00b0]?[Xx ].+|.{20,})"  # description: dimension (incl. °) OR long text
)

# Known OCR misreads for fixture codes.
_CODE_CORRECTIONS: dict[str, str] = {
    "$1": "S1",
    "VIS": "V",    # "vis" is V fixture with trailing OCR noise
    "BI": "B1",    # lowercase i misread as I
    "CI": "C1",
    "Al": "A1",    # lowercase l misread as 1... wait, Al is A1
}

# Words that are NOT fixture codes (header/description words).
_NOT_CODES = frozenset({
    "TYPE", "TPE",   # "TPE" is common OCR misread of "TYPE"
    "MARK", "DESCRIPTION", "VOLTAGE", "MOUNTING", "LUMENS",
    "CCT", "DIMMING", "WATTAGE", "VA", "LAMP", "LAMPS", "CATALOG",
    "QTY", "NOTES", "MANUFACTURER", "SCHEDULE", "SCHEDULES",
    "LUMINAIRE", "FIXTURE", "LIGHTING", "ELECTRICAL", "LIGHT",
    "LED", "PROVIDE", "GENERAL", "KEYED", "CONTRACTOR", "ENGINEER",
    "ARCHITECT", "ONLY", "THE", "AND", "FOR", "ALL", "TO",
})

# Min fraction of page width to start the schedule crop (left boundary).
_SCHEDULE_LEFT_FRAC = 0.50
# Max fraction of page width for the schedule crop (right boundary,
# excludes title block area).
_SCHEDULE_RIGHT_FRAC = 0.78
# Vertical crop: skip top border and bottom title block.
_SCHEDULE_TOP_FRAC = 0.03
_SCHEDULE_BOT_FRAC = 0.90


def extract_schedule_ocr(
    page_info: PageInfo,
    image_bytes: bytes,
) -> list[FixtureRecord]:
    """Extract fixture schedule from a page image using OCR.

    Tries two OCR strategies:
    1. PSM 3 (auto segmentation) with block parser — best for rasterized
       schedules where code lines are separate from description lines.
    2. PSM 6 (uniform text block) with table-row parser — best for
       standard table layouts where code + description are on one row.

    For each strategy, multiple crop regions are tried to locate the
    schedule table regardless of its position on the page.

    Args:
        page_info: Page metadata.
        image_bytes: PNG image bytes of the rendered page.

    Returns:
        List of FixtureRecord objects extracted via OCR.
    """
    try:
        import pytesseract
        from PIL import Image
    except ImportError as exc:
        logger.warning("pytesseract or Pillow not installed: %s", exc)
        return []

    sheet = page_info.sheet_code or f"page_{page_info.page_number}"
    logger.info("OCR schedule extraction on %s", sheet)

    img = Image.open(io.BytesIO(image_bytes))
    w, h = img.size
    logger.info("OCR image size: %dx%d", w, h)

    # Crop strategies: (name, left_frac, right_frac, top_frac, bot_frac)
    crop_strategies = [
        ("right-center", _SCHEDULE_LEFT_FRAC, _SCHEDULE_RIGHT_FRAC,
         _SCHEDULE_TOP_FRAC, _SCHEDULE_BOT_FRAC),
        ("left-center", 0.02, 0.55, _SCHEDULE_TOP_FRAC, _SCHEDULE_BOT_FRAC),
        ("schedule-table", 0.02, 0.55, 0.05, 0.55),
        ("full-page", 0.02, 0.85, _SCHEDULE_TOP_FRAC, _SCHEDULE_BOT_FRAC),
    ]

    # PSM modes to try.  PSM 3 (auto segmentation) first — works well for
    # rasterized schedules with image-embedded columns (Johanna Fire: 28
    # fixtures).  PSM 6 (table-row) second — works for standard tables
    # where code + description are on the same line (Dental Hygiene).
    ocr_modes: list[tuple[str, str, Any]] = [
        ("psm3", "--psm 3", _parse_fixture_blocks),
        ("psm6", "--psm 6", _parse_table_rows),
    ]

    best_fixtures: list[FixtureRecord] = []
    best_label = ""

    for mode_name, psm_config, parser_fn in ocr_modes:
        mode_best: list[FixtureRecord] = []
        mode_label = ""

        for crop_name, left_frac, right_frac, top_frac, bot_frac in crop_strategies:
            left = int(w * left_frac)
            right = int(w * right_frac)
            top = int(h * top_frac)
            bot = int(h * bot_frac)
            schedule_img = img.crop((left, top, right, bot))
            label = f"{mode_name}/{crop_name}"
            logger.info(
                "OCR [%s]: (%d,%d)-(%d,%d) = %dx%d",
                label, left, top, right, bot,
                schedule_img.width, schedule_img.height,
            )

            try:
                text = pytesseract.image_to_string(
                    schedule_img, config=psm_config,
                )
            except Exception as exc:
                logger.warning("OCR failed on %s [%s]: %s", sheet, label, exc)
                continue

            lines = [l.rstrip() for l in text.split("\n")]
            logger.info(
                "OCR [%s] produced %d lines on %s",
                label, len(lines), sheet,
            )

            fixtures = parser_fn(lines, sheet)
            logger.info(
                "OCR [%s] found %d fixtures on %s",
                label, len(fixtures), sheet,
            )

            if len(fixtures) > len(mode_best):
                mode_best = fixtures
                mode_label = label

            # Early exit within this mode for solid results.
            if len(mode_best) >= 2:
                break

        # Update overall best from this mode.
        # Prefer PSM 6 over PSM 3 at equal counts because PSM 6 reads
        # the TYPE column inline with descriptions (better code quality),
        # while PSM 3 may pick up codes from MODEL/CATALOG columns.
        if len(mode_best) > len(best_fixtures) or (
            len(mode_best) == len(best_fixtures) > 0
            and mode_name == "psm6"
        ):
            best_fixtures = mode_best
            best_label = mode_label
            logger.info(
                "OCR [%s] now best with %d fixtures",
                best_label, len(best_fixtures),
            )

        # If a mode produced a strong result (≥5 fixtures), no need
        # to try the other mode.  For small results (2-4), continue
        # trying in case the other mode finds more.
        if len(best_fixtures) >= 5:
            logger.info(
                "OCR [%s] has %d fixtures — strong result, skipping other modes",
                best_label, len(best_fixtures),
            )
            break

    if best_fixtures:
        logger.info(
            "OCR best [%s] extracted %d fixture(s) from %s",
            best_label, len(best_fixtures), sheet,
        )
    else:
        logger.info("OCR found 0 fixtures on %s", sheet)
    return best_fixtures


def _parse_fixture_blocks(
    lines: list[str],
    sheet: str,
) -> list[FixtureRecord]:
    """Parse fixture records from OCR text lines.

    The rasterized schedule produces text where each fixture spans
    multiple lines:
      - Line(s) with description text, voltage, lamp type, qty
      - A line starting with the fixture CODE followed by more
        description/specs (lumens, dimming, mounting details)
      - More continuation lines

    The code line is identified by a short alphanumeric code at the
    start of the line.
    """
    fixtures: list[FixtureRecord] = []
    seen_codes: set[str] = set()

    # First pass: find all code lines and their line indices.
    # Stop at GENERAL NOTES / KEYED NOTES — anything after is not fixtures.
    code_lines: list[tuple[int, str]] = []  # (line_idx, code)
    for i, line in enumerate(lines):
        if _is_notes_header(line):
            break
        code = _extract_code(line)
        if code and code not in _NOT_CODES:
            # Filter OCR junk: if the code is pure-alpha and the line
            # is just the code (no meaningful text after it), skip it.
            remainder = re.sub(
                r'^[\[\]|_\- ]*[A-Za-z$]{1,3}\d{0,2}[\.\s_|]*',
                '', line,
            ).strip()
            if code.isalpha() and len(remainder) < 5:
                # Pure-alpha code on a near-empty line — likely OCR artifact.
                continue
            code_lines.append((i, code))

    if not code_lines:
        logger.warning("No fixture codes found in OCR text")
        return []

    logger.info(
        "OCR found %d fixture codes: %s",
        len(code_lines),
        [c for _, c in code_lines],
    )

    # Second pass: for each code, gather the surrounding lines as the
    # fixture block.  The block starts a few lines before the code line
    # (the description start) and ends just before the next fixture's
    # description start.
    for idx, (code_line_idx, code) in enumerate(code_lines):
        if code in seen_codes:
            continue  # Skip duplicate codes
        seen_codes.add(code)

        # Determine block boundaries.
        # Look backwards from code line for the start of this fixture's
        # description (first non-empty line after previous code's block).
        if idx == 0:
            # First fixture: start from after the header lines.
            block_start = _find_first_data_line(lines, code_line_idx)
        else:
            prev_code_line_idx = code_lines[idx - 1][0]
            block_start = prev_code_line_idx + 1
            # Skip empty lines after previous code.
            while block_start < code_line_idx and not lines[block_start].strip():
                block_start += 1

        # Block ends at the start of the next fixture's description,
        # which is a few lines before the next code line.
        if idx + 1 < len(code_lines):
            next_code_line_idx = code_lines[idx + 1][0]
            # The next fixture's description starts some lines before
            # its code line.  Find the boundary.
            block_end = next_code_line_idx
            # Look backwards from next code for the first description line.
            search_start = code_line_idx + 1
            for j in range(search_start, next_code_line_idx):
                line = lines[j].strip()
                if not line:
                    continue
                # If this line looks like a new fixture description start
                # (contains LED, downlight, strip, exit, etc. keywords at start)
                if _looks_like_description_start(line):
                    block_end = j
                    break
        else:
            # Last fixture: include until general notes or end.
            block_end = len(lines)
            for j in range(code_line_idx + 1, len(lines)):
                if _is_notes_header(lines[j]):
                    block_end = j
                    break

        # Gather all text in this block.
        block_lines = [l.strip() for l in lines[block_start:block_end] if l.strip()]
        fixture = _build_fixture_from_block(code, block_lines, sheet)
        if fixture:
            fixtures.append(fixture)

    return fixtures


def _parse_table_rows(
    lines: list[str],
    sheet: str,
) -> list[FixtureRecord]:
    """Parse fixture records from PSM 6 table-row OCR output.

    PSM 6 reads table rows as single lines where the fixture code appears
    at the start followed by the description and other cell text:
        'A 2X4 SPECIFICATION GRADE LENSED TROFFER...'
        AE 2'X4' SPECIFICATION GRADE LENSED TROFFER...

    This works well for standard schedule tables where each fixture starts
    a new row with its code in the leftmost column.
    """
    fixtures: list[FixtureRecord] = []
    seen_codes: set[str] = set()

    # Collect fixture rows: lines starting with code + description.
    fixture_rows: list[tuple[str, list[str]]] = []  # (code, block_lines)
    current_code: str | None = None
    current_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if _is_notes_header(stripped):
            break

        # Try table-row pattern: code followed by long description text.
        m = _TABLE_ROW_RE.match(stripped)
        if m:
            raw_code = m.group(1).upper()
            if raw_code in _CODE_CORRECTIONS:
                raw_code = _CODE_CORRECTIONS[raw_code]
            if raw_code in _NOT_CODES or raw_code.isdigit():
                # Not a fixture code (header word or bare number).
                if current_code:
                    current_lines.append(stripped)
                continue

            # Save previous fixture.
            if current_code and current_code not in seen_codes:
                seen_codes.add(current_code)
                fixture_rows.append((current_code, current_lines))

            current_code = raw_code
            current_lines = [stripped]
        elif current_code:
            # Continuation line for current fixture.
            current_lines.append(stripped)

    # Save last fixture.
    if current_code and current_code not in seen_codes:
        seen_codes.add(current_code)
        fixture_rows.append((current_code, current_lines))

    if not fixture_rows:
        return []

    logger.info(
        "OCR table-row parser found %d fixture codes: %s",
        len(fixture_rows),
        [code for code, _ in fixture_rows],
    )

    for code, block_lines in fixture_rows:
        fixture = _build_fixture_from_table_row(code, block_lines, sheet)
        if fixture:
            fixtures.append(fixture)

    return fixtures


def _build_fixture_from_table_row(
    code: str,
    block_lines: list[str],
    sheet: str,
) -> FixtureRecord | None:
    """Build a FixtureRecord from PSM 6 table-row lines."""
    if not block_lines:
        return None

    # Join all text for field extraction.
    full_text = " ".join(block_lines)
    full_text = re.sub(r'[\[\]|_]', '', full_text)
    full_text = re.sub(r'\s+', ' ', full_text).strip()

    # Description: strip leading code + artifacts from first line.
    first_line = block_lines[0]
    desc = re.sub(
        r"^['\"\u2018\u2019\u201c\u201d\[\]|_\- ]*[A-Za-z$]{1,3}\d{0,2}\s+",
        '', first_line,
    ).strip()
    # Add continuation lines until a non-description line.
    for line in block_lines[1:]:
        cleaned = line.strip()
        if not cleaned:
            break
        # Stop if line looks like field data (voltage, mounting, etc.)
        upper = cleaned.upper()
        if any(upper.startswith(kw) for kw in (
            "RECESSED", "SURFACE", "WALL", "CEILING", "PENDANT",
            "GRID", "CHAIN", "GROUND",
        )):
            break
        desc += " " + cleaned
    desc = re.sub(r'\s+', ' ', desc).strip()

    # Reuse the same field extraction from _build_fixture_from_block.
    voltage = ""
    v_match = re.search(r'\b(120/277|277|120|MVOLT|208|240)\b', full_text)
    if v_match:
        voltage = v_match.group(1)

    cct = ""
    cct_match = re.search(r'\b(\d{4}K)\b', full_text)
    if cct_match:
        cct = cct_match.group(1)

    lumens = ""
    lum_match = re.search(
        r'(\d[\d,]*)\s*NOMINAL\s*(?:DELIVERED\s*)?LUMENS',
        full_text, re.IGNORECASE,
    )
    if lum_match:
        lumens = lum_match.group(1) + " NOMINAL LUMENS"
    else:
        lum_match2 = re.search(
            r'(\d[\d,]*)\s*LUMENS?\s*(?:PER\s*FOOT)?',
            full_text, re.IGNORECASE,
        )
        if lum_match2:
            lumens = lum_match2.group(0).strip()

    dimming = ""
    dim_match = re.search(
        r'(0-10V\s*DIMMING(?:\s*(?:DRIVER|TO\s*\d+%))?|ELV\s*DIMMING|NON-DIMMING)',
        full_text, re.IGNORECASE,
    )
    if dim_match:
        dimming = dim_match.group(1).strip()

    mounting = ""
    mount_patterns = [
        r'(GRID\s*MOUNTED)', r'(SURFACE\s*MOUNTED?)', r'(WALL\s*MOUNT(?:ED)?)',
        r'(CEILING\s*MOUNTED?)', r'(RECESSED(?:\s*IN\s*GRID\s*CEILING)?)',
        r'(PENDANT)', r'(CHAIN\s*MOUNT(?:ING)?)', r'(GROUND\s*MOUNTED?)',
    ]
    for mp in mount_patterns:
        mm = re.search(mp, full_text, re.IGNORECASE)
        if mm:
            mounting = mm.group(1).upper()
            break

    max_va = ""
    va_match = re.search(r'(\d+)\s*(?:VA|W)\b', full_text, re.IGNORECASE)
    if va_match:
        max_va = va_match.group(0).strip()

    return FixtureRecord(
        code=code,
        description=desc,
        fixture_style="",
        voltage=voltage,
        mounting=mounting,
        lumens=lumens,
        cct=cct,
        dimming=dimming,
        max_va=max_va,
        schedule_page=sheet,
    )


def _find_first_data_line(lines: list[str], first_code_idx: int) -> int:
    """Find the first data line (after headers, before first code)."""
    # Walk backwards from first code line to find description start.
    start = 0
    for i in range(first_code_idx - 1, -1, -1):
        line = lines[i].strip().upper()
        if not line:
            start = i + 1
            break
        # Stop at header keywords.
        if any(kw in line for kw in ("DESCRIPTION", "VOLTAGE", "TYPE", "SCHEDULE", "QTY")):
            start = i + 1
            break
    return start


def _extract_code(line: str) -> str | None:
    """Try to extract a fixture code from the start of a line."""
    stripped = line.strip()
    if not stripped:
        return None

    # Try strict pattern first (avoids merged codes like "N14").
    m = _CODE_STRICT_RE.match(stripped)
    if not m:
        # Fallback to looser pattern.
        m = _CODE_RE.match(stripped)
    if not m:
        return None

    raw_code = m.group(1).upper()

    # Apply known OCR corrections.
    if raw_code in _CODE_CORRECTIONS:
        raw_code = _CODE_CORRECTIONS[raw_code]

    # Fix OCR-merged codes: if code has 2+ trailing digits (e.g., "N14"),
    # it's likely a code merged with next-line text.  Truncate to 1 digit.
    digit_match = re.search(r'(\d{2,})$', raw_code)
    if digit_match and len(raw_code) > 2:
        raw_code = raw_code[:-(len(digit_match.group(1)) - 1)]

    # Single digit = not a fixture code (it's a keynote number or qty).
    if raw_code.isdigit():
        return None

    # Pure numeric with letter prefix is OK (A1, B6, etc.)
    # Pure alpha 1-3 chars is OK (AA, BB, V, etc.)
    # But single letters that are common words: skip.
    if len(raw_code) == 1 and raw_code in "AIOX":
        return None

    return raw_code


def _looks_like_description_start(line: str) -> bool:
    """Check if a line looks like the start of a new fixture description."""
    upper = line.upper()
    starters = [
        "LED ", "2X", "4'", "6\"", "8'", "20\"",
        "EDGE LIT", "BACK-LIT", "CUTOFF", "FLAGPOLE",
        "SIGN LIGHT", "SURFACE MOUNT",
    ]
    return any(upper.startswith(s) or upper.lstrip("[|I ").startswith(s) for s in starters)


def _is_notes_header(line: str) -> bool:
    """Check if a line is a notes/keyed-notes header."""
    upper = line.strip().upper()
    return upper.startswith("GENERAL NOTES") or upper.startswith("KEYED NOTES") or upper.startswith("KEYED SHEET NOTES")


def _build_fixture_from_block(
    code: str,
    block_lines: list[str],
    sheet: str,
) -> FixtureRecord | None:
    """Build a FixtureRecord from a block of OCR text lines."""
    if not block_lines:
        return None

    # Join all text for field extraction.
    full_text = " ".join(block_lines)
    # Clean up common OCR artifacts.
    full_text = re.sub(r'[\[\]|_]', '', full_text)
    full_text = re.sub(r'\s+', ' ', full_text).strip()

    # Extract the first line(s) as description (before the code line).
    desc_parts = []
    for line in block_lines:
        cleaned = re.sub(r'^[\[\]|_ ]+', '', line).strip()
        # Stop at the code line.
        line_code = _extract_code(line)
        if line_code and line_code == code:
            # Include the rest of this line after the code.
            after_code = re.sub(
                r'^[\[\]|_\- ]*[A-Za-z$]{1,3}\d{0,2}[\.\s_|]+',
                '', line,
            ).strip()
            if after_code:
                desc_parts.append(after_code)
            break
        desc_parts.append(cleaned)

    description = " ".join(desc_parts).strip()
    # Clean up description.
    description = re.sub(r'^[\[\]|_ ]+', '', description)
    description = re.sub(r'\s+', ' ', description).strip()

    # Extract voltage.
    voltage = ""
    v_match = re.search(r'\b(120/277|277|120|MVOLT|208|240)\b', full_text)
    if v_match:
        voltage = v_match.group(1)

    # Extract CCT.
    cct = ""
    cct_match = re.search(r'\b(\d{4}K)\b', full_text)
    if cct_match:
        cct = cct_match.group(1)

    # Extract lumens.
    lumens = ""
    lum_match = re.search(
        r'(\d[\d,]*)\s*NOMINAL\s*(?:DELIVERED\s*)?LUMENS',
        full_text, re.IGNORECASE,
    )
    if lum_match:
        lumens = lum_match.group(1) + " NOMINAL LUMENS"
    else:
        lum_match2 = re.search(
            r'(\d[\d,]*)\s*LUMENS?\s*(?:PER\s*FOOT)?',
            full_text, re.IGNORECASE,
        )
        if lum_match2:
            lumens = lum_match2.group(0).strip()

    # Extract dimming.
    dimming = ""
    dim_match = re.search(
        r'(0-10V\s*DIMMING(?:\s*(?:DRIVER|TO\s*\d+%))?|ELV\s*DIMMING|NON-DIMMING)',
        full_text, re.IGNORECASE,
    )
    if dim_match:
        dimming = dim_match.group(1).strip()

    # Extract mounting.
    mounting = ""
    mount_patterns = [
        r'(GRID\s*MOUNTED)', r'(SURFACE\s*MOUNTED?)', r'(WALL\s*MOUNT(?:ED)?)',
        r'(CEILING\s*MOUNTED?)', r'(RECESSED)', r'(PENDANT)',
        r'(CHAIN\s*MOUNT(?:ING)?)', r'(GROUND\s*MOUNTED?)',
    ]
    for mp in mount_patterns:
        mm = re.search(mp, full_text, re.IGNORECASE)
        if mm:
            mounting = mm.group(1).upper()
            break

    # Extract VA/wattage — look for numbers near "VA" or "W".
    max_va = ""
    va_match = re.search(r'(\d+)\s*(?:VA|W)\b', full_text, re.IGNORECASE)
    if va_match:
        max_va = va_match.group(0).strip()

    return FixtureRecord(
        code=code,
        description=description,
        fixture_style="",
        voltage=voltage,
        mounting=mounting,
        lumens=lumens,
        cct=cct,
        dimming=dimming,
        max_va=max_va,
        schedule_page=sheet,
    )
