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

    The two images sent are:
    1. The KEY NOTES legend (cropped from the right side)
    2. The floor plan drawing area (cropped, excluding legend/title)
    """
    nums_list = ", ".join(keynote_numbers)
    return (
        "You are analyzing an electrical lighting plan drawing. "
        f"This is sheet {sheet_code}.\n\n"
        "IMAGE 1 (first image) shows the KEY NOTES LEGEND from the "
        "right side of the drawing. It lists each keynote number and "
        "its description. Look at this legend to understand what "
        "keynote callout symbols look like in this drawing.\n\n"
        "IMAGE 2 (second image) shows the FLOOR PLAN DRAWING area. "
        "This is where you need to count keynote symbols.\n\n"
        "TASK: Count how many times each of these keynote numbers "
        f"appears as a CALLOUT SYMBOL on the floor plan: {nums_list}\n\n"
        "WHAT IS A KEYNOTE CALLOUT SYMBOL:\n"
        "A keynote callout is a small marker placed on the floor plan "
        "to reference a numbered note. It is typically:\n"
        "- A number inside a small diamond (rotated square) shape\n"
        "- Or a number inside another geometric shape (hexagon, "
        "triangle, circle)\n"
        "- It is visually DISTINCT from other numbers on the drawing\n"
        "- It has a clear geometric BORDER/OUTLINE around the number\n\n"
        "WHAT IS NOT A KEYNOTE SYMBOL (do NOT count these):\n"
        "- Circuit numbers: bare numbers (no border) next to wiring "
        "lines and home runs — these are the MOST COMMON false positive\n"
        "- Fixture type labels: letter+number combinations like A1, B6\n"
        "- Dimension/measurement numbers: like 10'-0\", 4'-6\"\n"
        "- Room numbers: large numbers labeling rooms\n"
        "- Door numbers\n"
        "- Switch numbers on switch legs\n"
        "- Numbers in the title block\n"
        "- Numbers in the KEY NOTES legend itself\n\n"
        "THE KEY DIFFERENCE: Keynote symbols have a visible geometric "
        "BORDER (diamond, hexagon, etc.) around the number. Circuit "
        "numbers are just bare numbers with NO border. Look carefully "
        "for the border before counting something as a keynote.\n\n"
        "Return ONLY a JSON object with the count for each keynote. "
        "If a keynote number does not appear as a callout symbol on "
        "the plan, report 0.\n"
        'Example format: {"5": 3, "6": 2, "7": 0}\n'
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

    # Crop the legend and drawing areas
    legend_bytes = _crop_legend_area(image_bytes)
    drawing_bytes = _crop_drawing_area(image_bytes)

    legend_encoded = base64.b64encode(legend_bytes).decode()
    drawing_encoded = base64.b64encode(drawing_bytes).decode()

    prompt = _build_prompt(keynote_numbers, sheet)

    try:
        client = Anthropic(api_key=config.anthropic_api_key)
        message = client.messages.create(
            model=config.vision_model,
            max_tokens=1500,
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
