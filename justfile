serve-all:
    tmuxinator start -p tmuxinator.yaml
serve:
    # This is for development. For production, use `serve-all`, which uses command in `tmuxinator.yaml`.
    uv run uvicorn server:app --reload --app-dir src
run:
    uv run src/main.py
format:
    uv run ruff format
test:
    uv run pytest --cov=src/ ; uv run coverage-badge -f -o coverage.svg
