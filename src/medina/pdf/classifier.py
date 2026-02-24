"""Page type classification using sheet index, code prefixes, and content."""

from __future__ import annotations

import logging
import re
from typing import Any

from medina.models import PageInfo, PageType, SheetIndexEntry

logger = logging.getLogger(__name__)

# Sheet-code prefix rules for fallback classification.
# Each entry: (regex pattern, default type, disambiguation keywords)
_PREFIX_RULES: list[
    tuple[re.Pattern[str], PageType, dict[str, PageType]]
] = [
    # E0xx — symbols/legend by default
    (
        re.compile(r"^E0", re.IGNORECASE),
        PageType.SYMBOLS_LEGEND,
        {},
    ),
    # CS — cover sheet
    (
        re.compile(r"^CS$", re.IGNORECASE),
        PageType.COVER,
        {},
    ),
    # E1xx — could be lighting or demolition, check content
    (
        re.compile(r"^E1", re.IGNORECASE),
        PageType.LIGHTING_PLAN,
        {
            "demo": PageType.DEMOLITION_PLAN,
            "demolition": PageType.DEMOLITION_PLAN,
        },
    ),
    # E2xx — lighting plan (but check for power/demolition/signal)
    (
        re.compile(r"^E2", re.IGNORECASE),
        PageType.LIGHTING_PLAN,
        {
            "power": PageType.POWER_PLAN,
            "signal": PageType.OTHER,
            "demo": PageType.DEMOLITION_PLAN,
            "demolition": PageType.DEMOLITION_PLAN,
        },
    ),
    # E3xx — power plan (but may be lighting in some projects)
    (
        re.compile(r"^E3", re.IGNORECASE),
        PageType.POWER_PLAN,
        {
            "lighting": PageType.LIGHTING_PLAN,
        },
    ),
    # E4xx — often power or misc
    (
        re.compile(r"^E4", re.IGNORECASE),
        PageType.POWER_PLAN,
        {},
    ),
    # E5xx, E6xx, E7xx — schedule (but check for non-schedule pages)
    (
        re.compile(r"^E[567]", re.IGNORECASE),
        PageType.SCHEDULE,
        {
            "roof": PageType.OTHER,
            "riser": PageType.RISER,
        },
    ),
    # E8xx — detail
    (
        re.compile(r"^E8", re.IGNORECASE),
        PageType.DETAIL,
        {},
    ),
]

# Content keywords for deepest-fallback classification.
_CONTENT_KEYWORDS: list[tuple[list[str], PageType]] = [
    (
        [
            "luminaire schedule",
            "light fixture schedule",
            "lighting schedule",
            "fixture schedule",
        ],
        PageType.SCHEDULE,
    ),
    (
        ["lighting plan", "lighting layout"],
        PageType.LIGHTING_PLAN,
    ),
    (
        ["demolition plan", "demolition layout", "demo plan"],
        PageType.DEMOLITION_PLAN,
    ),
    (
        [
            "power plan",
            "power layout",
            "receptacle plan",
        ],
        PageType.POWER_PLAN,
    ),
    (
        [
            "electrical symbols",
            "abbreviations",
            "legend",
        ],
        PageType.SYMBOLS_LEGEND,
    ),
    (
        ["site plan", "site layout"],
        PageType.SITE_PLAN,
    ),
    (["fire alarm"], PageType.FIRE_ALARM),
    (["riser diagram", "riser schedule"], PageType.RISER),
    (["detail"], PageType.DETAIL),
]

# Keywords that indicate a non-luminaire schedule (exclude).
_SCHEDULE_EXCLUDE = {
    "panel schedule",
    "motor schedule",
    "equipment schedule",
    "floorbox",
    "poke thru",
}


def classify_pages(
    pages: list[PageInfo],
    pdf_pages: dict[int, Any],
    sheet_index: list[SheetIndexEntry],
) -> list[PageInfo]:
    """Classify each page using sheet index, code prefixes, and content.

    Mutates and returns the same PageInfo list with ``page_type``
    updated.

    Args:
        pages: List of loaded PageInfo objects.
        pdf_pages: Dict mapping page_number to pdfplumber page.
        sheet_index: Parsed sheet index entries (may be empty).

    Returns:
        The same list of PageInfo objects with page_type set.
    """
    # Build a lookup from sheet code to inferred type.
    index_lookup: dict[str, PageType] = {}
    for entry in sheet_index:
        if entry.inferred_type is not None:
            index_lookup[entry.sheet_code.upper()] = (
                entry.inferred_type
            )

    # Pre-identify dense pages via fitz content stream size (instant).
    # Dense pages have so many vector objects that pdfplumber's
    # extract_text() hangs for minutes. We skip pdfplumber fallback
    # on these pages.
    dense_pages: set[int] = set()  # page_number set
    try:
        import fitz as pymupdf

        # Group pages by source file to avoid re-opening PDFs
        source_files: dict[str, list[PageInfo]] = {}
        for p in pages:
            key = str(p.source_path)
            source_files.setdefault(key, []).append(p)

        for src, src_pages in source_files.items():
            try:
                doc = pymupdf.open(src)
                for p in src_pages:
                    if p.pdf_page_index < len(doc):
                        stream_sz = len(
                            doc[p.pdf_page_index].read_contents()
                        )
                        if stream_sz > 10_000_000:
                            dense_pages.add(p.page_number)
                doc.close()
            except Exception:
                pass
    except ImportError:
        pass

    for page in pages:
        page_type = _classify_single(
            page,
            pdf_pages.get(page.page_number),
            index_lookup,
            skip_pdfplumber=(page.page_number in dense_pages),
        )
        page.page_type = page_type
        logger.debug(
            "Page %d (%s) classified as %s",
            page.page_number,
            page.sheet_code,
            page_type.value,
        )

    return pages


def _classify_single(
    page: PageInfo,
    pdfp_page: Any | None,
    index_lookup: dict[str, PageType],
    skip_pdfplumber: bool = False,
) -> PageType:
    """Classify a single page through the priority chain."""
    code_upper = (page.sheet_code or "").upper()

    # Priority 1: Sheet index hints
    if code_upper and code_upper in index_lookup:
        logger.debug(
            "Page %d: classified via sheet index → %s",
            page.page_number,
            index_lookup[code_upper].value,
        )
        return index_lookup[code_upper]

    # Priority 2: Title block content (most reliable self-description).
    # Try fitz first (fast on ALL pages including dense vector).
    result = _classify_title_block_fitz(
        page.source_path, page.pdf_page_index
    )
    if result is not None:
        return result

    # Fall back to pdfplumber title block (skipped for dense pages
    # where extract_text would hang for minutes).
    if pdfp_page is not None and not skip_pdfplumber:
        result = _classify_from_title_block(pdfp_page)
        if result is not None:
            return result

    # Also check the sheet title from the index.
    title_text = (page.sheet_title or "").lower()

    # Priority 3: Sheet code prefix rules
    if code_upper:
        result = _classify_by_prefix(code_upper, title_text)
        if result is not None:
            return result

    # Priority 4: Full-page content keyword scan
    if pdfp_page is not None and not skip_pdfplumber:
        result = _classify_by_content(pdfp_page)
        if result is not None:
            return result

    return PageType.OTHER


def _classify_by_prefix(
    code: str,
    title_hint: str,
) -> PageType | None:
    """Classify using sheet code prefix rules."""
    for pattern, default_type, disambiguators in _PREFIX_RULES:
        if pattern.match(code):
            # Check disambiguation keywords in the title.
            for keyword, alt_type in disambiguators.items():
                if keyword in title_hint:
                    return alt_type
            return default_type
    return None


def _classify_by_content(page: Any) -> PageType | None:
    """Classify by scanning the page text for keywords.

    Uses a two-pass approach:
    1. Check the TITLE BLOCK area (bottom-right) for the page's own
       title/description — this is the most reliable indicator.
    2. Fall back to full-page text scan if the title block didn't match.

    This prevents misclassification when a lighting plan page
    references "SEE SHEET xxx FOR LIGHT FIXTURE SCHEDULE".
    """
    # --- Pass 1: Title block classification ---
    title_type = _classify_from_title_block(page)
    if title_type is not None:
        return title_type

    # --- Pass 2: Full-page text scan ---
    try:
        text = page.extract_text() or ""
    except Exception:
        return None

    if not text:
        return None

    text_lower = text.lower()

    # Remove cross-reference notes that mention other pages' schedules.
    # These often span multiple lines, e.g.:
    #   "REFER TO SHEET FOR FE-10691-012 FOR PANEL BOARD
    #    SCHEDULE AND LIGHTING FIXTURE SCHEDULE."
    # Collapse newlines first so the regex can match across lines.
    import re
    text_collapsed = text_lower.replace("\n", " ")
    text_no_crossref = re.sub(
        r"(?:see|refer\s+to)\s+(?:sheet\s+)?(?:for\s+)?"
        r".{0,120}schedule[^.]*\.?",
        "",
        text_collapsed,
    )

    for keywords, page_type in _CONTENT_KEYWORDS:
        if any(kw in text_no_crossref for kw in keywords):
            return page_type

    return None


def _classify_title_block_fitz(
    source_path: Any,
    pdf_page_index: int,
) -> PageType | None:
    """Fast-path title block classification using PyMuPDF (fitz).

    Used to avoid pdfplumber's slow extract_text on pages with
    extreme vector density (millions of line objects).
    """
    try:
        import fitz as pymupdf
        doc = pymupdf.open(str(source_path))
        if pdf_page_index >= len(doc):
            doc.close()
            return None
        fitz_page = doc[pdf_page_index]
        rect = fitz_page.rect
        clip = pymupdf.Rect(
            rect.width * 0.55,
            rect.height * 0.85,
            rect.width,
            rect.height,
        )
        raw_text = fitz_page.get_text("text", clip=clip)
        doc.close()
    except Exception:
        return None

    title_text = " ".join((raw_text or "").lower().split())
    if not title_text:
        return None

    _TITLE_KEYWORDS_LOCAL: list[tuple[list[str], PageType]] = [
        (["demolition", "demo plan"], PageType.DEMOLITION_PLAN),
        (["site plan", "site layout", "photometric"], PageType.SITE_PLAN),
        (["cover sheet", "title sheet", "coversheet"], PageType.COVER),
        (["electrical symbols", "abbreviation", "legend"], PageType.SYMBOLS_LEGEND),
        (["lighting plan", "lighting layout"], PageType.LIGHTING_PLAN),
        (["luminaire schedule", "lighting schedule", "fixture schedule",
          "electrical schedules"], PageType.SCHEDULE),
        (["power plan", "power layout", "power &", "systems plan",
          "electrical plan"], PageType.POWER_PLAN),
        (["fire alarm"], PageType.FIRE_ALARM),
        (["detail"], PageType.DETAIL),
    ]

    for keywords, page_type in _TITLE_KEYWORDS_LOCAL:
        if any(kw in title_text for kw in keywords):
            return page_type

    return None


def _classify_from_title_block(page: Any) -> PageType | None:
    """Classify a page by its title block description.

    The title block (bottom-right ~25% of the page) contains the
    page's actual title. This is more reliable than full-page text
    which may contain cross-references to other pages.
    """
    # Use page.bbox for origin-aware coordinates — some PDFs have
    # non-zero origins (e.g., bbox starts at x=-1224).
    x0, y0, x1, y1 = page.bbox
    w = x1 - x0
    h = y1 - y0

    # Crop to title block area (bottom-right).
    # Use bottom 15% (not 20%) to avoid capturing sheet index listings
    # that may appear just above the title block on symbols/cover pages.
    bbox = (
        x0 + w * 0.55,
        y0 + h * 0.85,
        x1,
        y1,
    )
    try:
        cropped = page.within_bbox(bbox)
        raw_text = cropped.extract_text() or ""
        # Collapse newlines to spaces so multi-line titles
        # like "ELECTRICAL SITE\nPLAN" match "site plan".
        title_text = " ".join(raw_text.lower().split())
    except Exception:
        return None

    if not title_text:
        return None

    # Check title block text for page type keywords.
    # Use the same keyword list but check against the title specifically.
    # Important: check in priority order — demolition before lighting.
    _TITLE_KEYWORDS: list[tuple[list[str], PageType]] = [
        (["demolition", "demo plan"], PageType.DEMOLITION_PLAN),
        (
            ["site plan", "site layout", "photometric"],
            PageType.SITE_PLAN,
        ),
        (
            ["roof electrical plan", "electrical roof plan"],
            PageType.OTHER,
        ),
        (["cover sheet", "title sheet", "coversheet"], PageType.COVER),
        (
            ["electrical symbols", "abbreviation", "legend"],
            PageType.SYMBOLS_LEGEND,
        ),
        (
            [
                "panel schedule", "panelboard schedule",
            ],
            PageType.SCHEDULE,
        ),
        (
            ["security plan", "technology plan"],
            PageType.FIRE_ALARM,
        ),
        (["lighting plan", "lighting layout",
          "electrical lighting plan"], PageType.LIGHTING_PLAN),
        (
            [
                "luminaire schedule",
                "light fixture schedule",
                "lighting schedule",
                "fixture schedule",
                "electrical schedules",
            ],
            PageType.SCHEDULE,
        ),
        (
            ["enlarged electrical room", "electrical room plan"],
            PageType.OTHER,
        ),
        (
            [
                "power plan", "power layout", "power &",
                "systems plan", "electrical plan",
            ],
            PageType.POWER_PLAN,
        ),
        (["fire alarm"], PageType.FIRE_ALARM),
        (["riser diagram", "riser"], PageType.RISER),
        (["detail"], PageType.DETAIL),
    ]

    for keywords, page_type in _TITLE_KEYWORDS:
        if any(kw in title_text for kw in keywords):
            return page_type

    return None
