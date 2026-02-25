"""Unified VLM client — dispatches to Anthropic or Google Gemini."""

from __future__ import annotations

import base64
import logging

from medina.config import MedinaConfig, get_config
from medina.exceptions import VisionAPIError

logger = logging.getLogger(__name__)


class VlmClient:
    """Provider-agnostic VLM client for vision queries."""

    def __init__(self, provider: str, api_key: str, model: str) -> None:
        self.provider = provider
        self.api_key = api_key
        self.model = model

    def vision_query(
        self,
        images: list[bytes],
        prompt: str,
        max_tokens: int = 4000,
        temperature: float | None = None,
    ) -> str:
        """Send images + prompt to the VLM provider, return response text.

        Args:
            images: List of PNG image bytes (1 or more).
            prompt: Text prompt to send alongside images.
            max_tokens: Maximum tokens in the response.
            temperature: Sampling temperature (None = provider default).

        Returns:
            Response text string from the VLM.

        Raises:
            VisionAPIError: If the API call fails.
        """
        if self.provider == "gemini":
            return self._query_gemini(images, prompt, max_tokens, temperature)
        return self._query_anthropic(images, prompt, max_tokens, temperature)

    def _query_anthropic(
        self,
        images: list[bytes],
        prompt: str,
        max_tokens: int,
        temperature: float | None,
    ) -> str:
        try:
            from anthropic import Anthropic
        except ImportError as exc:
            raise VisionAPIError(
                "anthropic package not installed. Run: pip install anthropic"
            ) from exc

        content: list[dict] = []
        for img in images:
            encoded = base64.b64encode(img).decode()
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": encoded,
                },
            })
        content.append({"type": "text", "text": prompt})

        kwargs: dict = {
            "model": self.model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": content}],
        }
        if temperature is not None:
            kwargs["temperature"] = temperature

        try:
            client = Anthropic(api_key=self.api_key)
            message = client.messages.create(**kwargs)
        except Exception as exc:
            raise VisionAPIError(f"Anthropic VLM call failed: {exc}") from exc

        response_text = ""
        for block in message.content:
            if hasattr(block, "text"):
                response_text += block.text
        return response_text

    def _query_gemini(
        self,
        images: list[bytes],
        prompt: str,
        max_tokens: int,
        temperature: float | None,
    ) -> str:
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise VisionAPIError(
                "google-genai package not installed. "
                "Run: pip install google-genai"
            ) from exc

        contents: list = []
        for img in images:
            contents.append(
                types.Part.from_bytes(data=img, mime_type="image/png")
            )
        contents.append(prompt)

        gen_kwargs: dict = {"max_output_tokens": max_tokens}
        if temperature is not None:
            gen_kwargs["temperature"] = temperature
        gen_config = types.GenerateContentConfig(**gen_kwargs)

        try:
            client = genai.Client(api_key=self.api_key)
            response = client.models.generate_content(
                model=self.model,
                contents=contents,
                config=gen_config,
            )
        except Exception as exc:
            raise VisionAPIError(f"Gemini VLM call failed: {exc}") from exc

        return response.text or ""


def _build_client(provider: str, config: MedinaConfig) -> VlmClient:
    """Build a VlmClient for a specific provider.

    Uses the provider-appropriate model name:
    - Anthropic: ``config.vision_model`` (default ``claude-sonnet-4-6``)
    - Gemini: ``config.gemini_vision_model`` (default ``gemini-2.5-flash``)
    """
    if provider == "gemini":
        if not config.gemini_api_key:
            raise VisionAPIError(
                "Gemini API key not configured. "
                "Set MEDINA_GEMINI_API_KEY in environment or .env file."
            )
        return VlmClient(
            provider="gemini",
            api_key=config.gemini_api_key,
            model=config.gemini_vision_model,
        )

    # Default: Anthropic
    if not config.anthropic_api_key:
        raise VisionAPIError(
            "Anthropic API key not configured for VLM. "
            "Set MEDINA_ANTHROPIC_API_KEY in environment or .env file."
        )
    return VlmClient(
        provider="anthropic",
        api_key=config.anthropic_api_key,
        model=config.vision_model,
    )


def get_vlm_client(config: MedinaConfig | None = None) -> VlmClient:
    """Create the primary VlmClient from configuration."""
    if config is None:
        config = get_config()
    return _build_client(config.vlm_provider.lower(), config)


def get_fallback_vlm_client(config: MedinaConfig | None = None) -> VlmClient | None:
    """Create a fallback VlmClient if a different provider is configured.

    Returns None if no fallback is available (same provider or missing key).
    """
    if config is None:
        config = get_config()

    primary = config.vlm_provider.lower()
    fallback = config.vlm_fallback_provider.lower()

    if fallback == primary:
        return None

    try:
        return _build_client(fallback, config)
    except VisionAPIError:
        return None
