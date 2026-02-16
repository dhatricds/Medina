"""Routes for loading demo data."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api", tags=["demo"])

DEMO_DIR = Path("demo_data")


@router.get("/demo/{name}")
async def get_demo(name: str):
    """Load demo JSON data by name."""
    # Map short names to file names
    name_map = {
        "hcmc": "hcmc_inventory.json",
        "anoka": "anoka_inventory.json",
    }

    filename = name_map.get(name)
    if not filename:
        raise HTTPException(status_code=404, detail=f"Demo '{name}' not found")

    filepath = DEMO_DIR / filename
    if not filepath.exists():
        raise HTTPException(status_code=404, detail=f"Demo file not found: {filepath}")

    with open(filepath) as f:
        return json.load(f)
