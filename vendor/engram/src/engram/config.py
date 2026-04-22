"""Engram configuration."""

from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel, Field


def default_db_path() -> Path:
    explicit = os.environ.get("ENGRAM_DB_PATH")
    if explicit:
        return Path(explicit)

    data_dir = os.environ.get("ENGRAM_DATA_DIR")
    if data_dir:
        return Path(data_dir) / "memory.db"

    return Path.home() / ".engram" / "memory.db"


class EngramConfig(BaseModel):
    """Global configuration for an Engram instance."""

    db_path: Path = Field(
        default_factory=default_db_path,
    )
    storage_backend: str = "sqlite"
    enable_embeddings: bool = True
    embedding_provider: str = Field(
        default_factory=lambda: os.environ.get("ENGRAM_EMBEDDING_PROVIDER", "ollama"),
    )  # "ollama" (GPU), "local", or "fake" (CI/testing)
    embedding_model: str = "mxbai-embed-large"
    ollama_base_url: str = "http://localhost:11434"
    default_namespace: str = "default"
    auto_decay: bool = False
    decay_rate: float = Field(default=0.01, ge=0.0, le=1.0)
    api_key: str | None = None
