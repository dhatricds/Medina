"""Extract raw table data from schedule pages using pdfplumber."""

from __future__ import annotations

import logging
from typing import Any

from medina.exceptions import ScheduleExtractionError
from medina.models import PageInfo

logger = logging.getLogger(__name__)

# pdfplumber table-extraction settings — line-based (primary).
_LINES_SETTINGS: dict[str, Any] = {
    "vertical_strategy": "lines",
    "horizontal_strategy": "lines",
    "snap_tolerance": 5,
    "join_tolerance": 5,
}

# Fallback: text-based detection for pages without ruled lines.
_TEXT_SETTINGS: dict[str, Any] = {
    "vertical_strategy": "text",
    "horizontal_strategy": "text",
    "snap_tolerance": 5,
    "join_tolerance": 5,
}


def _clean_cell(value: Any) -> str:
    """Normalise a single cell value to a stripped string."""
    if value is None:
        return ""
    text = str(value).strip()
    # Collapse runs of whitespace (including newlines) into a single space.
    return " ".join(text.split())


def _clean_table(raw: list[list[Any]]) -> list[list[str]]:
    """Clean every cell in a raw pdfplumber table."""
    return [
        [_clean_cell(cell) for cell in row]
        for row in raw
    ]


def _is_empty_table(table: list[list[str]]) -> bool:
    """Return True if a table has no meaningful content."""
    for row in table:
        if any(cell for cell in row):
            return False
    return True


def extract_schedule_tables(
    page_info: PageInfo,
    pdf_page: Any,
) -> list[list[list[str]]]:
    """Extract all tables from a schedule page.

    Tries line-based extraction first; if that yields no tables, falls back
    to text-based extraction.

    Args:
        page_info: Metadata for the page being processed.
        pdf_page: A pdfplumber page object.

    Returns:
        List of tables.  Each table is a list of rows; each row is a list
        of cell strings.

    Raises:
        ScheduleExtractionError: When pdfplumber fails unexpectedly.
    """
    sheet_label = page_info.sheet_code or f"page {page_info.page_number}"

    try:
        raw_tables = pdf_page.extract_tables(table_settings=_LINES_SETTINGS)
    except Exception as exc:
        raise ScheduleExtractionError(
            f"Line-based table extraction failed on {sheet_label}: {exc}"
        ) from exc

    tables: list[list[list[str]]] = []

    if raw_tables:
        for raw in raw_tables:
            cleaned = _clean_table(raw)
            if not _is_empty_table(cleaned):
                tables.append(cleaned)

    if tables:
        logger.info(
            "Extracted %d table(s) from %s using line-based strategy",
            len(tables),
            sheet_label,
        )
        return tables

    # Fallback: text-based extraction.
    logger.debug(
        "No line-based tables on %s — trying text-based strategy",
        sheet_label,
    )

    try:
        raw_tables = pdf_page.extract_tables(table_settings=_TEXT_SETTINGS)
    except Exception as exc:
        raise ScheduleExtractionError(
            f"Text-based table extraction failed on {sheet_label}: {exc}"
        ) from exc

    if raw_tables:
        for raw in raw_tables:
            cleaned = _clean_table(raw)
            if not _is_empty_table(cleaned):
                tables.append(cleaned)

    if tables:
        logger.info(
            "Extracted %d table(s) from %s using text-based strategy",
            len(tables),
            sheet_label,
        )
    else:
        logger.warning("No tables found on schedule page %s", sheet_label)

    return tables
