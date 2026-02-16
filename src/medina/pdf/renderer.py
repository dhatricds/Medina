"""PDF page rendering to images for vision API processing."""

from __future__ import annotations

import io
import logging
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image

logger = logging.getLogger(__name__)


def render_page_to_image(
    source_path: Path | str,
    page_index: int,
    dpi: int = 300,
) -> bytes:
    """Render a specific PDF page to PNG bytes at given DPI.

    Args:
        source_path: Path to the PDF file.
        page_index: Zero-based page index within the PDF.
        dpi: Resolution for rendering. Defaults to 300.

    Returns:
        PNG image data as bytes.

    Raises:
        RuntimeError: If rendering fails.
    """
    source_path = Path(source_path)
    logger.debug(
        "Rendering page %d of %s at %d DPI",
        page_index,
        source_path.name,
        dpi,
    )

    try:
        doc = fitz.open(str(source_path))
    except Exception as exc:
        raise RuntimeError(
            f"Failed to open PDF for rendering: "
            f"{source_path}: {exc}"
        ) from exc

    try:
        if page_index < 0 or page_index >= len(doc):
            raise RuntimeError(
                f"Page index {page_index} out of range for "
                f"{source_path.name} ({len(doc)} pages)"
            )

        page = doc[page_index]
        zoom = dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)
        pixmap = page.get_pixmap(matrix=matrix, alpha=False)

        return pixmap.tobytes(output="png")
    finally:
        doc.close()


def render_page_to_pil(
    source_path: Path | str,
    page_index: int,
    dpi: int = 300,
) -> Image.Image:
    """Render a specific PDF page to a PIL Image.

    Args:
        source_path: Path to the PDF file.
        page_index: Zero-based page index within the PDF.
        dpi: Resolution for rendering. Defaults to 300.

    Returns:
        PIL Image in RGB mode.

    Raises:
        RuntimeError: If rendering fails.
    """
    png_bytes = render_page_to_image(source_path, page_index, dpi)
    return Image.open(io.BytesIO(png_bytes)).convert("RGB")
