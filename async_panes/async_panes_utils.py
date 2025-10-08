"""
Shared utilities for non-blocking pane updaters (history/scene).

Provides helpers to:
- Build a normalized transcript from Memory/Mem0Memory plus last messages
- Format a transcript to concise text
- Run LLM completions off the event loop
"""

from __future__ import annotations

import asyncio
from typing import Any

from llama_index.core import Settings


def build_transcript(
    memory: Any,
    last_user_msg: str | None = None,
    last_agent_msg: str | None = None,
    max_len: int = 200,
) -> list[dict[str, str]]:
    """Build a user/agent transcript from memory, appending the latest turn if not yet persisted.

    Output shape: list of {"role": "user"|"agent", "content": str}
    """
    raw: list[Any] = []
    try:
        raw = list(memory.get_all())  # type: ignore[attr-defined]
    except Exception:
        raw = []
    transcript: list[dict[str, str]] = []
    for m in raw:
        role = None
        content = None
        try:
            role = getattr(m, "role", None)
            content = getattr(m, "content", None)
        except Exception:
            pass
        if role is None or content is None:
            if isinstance(m, dict):
                role = m.get("role")
                content = m.get("content")
        if not content:
            continue
        r = str(role).lower() if role is not None else "assistant"
        out_role = "user" if r in ("user", "human") else "agent"
        transcript.append({"role": out_role, "content": str(content)})

    # If memory hasn't captured the very last turn, add it as a fallback
    if last_user_msg:
        tail = "\n".join(x.get("content", "") for x in transcript[-2:])
        if last_user_msg not in tail:
            transcript.append({"role": "user", "content": last_user_msg})
        if last_agent_msg and last_agent_msg not in tail:
            transcript.append({"role": "agent", "content": last_agent_msg})

    if max_len and len(transcript) > max_len:
        transcript = transcript[-max_len:]
    return transcript


def format_transcript(
    transcript: list[dict[str, str]], last_k: int | None = None
) -> str:
    """Render transcript to plain text with User/Keeper prefixes."""
    if last_k is not None and last_k > 0:
        transcript = transcript[-last_k:]
    lines: list[str] = []
    for m in transcript:
        role = m.get("role", "")
        prefix = "User" if role == "user" else "Keeper"
        lines.append(f"{prefix}: {m.get('content', '')}")
    return "\n".join(lines)


async def llm_complete_text(prompt: str) -> str:
    """Run a single-shot completion via Settings.llm in a worker thread.

    Returns the response text stripped; empty string on failure.
    """
    try:
        return await asyncio.to_thread(
            lambda: Settings.llm.complete(prompt).text.strip()
        )
    except asyncio.CancelledError:
        raise
    except Exception:
        return ""
