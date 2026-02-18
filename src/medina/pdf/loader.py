"""PDF and folder loading, page normalization."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import fitz as pymupdf
import pdfplumber

from medina.exceptions import PDFLoadError
from medina.models import PageInfo, PageType

logger = logging.getLogger(__name__)

# In-memory cache: avoids reloading the same PDF across multiple agents
# in a single process.  Key = resolved absolute path string.
_load_cache: dict[str, tuple[list[PageInfo], dict[int, Any]]] = {}

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

# Pages with content streams larger than this are too dense for
# pdfplumber to extract text in reasonable time.  Checked via fitz
# (instant — reads raw byte length without parsing).
_MAX_CONTENT_STREAM_BYTES = 10_000_000  # 10 MB


def clear_load_cache() -> None:
    """Clear the in-memory PDF load cache."""
    _load_cache.clear()


def load(
    source: str | Path,
) -> tuple[list[PageInfo], dict[int, Any]]:
    """Load pages from a PDF file or folder of PDFs.

    Uses PyMuPDF (fitz) for fast sheet code / title extraction on
    dense vector pages, falling back to pdfplumber for normal pages.
    Always opens pdfplumber for downstream use (table extraction,
    char-level analysis, line geometry).

    Returns:
        Tuple of (page_infos, pdf_pages_dict) where pdf_pages_dict maps
        page_number to the pdfplumber page object.
    """
    source = Path(source)
    if not source.exists():
        raise PDFLoadError(f"Source path does not exist: {source}")

    cache_key = str(source.resolve())
    if cache_key in _load_cache:
        logger.info("Returning cached load for %s", source.name)
        return _load_cache[cache_key]

    if source.is_file():
        result = _load_single_pdf(source)
    elif source.is_dir():
        result = _load_folder(source)
    else:
        raise PDFLoadError(
            f"Source is neither a file nor directory: {source}"
        )

    _load_cache[cache_key] = result
    return result


def _load_single_pdf(
    pdf_path: Path,
) -> tuple[list[PageInfo], dict[int, Any]]:
    """Load a single multi-page PDF file.

    For each page:
    1. Check content stream size with fitz (instant, no parsing).
    2. If dense (>10MB stream): use fitz for sheet code extraction.
    3. If normal: use pdfplumber (more reliable on typical PDFs).
    4. Always keep pdfplumber page objects for downstream use.
    """
    logger.info("Loading single PDF: %s", pdf_path)

    # --- Identify dense pages via fitz (instant check) ---
    try:
        fitz_doc = pymupdf.open(str(pdf_path))
    except Exception as exc:
        raise PDFLoadError(
            f"Failed to open PDF {pdf_path}: {exc}"
        ) from exc

    dense_pages: set[int] = set()  # 0-indexed
    fitz_codes: dict[int, tuple[str | None, str | None]] = {}

    for idx in range(len(fitz_doc)):
        fitz_page = fitz_doc[idx]
        try:
            stream_size = len(fitz_page.read_contents())
        except Exception:
            stream_size = 0
        if stream_size > _MAX_CONTENT_STREAM_BYTES:
            dense_pages.add(idx)
            # Extract sheet code via fitz for dense pages
            code = _fitz_extract_sheet_code(fitz_page)
            title = _fitz_extract_sheet_title(fitz_page, code)
            fitz_codes[idx] = (code, title)
            logger.info(
                "Page %d: dense (%d MB stream) — using fitz "
                "for metadata",
                idx + 1,
                stream_size // 1_000_000,
            )

    fitz_doc.close()

    # --- Open with pdfplumber ---
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

        if idx in dense_pages:
            # Use fitz-extracted metadata (skip pdfplumber text ops)
            sheet_code, sheet_title = fitz_codes[idx]
        else:
            # Normal page: pdfplumber extraction is fast and reliable
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
        "Loaded %d pages from %s (%d dense)",
        len(pages),
        pdf_path.name,
        len(dense_pages),
    )
    return pages, pdf_pages


def _load_folder(
    folder_path: Path,
) -> tuple[list[PageInfo], dict[int, Any]]:
    """Load a folder of individual PDF files.

    Files are expected to follow the naming convention:
    ``[NUMBER]---[SHEET-CODE] [DESCRIPTION].pdf``
    """
    logger.info("Loading PDF folder: %s", folder_path)

    pdf_files = sorted(
        [
            f
            for f in folder_path.iterdir()
            if f.suffix.lower() == ".pdf"
        ],
        key=lambda f: _sort_key_for_file(f),
    )

    if not pdf_files:
        raise PDFLoadError(
            f"No PDF files found in folder: {folder_path}"
        )

    pages: list[PageInfo] = []
    pdf_pages: dict[int, Any] = {}

    raw_entries: list[
        tuple[Path, str | None, str | None, Any]
    ] = []
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

        # Check density via fitz first
        title_block_code = None
        try:
            fitz_doc = pymupdf.open(str(pdf_file))
            stream_size = len(fitz_doc[0].read_contents())
            if stream_size > _MAX_CONTENT_STREAM_BYTES:
                title_block_code = _fitz_extract_sheet_code(
                    fitz_doc[0]
                )
            fitz_doc.close()
        except Exception:
            pass

        if title_block_code is None:
            title_block_code = _extract_sheet_code_from_title_block(
                pdfplumber_page
            )

        sheet_code = title_block_code or filename_code
        raw_entries.append(
            (pdf_file, sheet_code, sheet_title, pdfplumber_page)
        )

    # Deduplicate by sheet code (keep latest revision)
    seen_codes: dict[str, int] = {}
    for idx, (pdf_file, sheet_code, _title, _page) in enumerate(
        raw_entries
    ):
        if sheet_code:
            code_upper = sheet_code.upper()
            if code_upper in seen_codes:
                prev_idx = seen_codes[code_upper]
                prev_file = raw_entries[prev_idx][0]
                logger.info(
                    "Sheet %s: replacing %s with newer revision %s",
                    code_upper,
                    prev_file.name,
                    pdf_file.name,
                )
            seen_codes[code_upper] = idx

    keep_indices: set[int] = set()
    for idx, (_file, sheet_code, _title, _page) in enumerate(
        raw_entries
    ):
        if sheet_code:
            code_upper = sheet_code.upper()
            if seen_codes.get(code_upper) == idx:
                keep_indices.add(idx)
        else:
            keep_indices.add(idx)

    page_num = 0
    for idx, (
        pdf_file,
        sheet_code,
        sheet_title,
        pdfplumber_page,
    ) in enumerate(raw_entries):
        if idx not in keep_indices:
            logger.debug(
                "Skipping superseded file: %s", pdf_file.name
            )
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


# ── fitz-based fast extraction (for dense pages) ─────────────


def _fitz_extract_sheet_code(page: Any) -> str | None:
    """Extract sheet code from title block using PyMuPDF (fitz)."""
    rect = page.rect
    clip = pymupdf.Rect(
        rect.width * 0.60,
        rect.height * 0.80,
        rect.width,
        rect.height,
    )
    try:
        text = page.get_text("text", clip=clip)
    except Exception:
        return None

    return _find_sheet_code_in_text(text)


def _fitz_extract_sheet_title(
    page: Any,
    sheet_code: str | None,
) -> str | None:
    """Extract sheet title from title block using PyMuPDF (fitz)."""
    rect = page.rect
    clip = pymupdf.Rect(
        rect.width * 0.55,
        rect.height * 0.85,
        rect.width,
        rect.height,
    )
    try:
        text = page.get_text("text", clip=clip)
    except Exception:
        return None

    if not text or not text.strip():
        return None

    lines = [
        ln.strip()
        for ln in text.split("\n")
        if ln.strip()
        and ln.strip().upper() != (sheet_code or "")
    ]
    if lines:
        return max(lines, key=len)
    return None


# ── pdfplumber-based extraction (for normal pages) ───────────


def _extract_sheet_code_from_title_block(
    page: Any,
) -> str | None:
    """Extract sheet code from title block using pdfplumber."""
    width = page.width
    height = page.height

    bbox = (
        width * 0.60,
        height * 0.80,
        width,
        height,
    )
    try:
        cropped = page.within_bbox(bbox)
        text = cropped.extract_text() or ""
    except Exception:
        text = ""

    return _find_sheet_code_in_text(text)


def _extract_sheet_title(
    page: Any,
    sheet_code: str | None,
) -> str | None:
    """Extract sheet title from title block using pdfplumber."""
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

    lines = [
        ln.strip()
        for ln in text.split("\n")
        if ln.strip()
        and ln.strip().upper() != (sheet_code or "")
    ]
    if lines:
        return max(lines, key=len)
    return None


# ── Shared helpers ───────────────────────────────────────────


def _find_sheet_code_in_text(text: str | None) -> str | None:
    """Search for a sheet code in title block text."""
    if not text or not text.strip():
        return None

    for line in reversed(text.split("\n")):
        line = line.strip()
        if not line:
            continue
        code_match = _SHEET_CODE_RE.search(line)
        if code_match:
            return code_match.group(1).upper()

    for line in reversed(text.split("\n")):
        line = line.strip()
        broad_match = _BROAD_SHEET_CODE_RE.search(line)
        if broad_match:
            return broad_match.group(1).upper()

    generic_re = re.compile(r"\b([A-Z]{1,2}\d{1,4}[A-Za-z]?)\b")
    for line in reversed(text.split("\n")):
        match = generic_re.search(line.strip())
        if match:
            return match.group(1).upper()

    return None


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

    stem = pdf_file.stem
    code_match = _SHEET_CODE_RE.search(stem)
    if code_match:
        return code_match.group(1).upper(), stem
    return None, stem
