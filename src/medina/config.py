"""Configuration for Medina using pydantic-settings."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic_settings import BaseSettings

# Resolve project root so .env is found regardless of working directory.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_ENV_FILE = _PROJECT_ROOT / ".env"


class MedinaConfig(BaseSettings):
    """Application configuration loaded from environment variables."""

    model_config = {
        "env_prefix": "CDS_",
        "env_file": str(_ENV_FILE) if _ENV_FILE.exists() else ".env",
        "extra": "ignore",
    }

    anthropic_api_key: str = ""
    vision_model: str = "claude-sonnet-4-6"
    render_dpi: int = 300
    use_vision_counting: bool = False
    output_format: str = "both"  # "excel", "json", "both"
    qa_confidence_threshold: float = 0.95
    qa_fail_action: str = "warn"  # "warn", "error", "both"
    db_path: str = "output/medina.db"
    chroma_path: str = "output/chroma_db"

    # VLM provider settings
    vlm_provider: str = "anthropic"  # "anthropic", "gemini", "openrouter"
    vlm_fallback_provider: str = ""
    gemini_api_key: str = ""
    gemini_vision_model: str = "gemini-2.5-flash"
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"

    @property
    def has_vlm_key(self) -> bool:
        """Check if any VLM provider has an API key configured."""
        if self.vlm_provider == "openrouter":
            return bool(
                self.openrouter_api_key
                or os.environ.get("OPENROUTER_API_KEY")
            )
        if self.vlm_provider == "gemini":
            return bool(self.gemini_api_key)
        # Default: anthropic
        return bool(self.anthropic_api_key)

    # Auth / JWT settings
    jwt_secret_key: str = ""  # MEDINA_JWT_SECRET_KEY (auto-generated if empty)
    jwt_expiry_hours: int = 8  # MEDINA_JWT_EXPIRY_HOURS

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
