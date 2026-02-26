"""Count fixtures on plan pages using the Claude Vision API."""

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


def _crop_to_viewport(
    image_bytes: bytes,
    viewport_bbox: tuple[float, float, float, float],
    pdf_width: float,
    pdf_height: float,
) -> bytes:
    """Crop a rendered page image to just the viewport area.

    Converts PDF-point coordinates to pixel coordinates based on the
    image dimensions, then crops.
    """
    img = Image.open(io.BytesIO(image_bytes))
    iw, ih = img.size
    x_scale = iw / pdf_width
    y_scale = ih / pdf_height
    x0, y0, x1, y1 = viewport_bbox
    crop_box = (
        int(x0 * x_scale),
        int(y0 * y_scale),
        int(x1 * x_scale),
        int(y1 * y_scale),
    )
    cropped = img.crop(crop_box)
    buf = io.BytesIO()
    cropped.save(buf, format="PNG")
    return buf.getvalue()


def _build_prompt(fixture_codes: list[str], sheet_code: str) -> str:
    """Build the vision prompt that asks Claude to count fixtures."""
    codes_list = ", ".join(fixture_codes)
    return (
        "You are analyzing an electrical lighting plan drawing. "
        f"This is sheet {sheet_code}.\n\n"
        "Your task is to count how many times each of the following "
        "lighting fixture type codes appears on this plan:\n"
        f"  {codes_list}\n\n"
        "Fixture codes are typically shown as labels next to fixture "
        "symbols (circles, rectangles, or other shapes). They consist "
        "of one or two uppercase letters followed by one or two digits "
        "(e.g., A1, B6, D7, AA1).\n\n"
        "IMPORTANT:\n"
        "- Count each individual fixture label, not groups.\n"
        "- Do NOT count codes that appear in the title block "
        "(bottom-right corner), notes sections, or schedule tables.\n"
        "- Do NOT count codes that appear in keynote legends.\n"
        "- If a code does not appear on the plan, report 0.\n\n"
        "Return your answer as a JSON object mapping each fixture code "
        "to its count. Return ONLY the JSON, no other text.\n\n"
        "Example response:\n"
        '{"A1": 12, "B6": 5, "D7": 0}\n'
    )


def _parse_vision_response(
    response_text: str,
    fixture_codes: list[str],
) -> dict[str, int]:
    """Parse the JSON fixture counts from the vision API response.

    Handles cases where the model wraps JSON in markdown code fences
    or includes extra commentary.
    """
    # Try to extract JSON from code fences first.
    fence_match = re.search(
        r'```(?:json)?\s*(\{.*?\})\s*```', response_text, re.DOTALL
    )
    if fence_match:
        json_str = fence_match.group(1)
    else:
        # Try to find a bare JSON object.
        brace_match = re.search(r'\{[^{}]*\}', response_text, re.DOTALL)
        if brace_match:
            json_str = brace_match.group(0)
        else:
            logger.warning(
                "Could not find JSON in vision response: %s",
                response_text[:200],
            )
            return {code: 0 for code in fixture_codes}

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as exc:
        logger.warning("Failed to parse vision JSON: %s", exc)
        return {code: 0 for code in fixture_codes}

    if not isinstance(data, dict):
        logger.warning("Vision response JSON is not a dict: %s", type(data))
        return {code: 0 for code in fixture_codes}

    # Normalize keys and extract counts.
    counts: dict[str, int] = {}
    response_upper = {k.upper(): v for k, v in data.items()}
    for code in fixture_codes:
        raw = response_upper.get(code.upper(), 0)
        try:
            counts[code] = int(raw)
        except (ValueError, TypeError):
            logger.warning(
                "Non-integer count for fixture %s: %r", code, raw
            )
            counts[code] = 0

    return counts


def count_fixtures_vision(
    page_info: PageInfo,
    image_bytes: bytes,
    fixture_codes: list[str],
    config: MedinaConfig | None = None,
) -> dict[str, int]:
    """Count fixtures on a plan page using the Claude Vision API.

    Args:
        page_info: Page metadata.
        image_bytes: PNG image bytes of the rendered page.
        fixture_codes: Fixture codes to look for.
        config: Configuration with API key and model settings.
            If ``None``, loads from environment.

    Returns:
        Dict mapping fixture_code to count.

    Raises:
        VisionAPIError: If the API call fails.
    """
    if config is None:
        config = get_config()

    sheet = page_info.sheet_code or f"page_{page_info.page_number}"
    logger.info("Vision counting fixtures on plan %s", sheet)

    if not fixture_codes:
        logger.warning("No fixture codes provided for vision counting")
        return {}

    if not config.has_vlm_key:
        raise VisionAPIError(
            "No VLM API key configured. "
            "Set MEDINA_ANTHROPIC_API_KEY, MEDINA_GEMINI_API_KEY, "
            "or MEDINA_OPENROUTER_API_KEY in environment or .env file."
        )

    prompt = _build_prompt(fixture_codes, sheet)

    # Crop to viewport if this is a sub-plan on a multi-viewport page.
    img_to_send = image_bytes
    if page_info.viewport_bbox is not None:
        try:
            from medina.pdf.renderer import render_page_to_pil
            # Need original PDF dimensions for coordinate mapping.
            # Estimate from image + DPI, or use a standard approach.
            img = Image.open(io.BytesIO(image_bytes))
            iw, ih = img.size
            # We don't know the exact PDF dimensions here, but viewport_bbox
            # is in PDF points. Estimate PDF size from the image assuming
            # the DPI used for rendering.
            # Common approach: assume 150 DPI (the max used for vision).
            est_dpi = 150
            pdf_w = iw * 72 / est_dpi
            pdf_h = ih * 72 / est_dpi
            img_to_send = _crop_to_viewport(
                image_bytes, page_info.viewport_bbox, pdf_w, pdf_h,
            )
            logger.debug(
                "Cropped vision image to viewport %s for %s",
                page_info.viewport_bbox, sheet,
            )
        except Exception as e:
            logger.warning("Viewport crop failed for %s: %s", sheet, e)

    from medina.vlm_client import get_vlm_client
    vlm = get_vlm_client(config)

    try:
        response_text = vlm.vision_query(
            images=[img_to_send],
            prompt=prompt,
            max_tokens=2000,
        )
    except Exception as exc:
        raise VisionAPIError(
            f"Vision API call failed for plan {sheet}: {exc}"
        ) from exc

    if not response_text:
        logger.warning("Empty response from vision API for plan %s", sheet)
        return {code: 0 for code in fixture_codes}

    logger.debug("Vision response for %s: %s", sheet, response_text[:300])
    counts = _parse_vision_response(response_text, fixture_codes)

    total = sum(counts.values())
    logger.info(
        "Vision plan %s: found %d total fixtures across %d types",
        sheet, total, sum(1 for c in counts.values() if c > 0),
    )
    return counts


def count_all_plans_vision(
    plan_pages: list[PageInfo],
    page_images: dict[int, bytes],
    fixture_codes: list[str],
    config: MedinaConfig | None = None,
) -> dict[str, dict[str, int]]:
    """Count fixtures on all plan pages using the Vision API.

    Args:
        plan_pages: List of page metadata for lighting plan pages.
        page_images: Mapping of page_number to PNG image bytes.
        fixture_codes: Fixture type codes to search for.
        config: Configuration with API key and model settings.

    Returns:
        ``{sheet_code: {fixture_code: count}}`` for every plan page.
    """
    if config is None:
        config = get_config()

    results: dict[str, dict[str, int]] = {}

    for page_info in plan_pages:
        sheet = page_info.sheet_code or f"page_{page_info.page_number}"
        image_bytes = page_images.get(page_info.page_number)
        if image_bytes is None:
            logger.warning(
                "No rendered image for plan %s (page %d), skipping",
                sheet, page_info.page_number,
            )
            results[sheet] = {code: 0 for code in fixture_codes}
            continue

        try:
            counts = count_fixtures_vision(
                page_info, image_bytes, fixture_codes, config
            )
        except VisionAPIError:
            logger.exception("Vision counting failed for plan %s", sheet)
            counts = {code: 0 for code in fixture_codes}

        results[sheet] = counts

    return results
