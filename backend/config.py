from __future__ import annotations
"""
Central configuration module for SynthSense.
All environment variables and application constants are defined here.
Never import secrets directly — always use the `settings` singleton.
"""
from functools import lru_cache
from pathlib import Path
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve .env relative to this file so it works regardless of cwd
_ENV_FILE = Path(__file__).parent.parent / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_ENV_FILE), case_sensitive=False, extra="ignore")

    # ── LLM ──────────────────────────────────────────────────────────────────
    groq_api_key: str
    groq_model: str = "llama-3.1-8b-instant"
    groq_temperature: float = 0.2

    # ── HuggingFace ───────────────────────────────────────────────────────────
    huggingface_api_key: str
    hf_vision_model: str = "llava-hf/llava-1.5-7b-hf"
    hf_embedding_model: str = "BAAI/bge-small-en"
    hf_api_base: str = "https://api-inference.huggingface.co/models"

    # ── Supabase ──────────────────────────────────────────────────────────────
    supabase_url: str
    supabase_key: str

    # ── Upstash Redis ─────────────────────────────────────────────────────────
    upstash_redis_rest_url: str
    upstash_redis_rest_token: str

    # ── LangSmith ─────────────────────────────────────────────────────────────
    langchain_api_key: str
    langchain_tracing_v2: bool = True
    langchain_project: str = "synthsense"

    # ── Application ───────────────────────────────────────────────────────────
    app_title: str = "SynthSense"
    app_version: str = "1.0.0"
    cors_origins: list[str] = ["http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:3001", "http://127.0.0.1:3001"]
    log_level: str = "INFO"

    # ── Cache ─────────────────────────────────────────────────────────────────
    image_cache_ttl: int = 86400          # 24 hours in seconds
    cache_key_prefix: str = "synthsense"

    # ── Embeddings ────────────────────────────────────────────────────────────
    embedding_dim: int = 384              # BAAI/bge-small-en output dimension

    # ── RAG retrieval ─────────────────────────────────────────────────────────
    top_k_incidents: int = 5
    top_k_runbooks: int = 5
    similarity_threshold: float = 0.3

    # ── Eval ──────────────────────────────────────────────────────────────────
    eval_every_n_incidents: int = 10
    evals_file: str = "evals.json"
    synthetic_incidents_file: str = "synthetic_incidents.json"

    # ── Retry config ──────────────────────────────────────────────────────────
    max_retries: int = 3
    retry_base_delay: float = 2.0

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors(cls, v: str | list) -> list[str]:
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",")]
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

# Severity levels ordered by urgency
SEVERITY_LEVELS = ["critical", "high", "medium", "low"]

SEVERITY_COLORS = {
    "critical": "red",
    "high": "orange",
    "medium": "yellow",
    "low": "green",
}

# Incident categories for synthetic data generation
INCIDENT_CATEGORIES = [
    "Database outage",
    "Memory leak",
    "API timeout",
    "Deployment failure",
    "Certificate expiry",
]
