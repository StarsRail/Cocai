serve-all:
    tmuxinator start -p tmuxinator.yaml
serve:
    uv run uvicorn server:app --reload
run:
    uv run main.py
format:
    uv run ruff format
