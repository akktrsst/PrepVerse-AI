"""Single entry point for every Gemini call.

Uses the google-genai SDK with vertexai=True so usage bills to the GCP project
(and its credit). Locally: `gcloud auth application-default login`. On Cloud
Run the service account needs the Vertex AI User role.
"""

import logging
from collections.abc import Iterator
from functools import cached_property
from typing import Literal, TypeVar

from google import genai
from google.genai import errors, types
from pydantic import BaseModel, ValidationError

from .config import Settings

log = logging.getLogger(__name__)

Tier = Literal["lite", "std", "pro"]
T = TypeVar("T", bound=BaseModel)

# Thinking tokens bill at output rates: off for the cheap tiers. Pro models
# can't disable thinking, so they keep the model's dynamic default.
DEFAULT_THINKING_BUDGET: dict[Tier, int | None] = {"lite": 0, "std": 0, "pro": None}

# Firestore vector search caps embeddings at 2048 dims; gemini-embedding-001
# defaults to 3072, so always request a smaller size.
EMBEDDING_DIM = 768


class LLMError(RuntimeError):
    """The model call failed or returned output we couldn't use."""


class LLM:
    def __init__(self, settings: Settings):
        self._settings = settings
        self.models: dict[Tier, str] = {
            "lite": settings.gemini_model_lite,
            "std": settings.gemini_model,
            "pro": settings.gemini_model_pro,
        }

    @cached_property
    def client(self) -> genai.Client:
        # Lazy so the app (and tests) can start without GCP credentials.
        return genai.Client(
            vertexai=True,
            project=self._settings.gcp_project or None,
            location=self._settings.gcp_location,
        )

    def generate(
        self,
        prompt: str,
        *,
        tier: Tier = "std",
        system: str | None = None,
        temperature: float = 0.4,
        thinking_budget: int | None = None,
        feature: str = "unknown",
    ) -> str:
        config = self._config(tier, system, temperature, thinking_budget)
        return self._call(prompt, tier, config, feature).text or ""

    def generate_structured(
        self,
        prompt: str,
        schema: type[T],
        *,
        tier: Tier = "std",
        system: str | None = None,
        temperature: float = 0.4,
        thinking_budget: int | None = None,
        feature: str = "unknown",
        low_media_resolution: bool = False,
    ) -> T:
        """`prompt` may be a string or a list of parts (e.g. a YouTube URL part + text)."""
        config = self._config(tier, system, temperature, thinking_budget, schema)
        if low_media_resolution:
            config.media_resolution = types.MediaResolution.MEDIA_RESOLUTION_LOW
        resp = self._call(prompt, tier, config, feature)
        if isinstance(resp.parsed, schema):
            return resp.parsed
        try:
            return schema.model_validate_json(resp.text or "")
        except ValidationError as e:
            raise LLMError(f"{feature}: model output did not match {schema.__name__}") from e

    def stream(
        self,
        prompt,
        *,
        tier: Tier = "std",
        system: str | None = None,
        temperature: float = 0.4,
        thinking_budget: int | None = None,
        feature: str = "unknown",
    ) -> Iterator[str]:
        """Yield text chunks as the model produces them."""
        model = self.models[tier]
        config = self._config(tier, system, temperature, thinking_budget)
        usage = None
        try:
            for chunk in self.client.models.generate_content_stream(model=model, contents=prompt, config=config):
                usage = chunk.usage_metadata or usage
                if chunk.text:
                    yield chunk.text
        except errors.APIError as e:
            raise LLMError(f"{feature}: {model} stream failed: {e}") from e
        if usage:
            log.info(
                "llm feature=%s model=%s in=%s out=%s thinking=%s stream=1",
                feature, model, usage.prompt_token_count, usage.candidates_token_count, usage.thoughts_token_count,
            )

    def embed(self, texts: list[str], task_type: str = "RETRIEVAL_DOCUMENT") -> list[list[float]]:
        try:
            resp = self.client.models.embed_content(
                model=self._settings.embedding_model,
                contents=texts,
                config=types.EmbedContentConfig(task_type=task_type, output_dimensionality=EMBEDDING_DIM),
            )
        except errors.APIError as e:
            raise LLMError(f"embed failed: {e}") from e
        return [e.values for e in resp.embeddings]

    def _config(self, tier, system, temperature, thinking_budget, schema=None) -> types.GenerateContentConfig:
        budget = DEFAULT_THINKING_BUDGET[tier] if thinking_budget is None else thinking_budget
        return types.GenerateContentConfig(
            system_instruction=system,
            temperature=temperature,
            thinking_config=types.ThinkingConfig(thinking_budget=budget) if budget is not None else None,
            response_mime_type="application/json" if schema else None,
            response_schema=schema,
        )

    def _call(self, prompt, tier: Tier, config, feature: str) -> types.GenerateContentResponse:
        model = self.models[tier]
        try:
            resp = self.client.models.generate_content(model=model, contents=prompt, config=config)
        except errors.APIError as e:
            raise LLMError(f"{feature}: {model} call failed: {e}") from e
        if u := resp.usage_metadata:
            log.info(
                "llm feature=%s model=%s in=%s out=%s thinking=%s",
                feature, model, u.prompt_token_count, u.candidates_token_count, u.thoughts_token_count,
            )
        return resp
