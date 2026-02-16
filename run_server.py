"""Run the Medina API server."""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure src/ is on the path
src = str(Path(__file__).resolve().parent / "src")
if src not in sys.path:
    sys.path.insert(0, src)

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "medina.api.main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        reload_dirs=[src],
    )
