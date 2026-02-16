"""Count fixtures on plan pages using the Claude Vision API."""

from __future__ import annotations

import base64
import json
import logging
import re
from typing import Any

from medina.config import MedinaConfig, get_config
from medina.exceptions import VisionAPIError
from medina.models import PageInfo

logger = logging.getLogger(__name__)


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

    if not config.anthropic_api_key:
        raise VisionAPIError(
            "Anthropic API key not configured. "
            "Set MEDINA_ANTHROPIC_API_KEY in environment or .env file."
        )

    try:
        from anthropic import Anthropic
    except ImportError as exc:
        raise VisionAPIError(
            "anthropic package not installed. Run: pip install anthropic"
        ) from exc

    prompt = _build_prompt(fixture_codes, sheet)
    encoded_image = base64.b64encode(image_bytes).decode()

    try:
        client = Anthropic(api_key=config.anthropic_api_key)
        message = client.messages.create(
            model=config.vision_model,
            max_tokens=2000,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": encoded_image,
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
            f"Vision API call failed for plan {sheet}: {exc}"
        ) from exc

    # Extract text content from the response.
    response_text = ""
    for block in message.content:
        if hasattr(block, "text"):
            response_text += block.text

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
