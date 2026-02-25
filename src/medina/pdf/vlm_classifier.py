"""VLM-based page classification fallback.

When the sheet index is missing and standard classification (title block,
prefix rules, content scan) fails to identify schedule or lighting plan
pages, this module renders low-resolution thumbnails and asks Claude Vision
to classify them.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from medina.config import MedinaConfig, get_config
from medina.exceptions import VisionAPIError
from medina.models import PageInfo, PageType

logger = logging.getLogger(__name__)

_CLASSIFICATION_PROMPT = """\
You are analyzing electrical construction drawing pages from a PDF. \
Your task is to classify each page into one or more of these categories:

- "luminaire_schedule": A page that contains a LIGHT FIXTURE SCHEDULE table \
(also called a Luminaire Schedule). This is a TABLE with columns like TYPE, \
DESCRIPTION, VOLTAGE, MOUNTING, LUMENS, CCT, etc. \
Do NOT confuse with Panel Schedules, Motor Schedules, or Equipment Schedules.

- "lighting_plan": A page that shows a FLOOR PLAN with lighting fixture \
symbols placed on it. These are architectural floor plans with circles, \
squares, or other symbols representing light fixtures. \
Do NOT confuse with Power Plans (which show outlets and circuits) or \
Demolition Plans (which show items to be removed, usually with dashed lines \
or "DEMO" in the title).

- "other": A page that is neither a luminaire schedule nor a lighting plan. \
This includes cover sheets, symbol legends, power plans, demolition plans, \
detail pages, fire alarm pages, riser diagrams, site plans, etc.

IMPORTANT: A page can be BOTH "luminaire_schedule" AND "lighting_plan" — \
this happens when a floor plan has an embedded schedule table on the same page.

For each page image provided, return your classification. \
The images are labeled with their page numbers.

Return ONLY a JSON object mapping page number (as string) to a list of \
classifications. Example:
{
  "3": ["lighting_plan"],
  "5": ["luminaire_schedule"],
  "7": ["luminaire_schedule", "lighting_plan"],
  "8": ["other"]
}
"""


def classify_pages_vlm(
    pages: list[PageInfo],
    config: MedinaConfig | None = None,
    batch_size: int = 8,
) -> dict[int, list[PageType]]:
    """Classify pages using Claude Vision API.

    Renders candidate pages at 72 DPI and sends them to Claude Vision
    in batches for classification.

    Args:
        pages: Pages to classify (should be filtered to candidates only).
        config: Optional configuration override.
        batch_size: Maximum number of pages per API call.

    Returns:
        Mapping of page_number to list of PageType classifications.
    """
    if config is None:
        config = get_config()

    has_key = (
        config.anthropic_api_key
        if config.vlm_provider != "gemini"
        else config.gemini_api_key
    )
    if not has_key:
        logger.warning("No API key available for VLM classification")
        return {}

    if not pages:
        return {}

    from medina.pdf.renderer import render_page_to_image

    # Render all candidate pages at 72 DPI (tiny thumbnails)
    page_images: dict[int, bytes] = {}
    for pinfo in pages:
        label = pinfo.sheet_code or str(pinfo.page_number)
        try:
            img_bytes = render_page_to_image(
                pinfo.source_path,
                pinfo.pdf_page_index,
                dpi=72,
            )
            page_images[pinfo.page_number] = img_bytes
            logger.debug("Rendered page %s at 72 DPI for VLM classification", label)
        except Exception as e:
            logger.warning("Failed to render page %s for VLM classification: %s", label, e)

    if not page_images:
        return {}

    # Process in batches
    results: dict[int, list[PageType]] = {}
    page_numbers = sorted(page_images.keys())

    for batch_start in range(0, len(page_numbers), batch_size):
        batch_nums = page_numbers[batch_start : batch_start + batch_size]
        batch_results = _classify_batch(
            {n: page_images[n] for n in batch_nums},
            pages,
            config,
        )
        results.update(batch_results)

    return results


def _classify_batch(
    page_images: dict[int, bytes],
    pages: list[PageInfo],
    config: MedinaConfig,
) -> dict[int, list[PageType]]:
    """Classify a batch of pages via a single API call."""
    from medina.vlm_client import get_vlm_client

    # Build page number to label mapping
    page_labels: dict[int, str] = {}
    for pinfo in pages:
        if pinfo.page_number in page_images:
            page_labels[pinfo.page_number] = (
                pinfo.sheet_code or str(pinfo.page_number)
            )

    # Build interleaved prompt: text label + image for each page
    page_list = ", ".join(
        f"Page {n} ({page_labels.get(n, str(n))})"
        for n in sorted(page_images.keys())
    )
    prompt_header = (
        f"{_CLASSIFICATION_PROMPT}\n\n"
        f"Pages to classify: {page_list}\n\n"
        f"The following images are the pages, in order:\n"
    )
    for page_num in sorted(page_images.keys()):
        prompt_header += (
            f"\nPage {page_num} "
            f"({page_labels.get(page_num, str(page_num))}): "
            f"[see image {page_num}]\n"
        )

    # Collect images in order
    images = [page_images[n] for n in sorted(page_images.keys())]

    client = get_vlm_client(config)
    response_text = client.vision_query(images, prompt_header, max_tokens=1024)

    return _parse_classification_response(response_text, page_images.keys())


def _parse_classification_response(
    response_text: str,
    valid_page_numbers: Any,
) -> dict[int, list[PageType]]:
    """Parse the VLM classification response JSON."""
    # Extract JSON from response (may be wrapped in markdown code block)
    json_match = re.search(r"\{[\s\S]*\}", response_text)
    if not json_match:
        logger.warning("No JSON found in VLM classification response")
        return {}

    try:
        raw = json.loads(json_match.group())
    except json.JSONDecodeError as e:
        logger.warning("Failed to parse VLM classification JSON: %s", e)
        return {}

    # Map string classifications to PageType
    type_map = {
        "luminaire_schedule": PageType.SCHEDULE,
        "lighting_plan": PageType.LIGHTING_PLAN,
    }

    results: dict[int, list[PageType]] = {}
    for page_key, classifications in raw.items():
        try:
            page_num = int(page_key)
        except (ValueError, TypeError):
            continue

        if page_num not in valid_page_numbers:
            continue

        if not isinstance(classifications, list):
            classifications = [classifications]

        page_types = []
        for cls in classifications:
            cls_str = str(cls).lower().strip()
            if cls_str in type_map:
                page_types.append(type_map[cls_str])

        if page_types:
            results[page_num] = page_types
            logger.info(
                "VLM classified page %d as: %s",
                page_num,
                [t.value for t in page_types],
            )

    return results
