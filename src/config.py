"""Central application configuration for Cocai.

Provides a single dataclass `AppConfig` that captures all environment-driven
settings so they can be:
  * Unit tested without patching os.environ everywhere.
  * Potentially surfaced in a future GUI for live configuration.
  * Serialized (later) for persistence.

Environment precedence / notes:
  - LLM provider precedence: OPENAI_API_KEY > TOGETHER_AI_API_KEY > Ollama local.
  - Memory: DISABLE_MEMORY short-circuits; else MEM0_API_KEY selects cloud Mem0; else local Mem0; fallback to default Memory on error.
    - Feature flags use forgiving boolean parsing via `env_flag`.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

from utils import FALSY_STRINGS, TRUTHY_STRINGS


def env_flag(name: str, default: bool = True) -> bool:
    """
    Read a boolean flag from environment variables with a forgiving parser.

    - Truthy values (case-insensitive): 1, true, yes, y, on, t
    - Falsy values (case-insensitive): 0, false, no, n, off, f
    - Any other non-empty value defaults to False, and missing env var returns
      the provided default.

    This function is intentionally permissive to avoid surprises in
    container/CI environments where flags can be provided in varying forms.
    """
    raw = os.environ.get(name)
    if raw is None:
        return default
    val = str(raw).strip().lower()
    if val in TRUTHY_STRINGS:
        return True
    if val in FALSY_STRINGS:
        return False
    return False


@dataclass(slots=True)
class AppConfig:
    # LLM / Embeddings
    openai_api_key: str | None = None
    together_api_key: str | None = None
    ollama_base_url: str = "http://localhost:11434"
    ollama_llm_id: str = "gpt-oss:20b"
    ollama_embed_model_id: str = "nomic-embed-text:latest"

    # Retrieval / Module
    game_module_path: str = "game_modules/Clean-Up-Aisle-Four"
    should_preread_game_module: bool = False
    should_reuse_existing_index: bool = True

    # Memory
    disable_memory: bool = False
    mem0_api_key: str | None = None

    # Auto update features
    enable_auto_history_update: bool = True
    enable_auto_scene_update: bool = True

    # MinIO / Storage
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"

    # Stable Diffusion (optional)
    stable_diffusion_api_url: str = "http://127.0.0.1:7860"

    # Qdrant
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_collection: str = "game_module"

    @property
    def llm_provider(self) -> str:
        if self.openai_api_key:
            return "openai"
        if self.together_api_key:
            return "together"
        return "ollama"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> AppConfig:
        e = env or os.environ
        return cls(
            openai_api_key=e.get("OPENAI_API_KEY"),
            together_api_key=e.get("TOGETHER_AI_API_KEY"),
            ollama_base_url=e.get("OLLAMA_BASE_URL", "http://localhost:11434"),
            ollama_llm_id=e.get("OLLAMA_LLM_ID", "gpt-oss:20b"),
            ollama_embed_model_id=e.get(
                "OLLAMA_EMBED_MODEL_ID", "nomic-embed-text:latest"
            ),
            game_module_path=e.get(
                "GAME_MODULE_PATH", "game_modules/Clean-Up-Aisle-Four"
            ),
            should_preread_game_module=env_flag("SHOULD_PREREAD_GAME_MODULE", False),
            should_reuse_existing_index=env_flag("SHOULD_REUSE_EXISTING_INDEX", True),
            disable_memory=env_flag("DISABLE_MEMORY", False),
            mem0_api_key=e.get("MEM0_API_KEY"),
            enable_auto_history_update=env_flag("ENABLE_AUTO_HISTORY_UPDATE", True),
            enable_auto_scene_update=env_flag("ENABLE_AUTO_SCENE_UPDATE", True),
            minio_access_key=e.get("MINIO_ACCESS_KEY", "minioadmin"),
            minio_secret_key=e.get("MINIO_SECRET_KEY", "minioadmin"),
            stable_diffusion_api_url=e.get(
                "STABLE_DIFFUSION_API_URL", "http://127.0.0.1:7860"
            ),
            qdrant_host=e.get("QDRANT_HOST", "localhost"),
            qdrant_port=int(e.get("QDRANT_PORT", "6333")),
            qdrant_collection=e.get("QDRANT_COLLECTION", "game_module"),
        )
