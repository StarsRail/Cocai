## CoCai – AI agent working notes

Use this as the minimal, high-signal guide to be productive in this repo. Keep instructions concrete and aligned with how this code actually works.

### Big picture

- Web app: `fastapi` app in `server.py` mounts Chainlit at `/chat` with `mount_chainlit(app, target="main.py", path="/chat")`.
- Chat brain: `main.py` wires a LlamaIndex `FunctionAgent` with tools and memory, and streams tokens to Chainlit.
- Memory: Mem0 short‑term memory via Qdrant (local) or Mem0 Cloud. Fallback to LlamaIndex `Memory` if disabled or init fails.
- Observability: OpenTelemetry traces to Arize Phoenix (Docker) via `openinference` + `LlamaIndexInstrumentor`.
- Extras: Visual dice rolls via `/roll_dice` (Jinja template in `dice/`), optional Stable Diffusion Web UI for scene illustrations.

Data flow sketch

- User -> Chainlit UI (/chat) -> FunctionAgent -> tools (`tools.py`) -> external services (Qdrant, MinIO, Ollama, Tavily, SD) -> responses stream back over Chainlit.

### Run/dev workflow

- Easiest: `just serve-all` (tmuxinator panes: uvicorn at :8000, ollama, docker-compose for qdrant/minio/phoenix, optional SD UI).
- Manual: run `ollama serve`, `docker-compose up`, optional SD UI `./webui.sh --api`, then `just serve`.
- URLs: Chat `http://localhost:8000/chat`, Qdrant dashboard `http://localhost:6333/dashboard#/collections`, Phoenix `http://localhost:6006`.
- Python deps via `uv`; no explicit venv creation needed. Format with `just format` (ruff).

### Key conventions and patterns

- LLM selection precedence (in `set_up_llama_index()`): `OPENAI_API_KEY` -> `TOGETHER_AI_API_KEY` -> Ollama (OpenAI‑compatible). Embeddings via Ollama `nomic-embed-text` by default.
- Important: initialize LLMs/tools inside `@cl.on_chat_start`/session setup path, not module import time, so Phoenix traces attach to Agent Steps.
- System prompt: `prompts/system_prompt.md` + auto‑generated module summary (pre‑read using the module tool) -> final `system_prompt`.
- Module RAG: `ToolForConsultingTheModule` builds/loads Qdrant collection `game_module` from `GAME_MODULE_PATH` (defaults to `game_modules/Clean-Up-Aisle-Four`). Reuse controlled by `SHOULD_REUSE_EXISTING_INDEX`.
- Memory config (local): Mem0 uses Qdrant collection `cocai` and embedding dims 768. Ensure your embedding model matches (default `nomic-embed-text`). Set `DISABLE_MEMORY=1` to bypass Mem0.
- Chainlit storage: Data layer initialized in `utils.set_up_data_layer()` with SQLite file `.chainlit/data.db` and schema `.chainlit/schema.sql`, plus MinIO as storage backend for artifacts.
- Dice visual: `tools.roll_a_skill(ctx, ...)` saves `user_message_id`/`thread_id` in `Context` state (set in `main.handle_message_from_user`) and posts a `cl.Pdf` pointing to `/roll_dice?d10=...`.

### Adding a new tool (preferred pattern)

1. Implement a function (sync or async). If it needs Chainlit context, accept `Context` as first arg.
2. Define a pydantic model for inputs when helpful; then wrap with `FunctionTool.from_defaults(fn, fn_schema=YourModel)`.
3. Add to `all_tools` in `set_up_llama_index()` in `main.py`.
4. If the tool renders Chainlit elements replying to a user message, read `user_message_id` and `user_message_thread_id` from `ctx.store`.

Example references

- Simple stateless tool: `roll_a_dice`.
- Contextful + UI element: `roll_a_skill(ctx, ...)`.
- External HTTP call: `illustrate_a_scene` (Stable Diffusion API at :7860).
- RAG over module docs: `ToolForConsultingTheModule` (Qdrant + SimpleDirectoryReader).

### Environment variables you will actually use

- Models: `OPENAI_API_KEY`, `TOGETHER_AI_API_KEY`, `OLLAMA_BASE_URL`, `OLLAMA_LLM_ID`, `OLLAMA_EMBED_MODEL_ID`.
- Retrieval/memory: `GAME_MODULE_PATH`, `SHOULD_REUSE_EXISTING_INDEX`, `MEM0_API_KEY`, `DISABLE_MEMORY`.
- Storage: `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`.
- Tools: `TAVILY_API_KEY` (optional search).

### Gotchas and tips

- Pull models before first run: `ollama pull gpt-oss:20b` and `ollama pull nomic-embed-text`.
- Phoenix can be flaky locally; containerized Phoenix via docker-compose is the recommended path (see `docker-compose.yaml`).
- MinIO: start once, create access key in console (`:9001`), then set `MINIO_ACCESS_KEY`/`MINIO_SECRET_KEY` in `.env`.
- Dockerfile is a demo and may be outdated; prefer `just serve-all` on host.

### Where to look

- Core runtime: `main.py` (agent, tools wiring, memory, callbacks), `server.py` (FastAPI + Chainlit mount).
- Tools: `tools.py` (dice/skills, SD image, RAG module, character creation via `cochar`).
- Infra/config: `docker-compose.yaml`, `tmuxinator.yaml`, `justfile`, `pyproject.toml`.
- Prompts: `prompts/`.
