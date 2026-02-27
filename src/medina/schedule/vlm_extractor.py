"""VLM-based schedule extraction for image-based/scanned schedule pages."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from medina.config import MedinaConfig, get_config
from medina.exceptions import ScheduleExtractionError, VisionAPIError
from medina.models import FixtureRecord, PageInfo

logger = logging.getLogger(__name__)

_SCHEDULE_EXTRACTION_PROMPT = """\
You are analyzing an electrical construction drawing page that contains a \
LIGHT FIXTURE SCHEDULE table (also called a Luminaire Schedule, Ceiling Fan \
Schedule, or Fan Schedule).

Your task is to extract EVERY fixture/luminaire/fan row from the schedule table \
into a structured JSON format.

For EACH fixture row, extract these fields:
- "code": The fixture type code/identifier (e.g., "AL1", "AL1E", "WL1", "EX1", "D7")
- "description": The full text description of the fixture
- "fixture_style": The fixture style or catalog description (if a separate column exists)
- "voltage": Operating voltage (e.g., "120/277", "MVOLT", "120V")
- "mounting": Mounting type (e.g., "YOKE", "WALL", "PENDANT", "RECESSED", "LAY-IN GRID")
- "lumens": Light output specification (e.g., "18000 lm", "5000 LUM MIN", "LED 5000 LUM")
- "cct": Correlated color temperature (e.g., "4000K", "3500K")
- "dimming": Dimming capability (e.g., "DIMMING 0-10V", "NON-DIMMING", "0-10V DIMMING")
- "max_va": Maximum volt-amperes or wattage (e.g., "50 VA", "119W-LED", "48W")

CRITICAL — Read the "code" / "TYPE" column very carefully:
- The code is the SHORT identifier in the TYPE or FIXTURE TYPE column.
- Codes can be very short (single letter like "A", "B", "C", "D") or longer \
("AL1", "WL2", "EX1", "EM", "ELM2"). Read EXACTLY what is in the TYPE cell.
- Do NOT confuse the fixture code with catalog numbers, model numbers, or \
part numbers in OTHER columns. The code is ONLY from the TYPE column.
- Common short codes: A, B, C, D, E, F (single letters are valid fixture types).
- Common longer codes: AL1, WL2, EX1, EM, D1, F1, BB, FF, X2.
- Codes ending in "E" (like "AL1E", "AL3E") indicate emergency battery versions.
- Read each code character by character. Do NOT add extra characters from \
other columns (like catalog numbers).

IMPORTANT:
- Extract ALL fixture rows from the table, do not skip any.
- If a column doesn't exist in the table, use an empty string "".
- If a value is embedded in the description (like CCT "4000K" or dimming info), \
extract it into the appropriate field AND keep it in the description.
- The "code" field is the short alphanumeric identifier (TYPE column), not a \
long description.
- Ignore any PANELBOARD schedules, PANEL schedules, or non-lighting tables.
- Extract from LIGHT FIXTURE / LUMINAIRE schedules AND CEILING FAN schedules.

Return ONLY a JSON array of objects, no other text. Example:
[
  {
    "code": "A",
    "description": "2'x2' FLAT PANEL, RECESSED, LED",
    "fixture_style": "FLAT PANEL LED",
    "voltage": "120/277",
    "mounting": "RECESSED",
    "lumens": "3500 LUM",
    "cct": "4000K",
    "dimming": "",
    "max_va": "35W"
  },
  {
    "code": "EM",
    "description": "EMERGENCY EGRESS UNIT WITH BATTERY",
    "fixture_style": "EMERGENCY BATTERY UNIT",
    "voltage": "120/277",
    "mounting": "WALL",
    "lumens": "",
    "cct": "",
    "dimming": "",
    "max_va": "2W"
  }
]
"""


def _parse_vlm_response(response_text: str) -> list[dict[str, str]]:
    """Parse the JSON fixture list from the VLM response."""
    # Try to extract JSON from code fences first.
    fence_match = re.search(
        r"```(?:json)?\s*(\[.*?\])\s*```", response_text, re.DOTALL
    )
    if fence_match:
        json_str = fence_match.group(1)
    else:
        # Try to find a bare JSON array.
        bracket_match = re.search(r"\[[\s\S]*\]", response_text)
        if bracket_match:
            json_str = bracket_match.group(0)
        else:
            logger.warning(
                "Could not find JSON array in VLM schedule response: %s",
                response_text[:300],
            )
            return []

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as exc:
        logger.warning("Failed to parse VLM schedule JSON: %s", exc)
        return []

    if not isinstance(data, list):
        logger.warning(
            "VLM schedule response is not a list: %s", type(data)
        )
        return []

    return data


def _dict_to_fixture(raw: dict[str, Any]) -> FixtureRecord | None:
    """Convert a raw dict from VLM response to a FixtureRecord."""
    code = str(raw.get("code", "")).strip()
    if not code:
        return None

    # Parse wattage into max_va if max_va is empty
    max_va = str(raw.get("max_va", "")).strip()
    if not max_va:
        # Check if wattage field exists (some VLM responses use it)
        wattage = str(raw.get("wattage", "")).strip()
        if wattage:
            max_va = wattage

    # Extract CCT from description if not provided separately
    description = str(raw.get("description", "")).strip()
    cct = str(raw.get("cct", "")).strip()
    if not cct and description:
        cct_match = re.search(r"\b(\d{3,4})\s*K\b", description)
        if cct_match:
            cct = f"{cct_match.group(1)}K"

    # Extract dimming from description if not provided
    dimming = str(raw.get("dimming", "")).strip()
    if not dimming and description:
        dim_match = re.search(
            r"(0-10V\s*DIMMING|DIMMING\s*0-10V|NON-DIMMING)",
            description,
            re.IGNORECASE,
        )
        if dim_match:
            dimming = dim_match.group(1).strip()

    return FixtureRecord(
        code=code.strip(),
        description=description,
        fixture_style=str(raw.get("fixture_style", "")).strip(),
        voltage=str(raw.get("voltage", "")).strip(),
        mounting=str(raw.get("mounting", "")).strip(),
        lumens=str(raw.get("lumens", "")).strip(),
        cct=cct,
        dimming=dimming,
        max_va=max_va,
    )


_SCHEDULE_TYPE_CHECK_PROMPT = """\
Look at this electrical construction drawing page. What type of schedule \
table(s) does it contain?

Answer with ONLY one of these categories:
- "luminaire" — if it contains a LIGHT FIXTURE SCHEDULE, LUMINAIRE SCHEDULE, or CEILING FAN SCHEDULE
- "panel" — if it contains PANEL BOARD schedules, DISTRIBUTION BOARD schedules
- "motor" — if it contains a MOTOR SCHEDULE
- "other" — if it contains other types of schedules (mechanical, plumbing, etc.)
- "mixed" — if it contains BOTH a luminaire/fan schedule AND other schedule types

Reply with ONLY the single category word, nothing else.
"""


def check_schedule_type_vlm(
    page_info: PageInfo,
    image_bytes: bytes,
    config: MedinaConfig | None = None,
) -> str:
    """Quick VLM check to determine what type of schedule a page contains.

    Returns one of: "luminaire", "panel", "motor", "other", "mixed", "unknown".
    """
    if config is None:
        config = get_config()

    sheet = page_info.sheet_code or f"page_{page_info.page_number}"

    try:
        from medina.vlm_client import get_vlm_client
        vlm = get_vlm_client(config)
    except Exception:
        return "unknown"

    try:
        response_text = vlm.vision_query(
            images=[image_bytes],
            prompt=_SCHEDULE_TYPE_CHECK_PROMPT,
            max_tokens=20,
        )
    except Exception as exc:
        logger.warning("VLM schedule type check failed for %s: %s", sheet, exc)
        return "unknown"

    result = response_text.strip().lower().split()[0] if response_text.strip() else "unknown"
    valid = {"luminaire", "panel", "motor", "other", "mixed"}
    if result not in valid:
        result = "unknown"

    logger.info("VLM schedule type check for %s: %s", sheet, result)
    return result


def extract_schedule_vlm(
    page_info: PageInfo,
    image_bytes: bytes,
    config: MedinaConfig | None = None,
    plan_codes_hint: set[str] | None = None,
) -> list[FixtureRecord]:
    """Extract fixture schedule from a page image using Claude Vision.

    This is the fallback for pages where pdfplumber cannot extract tables
    (e.g., rasterized/scanned schedule pages).

    Args:
        page_info: Page metadata.
        image_bytes: PNG image bytes of the rendered page.
        config: Configuration with API key and model settings.
        plan_codes_hint: Optional set of fixture codes found on plan pages,
            used to guide the VLM to read codes correctly.

    Returns:
        List of FixtureRecord objects extracted from the image.

    Raises:
        VisionAPIError: If the API call fails.
    """
    if config is None:
        config = get_config()

    sheet = page_info.sheet_code or f"page_{page_info.page_number}"
    logger.info("VLM schedule extraction on %s", sheet)

    from medina.vlm_client import get_vlm_client
    vlm = get_vlm_client(config)

    # Build the prompt, optionally including plan codes as hints
    prompt = _SCHEDULE_EXTRACTION_PROMPT
    if plan_codes_hint:
        sorted_codes = sorted(plan_codes_hint)
        prompt += (
            f"\n\nHINT: The following fixture codes were found on the "
            f"lighting plan pages of this project: {', '.join(sorted_codes)}. "
            f"The codes in the schedule should match or closely correspond "
            f"to these plan codes. Use this to verify your reading of the "
            f"TYPE column."
        )

    try:
        response_text = vlm.vision_query(
            images=[image_bytes],
            prompt=prompt,
            max_tokens=8000,
        )
    except Exception as exc:
        raise VisionAPIError(
            f"VLM schedule extraction API call failed for {sheet}: {exc}"
        ) from exc

    if not response_text:
        logger.warning(
            "Empty response from VLM schedule extraction for %s", sheet
        )
        return []

    logger.debug(
        "VLM schedule response for %s: %s", sheet, response_text[:500]
    )

    raw_fixtures = _parse_vlm_response(response_text)
    fixtures: list[FixtureRecord] = []
    for raw in raw_fixtures:
        fixture = _dict_to_fixture(raw)
        if fixture:
            fixture.schedule_page = page_info.sheet_code or ""
            fixtures.append(fixture)

    # Filter out panel schedule entries that VLM may extract despite
    # instructions.  Panel circuit numbers are purely numeric with
    # non-lighting descriptions.
    if fixtures:
        from medina.schedule.parser import _looks_like_panel_schedule
        if _looks_like_panel_schedule(fixtures):
            logger.warning(
                "VLM results for %s look like panel schedule entries "
                "(mostly numeric codes) — discarding %d entries",
                sheet, len(fixtures),
            )
            fixtures = []

    logger.info(
        "VLM extracted %d fixture(s) from schedule on %s",
        len(fixtures),
        sheet,
    )
    return fixtures


def has_image_based_content(
    pdf_page: Any,
    min_image_area_ratio: float = 0.15,
) -> bool:
    """Check if a PDF page has significant image-based content.

    Returns True if the page contains large embedded images that likely
    represent rasterized table content (common in scanned drawings).

    Args:
        pdf_page: A pdfplumber page object.
        min_image_area_ratio: Minimum ratio of image area to page area
            to consider the page image-heavy.
    """
    try:
        images = pdf_page.images
    except Exception:
        return False

    if not images:
        return False

    page_area = pdf_page.width * pdf_page.height
    total_image_area = 0.0

    for img in images:
        img_width = abs(img.get("x1", 0) - img.get("x0", 0))
        img_height = abs(img.get("bottom", 0) - img.get("top", 0))
        total_image_area += img_width * img_height

    ratio = total_image_area / page_area if page_area > 0 else 0
    logger.debug(
        "Page image area ratio: %.2f (threshold: %.2f)",
        ratio,
        min_image_area_ratio,
    )
    return ratio >= min_image_area_ratio


def has_minimal_text(pdf_page: Any, min_words: int = 50) -> bool:
    """Check if a PDF page has very little extractable text.

    Pages with rasterized content will have minimal text (only title block).
    """
    try:
        text = pdf_page.extract_text() or ""
    except Exception:
        return True

    word_count = len(text.split())
    logger.debug("Page text word count: %d (threshold: %d)", word_count, min_words)
    return word_count < min_words


def extract_plan_fixture_codes(pdf_pages: dict[int, Any]) -> set[str]:
    """Extract fixture-like codes from plan page text.

    Scans all provided plan pages for alphanumeric codes that look like
    fixture identifiers (e.g., AL1, AL1E, WL2, EX1, EF-3).

    Args:
        pdf_pages: Mapping of page_number to pdfplumber page objects
            for the plan pages.

    Returns:
        Set of unique fixture-like codes found on plan pages.
    """
    codes: set[str] = set()
    # Match patterns like AL1, AL1E, WL2, EX1, EF3, B1, D7 (and lowercase)
    code_pattern = re.compile(r'\b([A-Za-z]{1,3}\d+[A-Za-z]?)\b')

    for page_num, pdf_page in pdf_pages.items():
        try:
            text = pdf_page.extract_text() or ""
        except Exception:
            continue
        matches = code_pattern.findall(text)
        for m in matches:
            # Filter out non-fixture patterns (sheet codes, dates, etc.)
            if len(m) <= 6 and not re.match(r'^(FE|SS|TR|JR|LP|CS|DP|VFD|UPS)\d', m, re.IGNORECASE):
                codes.add(m)

    return codes


def crossref_vlm_codes(
    fixtures: list[FixtureRecord],
    plan_codes: set[str],
) -> list[FixtureRecord]:
    """Cross-reference VLM-extracted fixture codes against plan page codes.

    When the VLM misreads a code (e.g., "A1" instead of "AL1"), this
    function finds a matching plan code and corrects the fixture record.

    Args:
        fixtures: VLM-extracted fixture records.
        plan_codes: Fixture codes found on plan page text.

    Returns:
        Updated fixture records with corrected codes.
    """
    if not plan_codes:
        return fixtures

    plan_codes_set = set(plan_codes)

    corrected: list[FixtureRecord] = []
    used_corrections: dict[str, str] = {}  # old_code -> new_code

    for fixture in fixtures:
        code = fixture.code

        # If the code already exists on plan pages, keep it as-is
        if code in plan_codes_set:
            corrected.append(fixture)
            continue

        # Normalize: strip hyphens that VLM may insert (e.g., "A1-6")
        clean_code = code.replace("-", "")

        # If the cleaned code exists on plan pages, use it
        if clean_code in plan_codes_set:
            logger.info(
                "VLM code correction: %s -> %s (stripped hyphens)",
                code, clean_code,
            )
            used_corrections[code] = clean_code
            fixture = fixture.model_copy(update={"code": clean_code})
            corrected.append(fixture)
            continue

        # Try to find a plan code that is a longer version of this code.
        # E.g., VLM says "A1" but plan has "AL1".
        candidates = _find_code_candidates(clean_code, plan_codes_set)

        if len(candidates) == 1:
            new_code = candidates[0]
            logger.info(
                "VLM code correction: %s -> %s (cross-ref with plan)",
                code, new_code,
            )
            used_corrections[code] = new_code
            fixture = fixture.model_copy(update={"code": new_code})
        elif len(candidates) > 1:
            logger.warning(
                "VLM code %s has multiple plan candidates: %s — "
                "keeping original",
                code, candidates,
            )

        corrected.append(fixture)

    if used_corrections:
        logger.info(
            "VLM code corrections applied: %s",
            used_corrections,
        )

    # Second pass: fix missing 'E' suffix on emergency fixtures.
    # VLM sometimes drops the trailing 'E' (e.g., reads "WL1" for "WL1E").
    # Detect this when: code doesn't end in E, code+'E' is on plan pages,
    # code+'E' isn't already in the fixture list, and description mentions
    # emergency-related terms.
    _EMERGENCY_KW = ("EMERGENCY", "BATTERY PACK", "BATTERY BACKUP")
    existing_codes = {f.code for f in corrected}
    for i, fixture in enumerate(corrected):
        code = fixture.code
        if code.endswith("E") or code.endswith("e"):
            continue
        code_e = code + "E"
        if code_e not in plan_codes_set:
            continue
        if code_e in existing_codes:
            continue  # E-variant already present in schedule
        desc_upper = fixture.description.upper()
        if any(kw in desc_upper for kw in _EMERGENCY_KW):
            logger.info(
                "VLM code correction: %s -> %s (emergency description "
                "+ plan code match)",
                code, code_e,
            )
            corrected[i] = fixture.model_copy(update={"code": code_e})
            used_corrections[code] = code_e

    return corrected


def _find_code_candidates(
    vlm_code: str,
    plan_codes: set[str],
) -> list[str]:
    """Find plan codes that could be the correct version of a VLM code.

    Matching rules:
    - The plan code must share the same digit+suffix with the VLM code
    - The plan code's letter prefix must start with the VLM code's prefix
    - E.g., VLM "A1" matches plan "AL1", VLM "A2E" matches plan "AL2E"
    - E.g., VLM "W2" matches plan "WL2", VLM "B1" matches plan "BL1"
    """
    vlm_letters = re.match(r'^([A-Z]+)', vlm_code)
    vlm_digits = re.search(r'(\d+[A-Z]*)$', vlm_code)
    if not vlm_letters or not vlm_digits:
        return []

    candidates = []
    for pc in plan_codes:
        pc_letters = re.match(r'^([A-Z]+)', pc)
        pc_digits = re.search(r'(\d+[A-Z]*)$', pc)
        if not pc_letters or not pc_digits:
            continue

        # The digit+suffix part must match exactly
        if vlm_digits.group(1) != pc_digits.group(1):
            continue

        # The plan code's letter prefix must start with
        # the VLM code's letter prefix
        if pc_letters.group(1).startswith(vlm_letters.group(1)):
            candidates.append(pc)

    return candidates
