# Application Configuration (AppConfig)

Runtime settings are centralized in `src/config.py` via the `AppConfig` dataclass. This replaces ad‑hoc `os.environ.get()` calls and makes configuration testable and future‑GUI friendly.

## Goals

- Easier unit testing (`AppConfig.from_env(custom_mapping)`).
- Single source of truth for future GUI / admin panel.
- Explicit precedence: LLM provider (OpenAI > Together > Ollama); memory (disable flag > cloud Mem0 > local Mem0 > fallback default memory).

## Key Fields (Excerpt)

| Concern | Fields |
|---------|--------|
| LLM provider | `openai_api_key`, `together_api_key`, `ollama_llm_id`, `ollama_base_url` |
| Embeddings | `ollama_embed_model_id` |
| Module RAG | `game_module_path`, `should_preread_game_module`, `should_reuse_existing_index` |
| Memory | `disable_memory`, `mem0_api_key` |
| Auto updates | `enable_auto_history_update`, `enable_auto_scene_update` |
| Storage / MinIO | `minio_access_key`, `minio_secret_key` |
| Vector DB (Qdrant) | `qdrant_host`, `qdrant_port`, `qdrant_collection` |
| Stable Diffusion | `stable_diffusion_api_url` |

## Usage in `main.py`

```python
from config import AppConfig

cfg = AppConfig.from_env()
system_prompt = set_up_llama_index(cfg)
memory = __prepare_memory(key, cfg)
```

## Adding a New Config Value

1. Add the dataclass field with a sensible default.
2. Extend `AppConfig.from_env` to read the env var.
3. Add or update a test in `tests/test_config.py`.

## Future GUI Idea

Expose a REST or Chainlit settings pane:

- `GET /config` -> serialize `asdict(AppConfig.from_env())`.
- `PATCH /config` -> write updates to a managed `.env.local` file which is loaded before `from_env`.

## Testing Strategy

Unit tests assert:

- Provider precedence.
- Boolean flag parsing via shared `env_flag`.
- Defaults when variables absent.

Coverage for `config.py` should remain high (aim ≥90%).
