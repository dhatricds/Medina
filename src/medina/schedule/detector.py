"""Detect pages that contain luminaire schedule tables."""

from __future__ import annotations

import logging
from typing import Any

from medina.config import MedinaConfig, get_config
from medina.models import PageInfo, PageType

logger = logging.getLogger(__name__)

# Default keywords used when no config is provided.
_DEFAULT_INCLUDE = [
    "luminaire schedule",
    "light fixture schedule",
    "lighting schedule",
    "fixture schedule",
]
_DEFAULT_EXCLUDE = [
    "panel schedule",
    "motor schedule",
    "equipment schedule",
    "floorbox",
    "poke thru",
]


def _page_has_luminaire_schedule(
    text: str,
    include_keywords: list[str],
    exclude_keywords: list[str],
) -> bool:
    """Return True if *text* contains a luminaire-related schedule heading.

    A page qualifies when it matches at least one include keyword and the
    match is not solely in a region dominated by an exclude keyword.
    """
    text_lower = text.lower()

    has_include = any(kw in text_lower for kw in include_keywords)
    if not has_include:
        return False

    # If exclude keywords are present we do a simple heuristic: the page
    # still qualifies as long as at least one include keyword appears in a
    # position that is not immediately preceded by an exclude keyword.
    # For the common case this is sufficient.
    for exc_kw in exclude_keywords:
        if exc_kw in text_lower:
            # Check whether every include-keyword occurrence sits inside
            # an exclude-keyword region.  If at least one is independent
            # we keep the page.
            independent = False
            for inc_kw in include_keywords:
                idx = text_lower.find(inc_kw)
                while idx != -1:
                    # Look backward from the match for the exclude keyword.
                    preceding = text_lower[max(0, idx - len(exc_kw) - 5): idx]
                    if exc_kw not in preceding:
                        independent = True
                        break
                    idx = text_lower.find(inc_kw, idx + 1)
                if independent:
                    break
            if not independent:
                return False

    return True


def detect_schedule_pages(
    pages: list[PageInfo],
    pdf_pages: dict[int, Any],
    config: MedinaConfig | None = None,
) -> list[PageInfo]:
    """Identify pages that contain luminaire/lighting fixture schedule tables.

    Args:
        pages: All loaded page metadata.
        pdf_pages: Mapping of page number to the pdfplumber page object.
        config: Optional application config for keyword lists.

    Returns:
        List of PageInfo for pages that contain luminaire schedule tables.
    """
    if config is None:
        try:
            config = get_config()
        except Exception:
            config = None

    include_keywords = (
        config.schedule_include_keywords if config else _DEFAULT_INCLUDE
    )
    exclude_keywords = (
        config.schedule_exclude_keywords if config else _DEFAULT_EXCLUDE
    )

    schedule_pages: list[PageInfo] = []

    for page in pages:
        pdf_page = pdf_pages.get(page.page_number)
        if pdf_page is None:
            logger.debug(
                "No pdfplumber page for page_number=%d, skipping",
                page.page_number,
            )
            continue

        # Already classified as schedule — still verify content.
        is_candidate = page.page_type == PageType.SCHEDULE

        try:
            text = pdf_page.extract_text() or ""
        except Exception:
            logger.warning(
                "Failed to extract text from page %d (%s)",
                page.page_number,
                page.sheet_code,
                exc_info=True,
            )
            # If already classified as schedule, include it anyway.
            if is_candidate:
                schedule_pages.append(page)
            continue

        if _page_has_luminaire_schedule(text, include_keywords, exclude_keywords):
            logger.info(
                "Detected luminaire schedule on page %d (sheet %s)",
                page.page_number,
                page.sheet_code,
            )
            schedule_pages.append(page)
        elif is_candidate:
            # Classified as schedule but no luminaire keywords — could be a
            # panel or equipment schedule.  Still check for a generic
            # "schedule" keyword combined with fixture-related terms.
            text_lower = text.lower()
            if "schedule" in text_lower and any(
                term in text_lower
                for term in ("fixture", "luminaire", "lighting", "lamp", "led")
            ):
                logger.info(
                    "Page %d (sheet %s) classified as schedule and "
                    "contains fixture-related terms — including it",
                    page.page_number,
                    page.sheet_code,
                )
                schedule_pages.append(page)
            else:
                logger.debug(
                    "Page %d (sheet %s) classified as schedule but "
                    "no luminaire keywords found — skipping",
                    page.page_number,
                    page.sheet_code,
                )

    if not schedule_pages:
        logger.warning("No luminaire schedule pages detected")

    return schedule_pages
