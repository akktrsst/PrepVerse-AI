from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Vertex AI / Gemini
    gcp_project: str = ""
    gcp_location: str = "global"
    gemini_model_lite: str = "gemini-2.5-flash-lite"
    gemini_model: str = "gemini-2.5-flash"
    gemini_model_pro: str = "gemini-2.5-pro"
    embedding_model: str = "gemini-embedding-001"

    # External data (ingestion)
    youtube_api_key: str = ""
    github_token: str = ""
    # On-demand topic refresh. Empty: run in a local background thread (dev).
    # Set to the Cloud Run Job name in production so the work runs outside the API.
    ingest_job_name: str = ""
    ingest_job_region: str = "asia-south1"

    # Firebase / storage. The web_* values are the public Firebase web config.
    firebase_project_id: str = ""
    firebase_web_api_key: str = ""
    firebase_auth_domain: str = ""
    firebase_app_id: str = ""
    store_backend: Literal["memory", "file", "firestore"] = "memory"
    local_data_path: str = ".data/store.json"  # STORE_BACKEND=file, relative to backend/
    auth_disabled: bool = False  # local dev only: every request is "dev-user"

    # Guardrails
    max_daily_llm_calls_per_user: int = 50
    cors_origins: list[str] = ["http://localhost:3000"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
