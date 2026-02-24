"""Runtime parameter registry and lookup."""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Parameter metadata registry
PARAM_REGISTRY: dict[str, dict[str, Any]] = {
    "font_size_tolerance_multi": {
        "default": 1.5,
        "type": "float",
        "min": 1.01,
        "max": 3.0,
        "description": "Font size tolerance multiplier for multi-char codes (range: modal/N to modal*N)",
        "agent": "count",
        "source_constant": "_FONT_SIZE_TOLERANCE",
    },
    "font_size_tolerance_single": {
        "default": 1.15,
        "type": "float",
        "min": 1.01,
        "max": 2.0,
        "description": "Font size tolerance multiplier for single-char codes (tighter, range: modal/N to modal*N)",
        "agent": "count",
        "source_constant": "_SHORT_CODE_FONT_TOLERANCE",
    },
    "isolation_distance": {
        "default": 15.0,
        "type": "float",
        "min": 5.0,
        "max": 50.0,
        "description": "Isolation gap (pt) — single-char codes must have no nearby characters",
        "agent": "count",
        "source_constant": "_ISO_GAP",
    },
    "dedup_distance": {
        "default": 70.0,
        "type": "float",
        "min": 20.0,
        "max": 200.0,
        "description": "De-duplication distance (pt) for merging nearby short-code matches",
        "agent": "count",
        "source_constant": "_SHORT_CODE_DEDUP_DIST",
    },
    "legend_col_x_frac": {
        "default": 0.85,
        "type": "float",
        "min": 0.5,
        "max": 1.0,
        "description": "Notes/keynotes column start (fraction of page width)",
        "agent": "count",
        "source_constant": "_LEGEND_COL_X_FRAC",
    },
    "title_block_frac": {
        "default": 0.80,
        "type": "float",
        "min": 0.5,
        "max": 1.0,
        "description": "Title block x-start (fraction of page width)",
        "agent": "count",
        "source_constant": "_TITLE_BLOCK_X_FRAC",
    },
    "schedule_render_dpi": {
        "default": 200,
        "type": "int",
        "min": 72,
        "max": 400,
        "description": "Max DPI for schedule page VLM rendering",
        "agent": "schedule",
    },
    "keynote_max_number": {
        "default": 20,
        "type": "int",
        "min": 5,
        "max": 99,
        "description": "Maximum keynote number (higher = more false positives)",
        "agent": "keynote",
        "source_constant": "_MAX_KEYNOTE_NUMBER",
    },
    "max_plausible_keynote_count": {
        "default": 10,
        "type": "int",
        "min": 3,
        "max": 50,
        "description": "Single keynote count threshold before VLM verification triggered",
        "agent": "keynote",
        "source_constant": "_MAX_PLAUSIBLE_KEYNOTE_COUNT",
    },
    "viewport_separation_threshold": {
        "default": 0.20,
        "type": "float",
        "min": 0.05,
        "max": 0.50,
        "description": "Minimum horizontal separation between viewport centers (fraction)",
        "agent": "search",
    },
    "qa_confidence_threshold": {
        "default": 0.95,
        "type": "float",
        "min": 0.5,
        "max": 1.0,
        "description": "Minimum confidence score to pass QA",
        "agent": "qa",
    },
    "use_vision_counting": {
        "default": False,
        "type": "bool",
        "description": "Use Claude Vision API for fixture counting (slower, more accurate for short codes)",
        "agent": "count",
    },
    "render_dpi": {
        "default": 300,
        "type": "int",
        "min": 72,
        "max": 600,
        "description": "Default DPI for page rendering",
        "agent": "all",
    },
    "vision_count_dpi": {
        "default": 150,
        "type": "int",
        "min": 72,
        "max": 300,
        "description": "DPI for vision-based fixture counting",
        "agent": "count",
    },
}


def get_effective_params(
    source_key: str = "",
    project_id: str = "",
) -> dict[str, Any]:
    """Get merged parameters: defaults -> global -> source_key -> project_id.

    Each layer overrides the previous.
    """
    # Start with defaults
    params = {k: v["default"] for k, v in PARAM_REGISTRY.items()}

    # Try DB overrides
    try:
        from medina.db import repositories as repo

        # Global overrides
        global_params = repo.get_params(scope="global")
        params.update(global_params)

        # Source-level overrides
        if source_key:
            source_params = repo.get_params(scope="source_key", scope_key=source_key)
            params.update(source_params)

        # Project-level overrides
        if project_id:
            project_params = repo.get_params(scope="project_id", scope_key=project_id)
            params.update(project_params)
    except Exception as e:
        logger.debug("DB param lookup failed (using defaults): %s", e)

    return params


def get_param(
    key: str,
    source_key: str = "",
    project_id: str = "",
) -> Any:
    """Get a single parameter value with full override chain."""
    params = get_effective_params(source_key, project_id)
    if key in params:
        return params[key]
    # Fall back to registry default
    if key in PARAM_REGISTRY:
        return PARAM_REGISTRY[key]["default"]
    raise KeyError(f"Unknown parameter: {key}")


def validate_param(key: str, value: Any) -> Any:
    """Validate and coerce a parameter value against registry metadata."""
    if key not in PARAM_REGISTRY:
        raise KeyError(f"Unknown parameter: {key}")
    meta = PARAM_REGISTRY[key]
    param_type = meta.get("type", "str")

    if param_type == "float":
        value = float(value)
        if "min" in meta and value < meta["min"]:
            raise ValueError(f"{key} must be >= {meta['min']}")
        if "max" in meta and value > meta["max"]:
            raise ValueError(f"{key} must be <= {meta['max']}")
    elif param_type == "int":
        value = int(value)
        if "min" in meta and value < meta["min"]:
            raise ValueError(f"{key} must be >= {meta['min']}")
        if "max" in meta and value > meta["max"]:
            raise ValueError(f"{key} must be <= {meta['max']}")
    elif param_type == "bool":
        if isinstance(value, str):
            value = value.lower() in ("true", "1", "yes")
        value = bool(value)

    return value
