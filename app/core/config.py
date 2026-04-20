"""Unified configuration for the CRM Agent application.

A single Settings class is shared across all agent modules.
Each agent sub-module imports settings from here — no per-agent config files.

Adding a new agent:
  No changes needed here.  Simply import settings from app.core.config in
  the new agent module.  If the agent requires unique settings (e.g. a
  module-specific timeout), add them as optional fields below.
"""

import os
from typing import Literal
from functools import lru_cache
from pydantic import Field
from pydantic_settings import BaseSettings
from dotenv import load_dotenv

load_dotenv(override=True)


class Settings(BaseSettings):
    """Application-wide settings for all CRM agents."""

    # ── LLM Provider ──────────────────────────────────────────────────────────
    llm_provider: Literal["openai", "ollama"] = "ollama"

    # ── OpenAI ────────────────────────────────────────────────────────────────
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"

    # ── Ollama ────────────────────────────────────────────────────────────────
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "gpt-oss:20b"

    # ── Database ──────────────────────────────────────────────────────────────
    db_dsn: str = "postgresql://postgres:aria@localhost:5434/crmdb"

    # ── Application ───────────────────────────────────────────────────────────
    debug: bool = True
    log_level: str = "INFO"

    # ── Server (unified crm_agent listens on a single port) ───────────────────
    # Individual agent zip files used 8003 / 8004.
    # The merged application uses one port; all agent endpoints are
    # available at /account-chat, /contact-chat, etc. on the same server.
    host: str = "0.0.0.0"
    port: int = 8000

    # ── Memory ────────────────────────────────────────────────────────────────
    # Number of previous conversation turns (user + assistant pairs) to retain
    # per session.  Set to 0 to disable memory (stateless mode).
    memory_window_size: int = 5

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        # Ensure Railway's dynamically injected environment variables take ultimate precedence
        if os.environ.get("DATABASE_URL"):
            self.db_dsn = os.environ.get("DATABASE_URL")
        elif os.environ.get("DB_DSN"):
            self.db_dsn = os.environ.get("DB_DSN")
            
        if os.environ.get("PORT"):
            self.port = int(os.environ.get("PORT"))

    @property
    def llm_model(self) -> str:
        return self.openai_model if self.llm_provider == "openai" else self.ollama_model

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
