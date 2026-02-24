"""VLM-based keynote symbol counting on lighting plan pages.

Strategy: Two-image approach — sends both a cropped KEY NOTES legend
and the cropped drawing area to the VLM so it can see the actual
symbol style used, then count those symbols on the plan.
"""

from __future__ import annotations

import base64
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

    if not config.anthropic_api_key:
        raise VisionAPIError(
            "Anthropic API key not configured for VLM keynote counting."
        )

    try:
        from anthropic import Anthropic
    except ImportError as exc:
        raise VisionAPIError(
            "anthropic package not installed."
        ) from exc

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

    legend_encoded = base64.b64encode(legend_bytes).decode()
    drawing_encoded = base64.b64encode(drawing_bytes).decode()

    prompt = _build_prompt(keynote_numbers, sheet)

    try:
        client = Anthropic(api_key=config.anthropic_api_key)
        message = client.messages.create(
            model=config.vision_model,
            max_tokens=4000,
            temperature=0,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": legend_encoded,
                            },
                        },
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": drawing_encoded,
                            },
                        },
                        {
                            "type": "text",
                            "text": prompt,
                        },
                    ],
                }
            ],
        )
    except Exception as exc:
        raise VisionAPIError(
            f"VLM keynote counting API call failed for {sheet}: {exc}"
        ) from exc

    response_text = ""
    for block in message.content:
        if hasattr(block, "text"):
            response_text += block.text

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
