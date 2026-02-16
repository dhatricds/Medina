"""Configuration for Medina using pydantic-settings."""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings

# Resolve project root so .env is found regardless of working directory.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_ENV_FILE = _PROJECT_ROOT / ".env"


class MedinaConfig(BaseSettings):
    """Application configuration loaded from environment variables."""

    model_config = {
        "env_prefix": "MEDINA_",
        "env_file": str(_ENV_FILE) if _ENV_FILE.exists() else ".env",
        "extra": "ignore",
    }

    anthropic_api_key: str = ""
    vision_model: str = "claude-opus-4-6"
    render_dpi: int = 300
    use_vision_counting: bool = False
    output_format: str = "both"  # "excel", "json", "both"
    qa_confidence_threshold: float = 0.95
    qa_fail_action: str = "warn"  # "warn", "error", "both"

    schedule_include_keywords: list[str] = [
        "luminaire schedule",
        "light fixture schedule",
        "lighting schedule",
        "fixture schedule",
    ]
    schedule_exclude_keywords: list[str] = [
        "panel schedule",
        "motor schedule",
        "equipment schedule",
        "floorbox",
        "poke thru",
    ]


def get_config() -> MedinaConfig:
    """Load configuration from environment."""
    return MedinaConfig()
