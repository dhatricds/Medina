"""VLM-based keynote symbol counting on lighting plan pages.

Strategy: Two-image approach — sends both a cropped KEY NOTES legend
and the cropped drawing area to the VLM so it can see the actual
symbol style used, then count those symbols on the plan.

Also provides full keynote extraction (definitions + counts) for
garbled/image-based PDFs where text extraction fails entirely.
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
from medina.models import KeyNote, PageInfo

logger = logging.getLogger(__name__)


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
    # Try code fences first.
    fence_match = re.search(
        r'```(?:json)?\s*(\{[^{}]*\})\s*```', response_text, re.DOTALL
    )
    if fence_match:
        json_str = fence_match.group(1)
    else:
        brace_match = re.search(r'\{[^{}]*\}', response_text, re.DOTALL)
        if brace_match:
            json_str = brace_match.group(0)
        else:
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

    if not config.has_vlm_key:
        raise VisionAPIError(
            "No VLM API key configured for keynote counting."
        )

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

    from medina.vlm_client import get_vlm_client
    vlm = get_vlm_client(config)

    try:
        response_text = vlm.vision_query(
            images=[legend_bytes, drawing_bytes],
            prompt=prompt,
            max_tokens=4000,
            temperature=0,
        )
    except Exception as exc:
        raise VisionAPIError(
            f"VLM keynote counting API call failed for {sheet}: {exc}"
        ) from exc

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
    logger.info(
        "VLM plan %s: found %d total keynote symbols across %d types",
        sheet, total, sum(1 for c in counts.values() if c > 0),
    )
    return counts


# ── Full VLM keynote extraction (definitions + counts) ──────────────

_EXTRACT_KEYNOTES_PROMPT = """\
You are analyzing an electrical lighting plan drawing.
This is sheet {sheet_code}.

IMAGE 1 shows the KEY NOTES LEGEND area (right side of the drawing).
IMAGE 2 shows the FLOOR PLAN DRAWING area.

TASKS:
1. Read the KEY NOTES legend in IMAGE 1. Extract each keynote:
   - number (the digit inside a geometric shape like diamond/circle/hexagon)
   - text (the description next to it — first sentence only, keep it short)

2. For each keynote number found, count how many times that keynote
   symbol appears on the FLOOR PLAN in IMAGE 2. Only count numbers
   that are enclosed in the SAME geometric shape as in the legend.
   Do NOT count bare circuit numbers, switch legs, or panel IDs.

RESPOND WITH ONLY A JSON OBJECT. NO EXPLANATIONS. NO THINKING.
Format:
{{"keynotes": [{{"number": "1", "text": "first sentence of keynote text", "count": 3}}, ...]}}
"""


def _extract_json_from_response(text: str) -> dict | None:
    """Extract JSON from a VLM response, handling truncation and noise."""
    # Try code fence first
    fence_match = re.search(
        r'```(?:json)?\s*(\{[\s\S]*?\})\s*```', text,
    )
    if fence_match:
        try:
            return json.loads(fence_match.group(1))
        except json.JSONDecodeError:
            pass

    # Try bare JSON object
    brace_match = re.search(r'\{[\s\S]*\}', text)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            # Truncated response — try to recover partial keynotes array
            raw = brace_match.group(0)
            # Find all complete {...} objects inside the keynotes array
            objs = re.findall(r'\{[^{}]+\}', raw)
            recovered: list[dict] = []
            for obj_str in objs:
                try:
                    obj = json.loads(obj_str)
                    if "number" in obj:
                        recovered.append(obj)
                except json.JSONDecodeError:
                    continue
            if recovered:
                return {"keynotes": recovered}

    # Try bare key-value pairs without outer braces
    if '"number"' in text and '"text"' in text:
        objs = re.findall(r'\{[^{}]+\}', text)
        recovered = []
        for obj_str in objs:
            try:
                obj = json.loads(obj_str)
                if "number" in obj:
                    recovered.append(obj)
            except json.JSONDecodeError:
                continue
        if recovered:
            return {"keynotes": recovered}

    return None


def extract_and_count_keynotes_vlm(
    page_info: PageInfo,
    image_bytes: bytes,
    config: MedinaConfig | None = None,
) -> tuple[list[KeyNote], dict[str, int]]:
    """Extract keynote definitions AND count symbols using VLM.

    Used when text-based extraction fails entirely (garbled text,
    image-based PDFs). Returns both KeyNote objects and per-plan counts.

    Args:
        page_info: Page metadata.
        image_bytes: PNG image bytes of the rendered plan page.
        config: Configuration with API key and model settings.

    Returns:
        Tuple of (list of KeyNote objects, dict of {keynote_num: count}).
    """
    if config is None:
        config = get_config()

    sheet = page_info.sheet_code or f"pg{page_info.page_number}"
    logger.info("[KEYNOTE-VLM] Full extraction on plan %s", sheet)

    if not config.has_vlm_key:
        return [], {}

    # Crop legend and drawing areas
    legend_bytes = _crop_legend_area(image_bytes)
    drawing_bytes = _crop_drawing_area(image_bytes)

    prompt = _EXTRACT_KEYNOTES_PROMPT.format(sheet_code=sheet)

    from medina.vlm_client import get_vlm_client
    vlm = get_vlm_client(config)

    try:
        response_text = vlm.vision_query(
            images=[legend_bytes, drawing_bytes],
            prompt=prompt,
            max_tokens=8192,
            temperature=0,
        )
    except Exception as exc:
        logger.warning(
            "[KEYNOTE-VLM] Full extraction API failed for %s: %s",
            sheet, exc,
        )
        return [], {}

    if not response_text:
        logger.warning("[KEYNOTE-VLM] Empty response for %s", sheet)
        return [], {}

    logger.debug(
        "[KEYNOTE-VLM] Response for %s: %s", sheet, response_text[:500],
    )

    parsed = _extract_json_from_response(response_text)
    if not parsed or "keynotes" not in parsed:
        logger.warning(
            "[KEYNOTE-VLM] Could not parse response for %s: %s",
            sheet, response_text[:300],
        )
        return [], {}

    keynotes: list[KeyNote] = []
    counts: dict[str, int] = {}

    for entry in parsed["keynotes"]:
        if not isinstance(entry, dict):
            continue
        num = str(entry.get("number", "")).strip()
        text = str(entry.get("text", "")).strip()
        count = 0
        try:
            count = int(entry.get("count", 0))
        except (ValueError, TypeError):
            pass

        if not num:
            continue

        # Skip implausibly high keynote numbers
        try:
            if int(num) > 20:
                continue
        except ValueError:
            pass

        kn = KeyNote(
            number=num,
            text=text,
            counts_per_plan={sheet: count},
            total=count,
        )
        keynotes.append(kn)
        counts[num] = count

    logger.info(
        "[KEYNOTE-VLM] Extracted %d keynotes from %s: %s",
        len(keynotes), sheet,
        {kn.number: kn.total for kn in keynotes},
    )
    return keynotes, counts
