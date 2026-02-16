"""PDF and folder loading, page normalization."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import pdfplumber

from medina.exceptions import PDFLoadError
from medina.models import PageInfo, PageType

logger = logging.getLogger(__name__)

# Pattern for folder-of-PDFs naming: [NUMBER]---[SHEET-CODE] [DESC].pdf
_FOLDER_FILE_RE = re.compile(
    r"^(\d+)---([A-Za-z0-9.]+)\s+(.+)\.pdf$",
    re.IGNORECASE,
)

# Common title-block sheet code pattern found in bottom-right of pages.
# Supports: E200, E1A, E2.2, E1.11R, E0.3, E5.1
_SHEET_CODE_RE = re.compile(
    r"\b(E\d{1,3}(?:\.\d{1,3})?[A-Za-z]?)\b",
)

# Broader sheet code pattern for non-standard naming (e.g., FE10691-013)
_BROAD_SHEET_CODE_RE = re.compile(
    r"\b([A-Z]{1,3}\d{3,}[-]\d{2,3})\b",
)


def load(
    source: str | Path,
) -> tuple[list[PageInfo], dict[int, Any]]:
    """Load pages from a PDF file or folder of PDFs.

    Args:
        source: Path to a single PDF or a directory of individual PDFs.

    Returns:
        Tuple of (page_infos, pdf_pages_dict) where pdf_pages_dict maps
        page_number to the pdfplumber page object.

    Raises:
        PDFLoadError: If the source cannot be loaded.
    """
    source = Path(source)
    if not source.exists():
        raise PDFLoadError(f"Source path does not exist: {source}")

    if source.is_file():
        return _load_single_pdf(source)
    elif source.is_dir():
        return _load_folder(source)
    else:
        raise PDFLoadError(
            f"Source is neither a file nor directory: {source}"
        )


def _load_single_pdf(
    pdf_path: Path,
) -> tuple[list[PageInfo], dict[int, Any]]:
    """Load a single multi-page PDF file.

    Extracts sheet codes from the title block area of each page.
    """
    logger.info("Loading single PDF: %s", pdf_path)
    try:
        pdf = pdfplumber.open(pdf_path)
    except Exception as exc:
        raise PDFLoadError(
            f"Failed to open PDF {pdf_path}: {exc}"
        ) from exc

    pages: list[PageInfo] = []
    pdf_pages: dict[int, Any] = {}

    for idx, page in enumerate(pdf.pages):
        page_num = idx + 1
        sheet_code = _extract_sheet_code_from_title_block(page)
        sheet_title = _extract_sheet_title(page, sheet_code)

        info = PageInfo(
            page_number=page_num,
            sheet_code=sheet_code,
            sheet_title=sheet_title,
            page_type=PageType.OTHER,
            source_path=pdf_path,
            pdf_page_index=idx,
        )
        pages.append(info)
        pdf_pages[page_num] = page

    logger.info(
        "Loaded %d pages from %s", len(pages), pdf_path.name
    )
    return pages, pdf_pages


def _load_folder(
    folder_path: Path,
) -> tuple[list[PageInfo], dict[int, Any]]:
    """Load a folder of individual PDF files.

    Files are expected to follow the naming convention:
    ``[NUMBER]---[SHEET-CODE] [DESCRIPTION].pdf``
    Files that don't match the pattern are loaded with best-effort
    parsing.
    """
    logger.info("Loading PDF folder: %s", folder_path)

    pdf_files = sorted(
        [f for f in folder_path.iterdir() if f.suffix.lower() == ".pdf"],
        key=lambda f: _sort_key_for_file(f),
    )

    if not pdf_files:
        raise PDFLoadError(
            f"No PDF files found in folder: {folder_path}"
        )

    pages: list[PageInfo] = []
    pdf_pages: dict[int, Any] = {}

    # First pass: load all files and resolve true sheet codes from title blocks.
    raw_entries: list[tuple[Path, str | None, str | None, Any]] = []
    for pdf_file in pdf_files:
        filename_code, sheet_title = _parse_filename(pdf_file)

        try:
            pdf = pdfplumber.open(pdf_file)
        except Exception as exc:
            logger.warning(
                "Skipping unreadable PDF %s: %s",
                pdf_file.name,
                exc,
            )
            continue

        if not pdf.pages:
            logger.warning(
                "PDF has no pages: %s", pdf_file.name
            )
            pdf.close()
            continue

        pdfplumber_page = pdf.pages[0]

        # Always check title block for the canonical sheet code.
        title_block_code = _extract_sheet_code_from_title_block(pdfplumber_page)
        sheet_code = title_block_code or filename_code

        raw_entries.append((pdf_file, sheet_code, sheet_title, pdfplumber_page))

    # Deduplicate: when multiple files share the same sheet code (e.g.,
    # original + addendum), keep only the last one (highest file number
    # = latest revision). Files are already sorted by number prefix.
    seen_codes: dict[str, int] = {}
    for idx, (pdf_file, sheet_code, _title, _page) in enumerate(raw_entries):
        if sheet_code:
            code_upper = sheet_code.upper()
            if code_upper in seen_codes:
                prev_idx = seen_codes[code_upper]
                prev_file = raw_entries[prev_idx][0]
                logger.info(
                    "Sheet %s: replacing %s with newer revision %s",
                    code_upper, prev_file.name, pdf_file.name,
                )
            seen_codes[code_upper] = idx

    # Build the final set: for duplicated codes keep only the latest;
    # for unique codes or unknown codes, keep everything.
    keep_indices: set[int] = set()
    for idx, (_file, sheet_code, _title, _page) in enumerate(raw_entries):
        if sheet_code:
            code_upper = sheet_code.upper()
            if seen_codes.get(code_upper) == idx:
                keep_indices.add(idx)
        else:
            keep_indices.add(idx)

    page_num = 0
    for idx, (pdf_file, sheet_code, sheet_title, pdfplumber_page) in enumerate(raw_entries):
        if idx not in keep_indices:
            logger.debug("Skipping superseded file: %s", pdf_file.name)
            continue
        page_num += 1

        info = PageInfo(
            page_number=page_num,
            sheet_code=sheet_code,
            sheet_title=sheet_title,
            page_type=PageType.OTHER,
            source_path=pdf_file,
            pdf_page_index=0,
        )
        pages.append(info)
        pdf_pages[page_num] = pdfplumber_page

    logger.info(
        "Loaded %d pages from folder %s (after deduplication)",
        len(pages),
        folder_path.name,
    )
    return pages, pdf_pages


# ── Private helpers ─────────────────────────────────────────────


def _sort_key_for_file(path: Path) -> tuple[int, str]:
    """Return a sort key that orders by leading number prefix."""
    match = re.match(r"^(\d+)", path.name)
    if match:
        return (int(match.group(1)), path.name.lower())
    return (999999, path.name.lower())


def _parse_filename(
    pdf_file: Path,
) -> tuple[str | None, str | None]:
    """Extract sheet_code and description from a folder-PDF filename.

    Expected format: ``007---E1.11R GYM LIGHTING PLAN - ROGERS.pdf``
    Returns (sheet_code, description) or (None, None) if no match.
    """
    match = _FOLDER_FILE_RE.match(pdf_file.name)
    if match:
        sheet_code = match.group(2).upper()
        description = match.group(3).strip()
        return sheet_code, description

    # Best-effort: try to find a sheet code anywhere in filename
    stem = pdf_file.stem
    code_match = _SHEET_CODE_RE.search(stem)
    if code_match:
        return code_match.group(1).upper(), stem
    return None, stem


def _extract_sheet_code_from_title_block(
    page: Any,
) -> str | None:
    """Attempt to read the sheet code from the title block area.

    Title blocks are typically in the bottom-right ~25% of the page.
    """
    width = page.width
    height = page.height

    # Crop to bottom-right quadrant where title blocks reside.
    bbox = (
        width * 0.60,   # left
        height * 0.80,  # top
        width,           # right
        height,          # bottom
    )
    try:
        cropped = page.within_bbox(bbox)
        text = cropped.extract_text() or ""
    except Exception:
        # within_bbox can fail on unusual page layouts
        text = ""

    if not text:
        return None

    # Look for a standalone sheet code like E200, E1A, E001, CS
    # Try electrical sheet codes first.
    for line in reversed(text.split("\n")):
        line = line.strip()
        code_match = _SHEET_CODE_RE.search(line)
        if code_match:
            return code_match.group(1).upper()

    # Try broader patterns for non-standard codes (FE10691-013)
    for line in reversed(text.split("\n")):
        line = line.strip()
        broad_match = _BROAD_SHEET_CODE_RE.search(line)
        if broad_match:
            return broad_match.group(1).upper()

    # Also try generic sheet codes (CS, A1, etc.)
    generic_re = re.compile(r"\b([A-Z]{1,2}\d{1,4}[A-Za-z]?)\b")
    for line in reversed(text.split("\n")):
        match = generic_re.search(line.strip())
        if match:
            return match.group(1).upper()

    return None


def _extract_sheet_title(
    page: Any,
    sheet_code: str | None,
) -> str | None:
    """Attempt to extract the sheet title from near the title block."""
    width = page.width
    height = page.height

    bbox = (
        width * 0.55,
        height * 0.85,
        width,
        height,
    )
    try:
        cropped = page.within_bbox(bbox)
        text = cropped.extract_text() or ""
    except Exception:
        return None

    if not text:
        return None

    # Return the longest line that isn't the sheet code itself,
    # as it's likely the title.
    lines = [
        ln.strip()
        for ln in text.split("\n")
        if ln.strip() and ln.strip().upper() != (sheet_code or "")
    ]
    if lines:
        return max(lines, key=len)
    return None
