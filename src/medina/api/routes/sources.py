"""Routes for listing available data sources."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter

from medina.api.models import SourceItem

router = APIRouter(prefix="/api", tags=["sources"])

DATA_DIR = Path("data")


@router.get("/sources", response_model=list[SourceItem])
async def list_sources():
    """List all available projects in the data/ folder."""
    if not DATA_DIR.exists():
        return []

    sources = []
    for item in sorted(DATA_DIR.iterdir()):
        if item.name.startswith("."):
            continue
        if item.is_file() and item.suffix.lower() == ".pdf":
            sources.append(SourceItem(
                name=item.stem,
                path=str(item),
                type="file",
                size=item.stat().st_size,
            ))
        elif item.is_dir():
            sources.append(SourceItem(
                name=item.name,
                path=str(item),
                type="folder",
                size=None,
            ))
    return sources
