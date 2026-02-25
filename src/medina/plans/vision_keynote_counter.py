"""VLM-based keynote symbol counting on lighting plan pages.

Strategy: Two-image approach — sends both a cropped KEY NOTES legend
and the cropped drawing area to the VLM so it can see the actual
symbol style used, then count those symbols on the plan.
"""

from __future__ import annotations

import io
import json
import logging
import re
from typing import Any

from PIL import Image

from medina.config import MedinaConfig, get_config
from medina.exceptions import VisionAPIError

from medina.models import PageInfo

logger = logging.getLogger(__name__)


def _extract_json_block(text: str) -> str | None:
    """Extract JSON object string from VLM response text.

    Tries multiple strategies:
    1. Content between ```json and ``` fences (string-based, not regex)
    2. Content between ``` and ``` fences
    3. Brace-matched extraction from raw text
    """
    # Strategy 1: ```json ... ``` fences
    if "```json" in text:
        try:
            start = text.index("```json") + 7
            end = text.index("```", start)
            candidate = text[start:end].strip()
            if candidate.startswith("{"):
                return candidate
        except ValueError:
            pass

    # Strategy 2: ``` ... ``` fences (without json tag)
    if "```" in text:
        try:
            start = text.index("```") + 3
            nl = text.find("\n", start)
            if nl != -1 and nl - start < 10:
                start = nl + 1
            end = text.index("```", start)
            candidate = text[start:end].strip()
            if candidate.startswith("{"):
                return candidate
        except ValueError:
            pass

    # Strategy 3: Find outermost { ... } using brace counting
    brace_start = text.find("{")
    if brace_start == -1:
        return None
    depth = 0
    for i in range(brace_start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[brace_start : i + 1]

    return None


def _build_prompt(
    keynote_numbers: list[str],
    sheet_code: str,
) -> str:
    """Build the vision prompt for counting keynote symbols.

    Uses a chain-of-thought approach: first identify the shape from
    the legend, then verify each candidate on the floor plan before
    counting.  This prevents false positives from bare numbers.

    The two images sent are:
    1. The KEY NOTES legend (cropped from the right side)
    2. The floor plan drawing area (cropped, excluding legend/title)
    """
    nums_list = ", ".join(keynote_numbers)
    return (
        "You are analyzing an electrical lighting plan drawing. "
        f"This is sheet {sheet_code}.\n\n"
        "IMAGE 1 (first image) shows the KEY NOTES LEGEND from the "
        "right side of the drawing.\n"
        "IMAGE 2 (second image) shows the FLOOR PLAN DRAWING area.\n\n"
        f"Keynote numbers to find: {nums_list}\n\n"
        "Follow these steps EXACTLY:\n\n"
        "STEP 1 — IDENTIFY THE KEYNOTE SHAPE:\n"
        "Look at IMAGE 1 (the legend). Each keynote number in the "
        "legend is enclosed inside a specific geometric shape — "
        "typically a CIRCLE, diamond, or hexagon. Identify which "
        "shape is used. Write it down (e.g., 'circle').\n\n"
        "STEP 2 — SCAN THE FLOOR PLAN AND VERIFY EACH CANDIDATE:\n"
        "Look at IMAGE 2. For every number you see that matches one "
        "of the keynote numbers above, check:\n"
        "  Does this number have a CLOSED [shape from Step 1] drawn "
        "around it?\n"
        "  - If YES → it is a keynote callout. Note it.\n"
        "  - If NO → it is NOT a keynote. Skip it.\n\n"
        "MOST numbers on a floor plan are NOT keynotes. The vast "
        "majority are:\n"
        "- Circuit numbers (bare digits near wiring — NO shape)\n"
        "- Home run numbers (bare digits with slash marks — NO shape)\n"
        "- Switch leg numbers (bare digits — NO shape)\n"
        "- Panel identifiers (bare digits near panels — NO shape)\n"
        "- Fixture labels (letter+number like AL1, EX1 — NO shape)\n"
        "ALL of the above are bare numbers WITHOUT a geometric shape "
        "enclosing them. Do NOT count any of these.\n\n"
        "A REAL keynote callout ALWAYS has a clearly visible closed "
        "outline (the same shape you identified in Step 1) drawn "
        "tightly around the number. If you cannot see that outline, "
        "the number is not a keynote.\n\n"
        "STEP 3 — PRODUCE COUNTS:\n"
        "Based ONLY on the verified keynote callouts from Step 2, "
        "produce a JSON object with the count for each keynote.\n\n"
        "Respond with your Step 1 finding, then your Step 2 list, "
        "then the final JSON on its own line.\n"
        'Final JSON format: {"5": 1, "6": 1, "7": 0}\n'
    )


def _parse_response(
    response_text: str,
    keynote_numbers: list[str],
) -> dict[str, int]:
    """Parse the JSON keynote counts from the VLM response."""
    json_str = _extract_json_block(response_text)
    if json_str is None:
        logger.warning(
            "Could not find JSON in keynote VLM response: %s",
            response_text[:200],
        )
        return {n: 0 for n in keynote_numbers}

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as exc:
        logger.warning("Failed to parse keynote VLM JSON: %s", exc)
        return {n: 0 for n in keynote_numbers}

    if not isinstance(data, dict):
        return {n: 0 for n in keynote_numbers}

    counts: dict[str, int] = {}
    for num in keynote_numbers:
        raw = data.get(
            num,
            data.get(int(num) if num.isdigit() else num, 0),
        )
        try:
            counts[num] = int(raw)
        except (ValueError, TypeError):
            counts[num] = 0

    return counts


def _crop_legend_area(image_bytes: bytes) -> bytes:
    """Crop the KEY NOTES legend area from the right side of the page.

    The keynotes legend is typically in the right ~30% of the page,
    in the upper ~80% (above the title block).
    """
    img = Image.open(io.BytesIO(image_bytes))
    w, h = img.size

    crop_box = (int(w * 0.70), 0, w, int(h * 0.80))
    cropped = img.crop(crop_box)

    buf = io.BytesIO()
    cropped.save(buf, format="PNG")
    return buf.getvalue()


def _crop_drawing_area(image_bytes: bytes) -> bytes:
    """Crop the floor plan drawing area.

    Returns the left ~72% and top ~85% to focus on the floor plan
    where keynote symbols are placed, excluding the legend and title.
    """
    img = Image.open(io.BytesIO(image_bytes))
    w, h = img.size

    crop_box = (0, 0, int(w * 0.72), int(h * 0.85))
    cropped = img.crop(crop_box)

    buf = io.BytesIO()
    cropped.save(buf, format="PNG")
    return buf.getvalue()


def _build_extract_and_count_prompt(sheet_code: str) -> str:
    """Build prompt for full VLM keynote extraction (text + counts).

    Used as fallback when text-based extraction fails (garbled text,
    non-standard format, scanned pages).  Asks VLM to both READ the
    keynote definitions AND COUNT the symbols on the floor plan.
    """
    return (
        "RESPOND WITH ONLY A JSON OBJECT. NO EXPLANATIONS. NO THINKING. "
        "JUST THE JSON.\n\n"
        f"Analyze this electrical plan (sheet {sheet_code}). "
        "Find the KEY NOTES / KEYNOTES / KEYED NOTES section (right side "
        "of drawing). Extract each numbered entry and count how many times "
        "each keynote number appears inside a geometric shape (diamond, "
        "hexagon, circle) on the floor plan. Do NOT count bare numbers "
        "(circuit numbers, panel IDs, room labels).\n\n"
        "JSON format:\n"
        '{"keynotes": ['
        '{"number": "1", "text": "Brief description (first sentence)", '
        '"count": 3}, '
        '{"number": "2", "text": "Brief description", "count": 1}'
        "]}\n\n"
        "Rules: Include ALL keynotes. Keep text to first sentence only "
        "(max ~80 chars). Set count=0 if not found on floor plan.\n"
    )


def _extract_json_from_response(response_text: str) -> Any:
    """Extract JSON data from VLM response, handling various formats.

    VLMs may return:
    1. ```json {"keynotes": [...]} ```  — standard wrapped JSON
    2. ```json "keynotes": [...] ```    — bare key-value without {}
    3. ```json [...] ```                — bare array
    4. Raw JSON without fences
    """
    # Strategy 1: Standard JSON block extraction
    json_str = _extract_json_block(response_text)
    if json_str is not None:
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            pass

    # Strategy 2: Code fence with bare content (no outer {})
    for fence_marker in ("```json", "```"):
        if fence_marker in response_text:
            try:
                start = response_text.index(fence_marker) + len(fence_marker)
                end = response_text.index("```", start)
                candidate = response_text[start:end].strip()
                # Try wrapping in {} if it looks like key-value pairs
                if candidate.startswith('"'):
                    wrapped = "{" + candidate + "}"
                    try:
                        return json.loads(wrapped)
                    except json.JSONDecodeError:
                        pass
                # Try as bare array
                if candidate.startswith("["):
                    try:
                        return json.loads(candidate)
                    except json.JSONDecodeError:
                        pass
            except ValueError:
                pass

    # Strategy 3: Find any [ ... ] array in the text
    bracket_start = response_text.find("[")
    if bracket_start != -1:
        depth = 0
        for i in range(bracket_start, len(response_text)):
            if response_text[i] == "[":
                depth += 1
            elif response_text[i] == "]":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(
                            response_text[bracket_start : i + 1]
                        )
                    except json.JSONDecodeError:
                        break

    # Strategy 4: Truncated response recovery
    # VLM may have been cut off by max_tokens. Try to recover
    # partial JSON by finding valid entries in the response.
    # Look for the keynotes array start and recover complete entries.
    kn_start = response_text.find('"keynotes"')
    if kn_start == -1:
        kn_start = response_text.find("'keynotes'")
    if kn_start != -1:
        arr_start = response_text.find("[", kn_start)
        if arr_start != -1:
            # Find all complete {...} objects within the truncated array
            recovered: list[dict] = []
            depth = 0
            obj_start = -1
            for i in range(arr_start + 1, len(response_text)):
                if response_text[i] == "{":
                    if depth == 0:
                        obj_start = i
                    depth += 1
                elif response_text[i] == "}":
                    depth -= 1
                    if depth == 0 and obj_start >= 0:
                        try:
                            obj = json.loads(
                                response_text[obj_start : i + 1]
                            )
                            recovered.append(obj)
                        except json.JSONDecodeError:
                            pass
                        obj_start = -1
            if recovered:
                logger.info(
                    "Recovered %d entries from truncated VLM response",
                    len(recovered),
                )
                return {"keynotes": recovered}

    return None


def _parse_extract_response(
    response_text: str,
) -> list[dict[str, Any]]:
    """Parse VLM response for full keynote extraction.

    Returns list of {"number": str, "text": str, "count": int} dicts.
    Handles various response formats from different VLM providers.
    """
    data = _extract_json_from_response(response_text)
    if data is None:
        logger.warning(
            "Could not find JSON in VLM extract response: %s",
            response_text[:300],
        )
        return []

    if isinstance(data, dict):
        entries = data.get("keynotes", [])
    elif isinstance(data, list):
        entries = data
    else:
        return []

    result: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        num = str(entry.get("number", ""))
        text = str(entry.get("text", ""))
        try:
            count = int(entry.get("count", 0))
        except (ValueError, TypeError):
            count = 0

        if num and text and len(text) >= 10:
            result.append({"number": num, "text": text, "count": count})

    return result


def extract_and_count_keynotes_vlm(
    page_info: PageInfo,
    image_bytes: bytes,
    config: MedinaConfig | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """VLM-based full keynote extraction AND counting.

    Fallback for when text-based extraction fails (garbled text,
    non-standard format, scanned/image-only pages).  Uses VLM to
    both READ the keynote definitions and COUNT the symbols.

    Args:
        page_info: Page metadata.
        image_bytes: PNG image bytes of the full rendered page.
        config: Configuration with API key and model settings.

    Returns:
        Tuple of (keynote_entries, counts) where:
        - keynote_entries = [{"number": "1", "text": "..."}, ...]
        - counts = {"1": 3, "2": 1, ...}

    Raises:
        VisionAPIError: If the API call fails.
    """
    if config is None:
        config = get_config()

    sheet = page_info.sheet_code or f"page_{page_info.page_number}"
    logger.info("VLM full keynote extraction on plan %s", sheet)

    from medina.vlm_client import get_vlm_client

    prompt = _build_extract_and_count_prompt(sheet)

    client = get_vlm_client(config)
    response_text = client.vision_query(
        [image_bytes], prompt, max_tokens=8192, temperature=0,
    )

    if not response_text:
        logger.warning("Empty VLM response for keynote extraction on %s", sheet)
        return [], {}

    logger.debug("VLM extract response for %s: %s", sheet, response_text[:500])

    entries = _parse_extract_response(response_text)

    # If primary VLM returned nothing, try fallback provider
    if not entries:
        from medina.vlm_client import get_fallback_vlm_client

        fallback = get_fallback_vlm_client(config)
        if fallback:
            logger.info(
                "VLM keynote extract primary returned nothing for %s — "
                "trying %s fallback", sheet, fallback.provider,
            )
            try:
                fb_text = fallback.vision_query(
                    [image_bytes], prompt, max_tokens=4000, temperature=0,
                )
                if fb_text:
                    entries = _parse_extract_response(fb_text)
                    if entries:
                        logger.info(
                            "VLM keynote extract fallback (%s) found %d "
                            "entries for %s",
                            fallback.provider, len(entries), sheet,
                        )
            except Exception as e:
                logger.warning(
                    "VLM keynote extract fallback failed for %s: %s", sheet, e,
                )

    if not entries:
        logger.warning("VLM found no keynote entries on %s", sheet)
        return [], {}

    # Build results
    keynote_entries = [
        {"number": e["number"], "text": e["text"]} for e in entries
    ]
    counts = {e["number"]: e["count"] for e in entries}

    logger.info(
        "VLM extracted %d keynotes from %s: %s",
        len(entries), sheet, counts,
    )
    return keynote_entries, counts


def count_keynotes_vision(
    page_info: PageInfo,
    image_bytes: bytes,
    keynote_numbers: list[str],
    config: MedinaConfig | None = None,
) -> dict[str, int]:
    """Count keynote symbols on a plan page using Claude Vision.

    Sends two images in a single call:
    1. The KEY NOTES legend (cropped from right side) — so the model
       can see what keynote symbols look like in this specific drawing.
    2. The floor plan drawing area (cropped) — where the model needs
       to count the keynote callout symbols.

    Args:
        page_info: Page metadata.
        image_bytes: PNG image bytes of the rendered plan page.
        keynote_numbers: List of keynote numbers to search for.
        config: Configuration with API key and model settings.

    Returns:
        Dict mapping keynote_number (str) to count.

    Raises:
        VisionAPIError: If the API call fails.
    """
    if config is None:
        config = get_config()

    sheet = page_info.sheet_code or f"page_{page_info.page_number}"
    logger.info("VLM keynote counting on plan %s", sheet)

    if not keynote_numbers:
        return {}

    from medina.vlm_client import get_vlm_client

    # For viewport sub-plans, the shared KEYED NOTES legend sits outside
    # the viewport bbox (e.g., at the far right of the full page).  We
    # keep the full-page image for the legend crop and use the viewport-
    # cropped image for the drawing crop.
    full_page_image = image_bytes
    viewport_image = image_bytes
    if page_info.viewport_bbox is not None:
        try:
            img = Image.open(io.BytesIO(image_bytes))
            iw, ih = img.size
            # Estimate PDF dimensions from image size (assume 200 DPI for keynotes)
            est_dpi = 200
            pdf_w = iw * 72 / est_dpi
            pdf_h = ih * 72 / est_dpi
            x0, y0, x1, y1 = page_info.viewport_bbox
            x_scale = iw / pdf_w
            y_scale = ih / pdf_h
            crop_box = (
                int(x0 * x_scale),
                int(y0 * y_scale),
                int(x1 * x_scale),
                int(y1 * y_scale),
            )
            cropped = img.crop(crop_box)
            buf = io.BytesIO()
            cropped.save(buf, format="PNG")
            viewport_image = buf.getvalue()
            logger.debug(
                "Cropped keynote VLM image to viewport %s for %s",
                page_info.viewport_bbox, sheet,
            )
        except Exception as e:
            logger.warning("Viewport crop failed for keynote VLM %s: %s", sheet, e)

    # Legend crop from full page (shared notes panel visible).
    # Drawing crop from viewport image (only this sub-plan's area).
    legend_bytes = _crop_legend_area(full_page_image)
    drawing_bytes = _crop_drawing_area(viewport_image)

    prompt = _build_prompt(keynote_numbers, sheet)

    client = get_vlm_client(config)
    response_text = client.vision_query(
        [legend_bytes, drawing_bytes], prompt, max_tokens=4000, temperature=0,
    )

    if not response_text:
        logger.warning(
            "Empty response from VLM keynote counting for %s", sheet
        )
        return {n: 0 for n in keynote_numbers}

    logger.debug(
        "VLM keynote response for %s: %s", sheet, response_text[:500]
    )
    counts = _parse_response(response_text, keynote_numbers)

    total = sum(counts.values())

    # If primary VLM returned no usable JSON, try fallback provider
    if total == 0 and _extract_json_block(response_text) is None:
        from medina.vlm_client import get_fallback_vlm_client

        fallback = get_fallback_vlm_client(config)
        if fallback:
            logger.info(
                "VLM keynote primary returned no JSON for %s — trying %s fallback",
                sheet, fallback.provider,
            )
            try:
                fb_text = fallback.vision_query(
                    [legend_bytes, drawing_bytes], prompt,
                    max_tokens=4000, temperature=0,
                )
                if fb_text:
                    fb_counts = _parse_response(fb_text, keynote_numbers)
                    fb_total = sum(fb_counts.values())
                    if fb_total > 0 or _extract_json_block(fb_text) is not None:
                        counts = fb_counts
                        total = fb_total
                        logger.info(
                            "VLM keynote fallback (%s) for %s: %d total",
                            fallback.provider, sheet, fb_total,
                        )
            except Exception as e:
                logger.warning("VLM keynote fallback failed for %s: %s", sheet, e)

    logger.info(
        "VLM plan %s: found %d total keynote symbols across %d types",
        sheet, total, sum(1 for c in counts.values() if c > 0),
    )
    return counts
