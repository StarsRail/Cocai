"""
Helpers for auto-updating the left-pane History text based on agent memory and recent exchanges.
"""

import asyncio
import logging
from typing import Any, Dict, List

from llama_index.core import Settings
from llama_index.core.memory import Memory
from llama_index.core.workflow import Context
from llama_index.memory.mem0 import Mem0Memory

from events import broadcaster
from state import GameState


async def update_history_if_needed(
    ctx: Context,
    memory: Memory | Mem0Memory,
    last_user_msg: str | None = None,
    last_agent_msg: str | None = None,
):
    """
    Check if the latest exchange advanced the in-world story. If so, update the left-pane History text.
    """
    logger = logging.getLogger("auto_history_update")
    transcript: List[Dict[str, str]] = __get_transcript_from_memory(
        memory=memory,
        last_user_msg=last_user_msg,
        last_agent_msg=last_agent_msg,
    )
    if not transcript:
        logger.warning("No transcript found for history update.")
        return
    # Optionally update the History pane based on the latest exchange and overall story so far
    try:
        if await __should_update_history(transcript):
            read_only_user_visible_state: GameState = await ctx.store.get(
                "user-visible"
            )
            current_history = read_only_user_visible_state.history
            new_summary = await __summarize_story(transcript, current_history)
            # Update the user-visible state in the context.
            async with ctx.store.edit_state() as ctx_state:
                user_visible_state: GameState = ctx_state.get("user-visible")
                user_visible_state.history = new_summary
                try:
                    broadcaster.publish(
                        {"type": "history", "history": user_visible_state.history}
                    )
                except Exception as e:
                    logger.error("Failed to publish updated history.", exc_info=e)
    except asyncio.CancelledError:
        # Allow cooperative cancellation to propagate immediately
        logger.info("auto_history_update task was cancelled")
        raise
    except Exception as e:
        logger.error("Auto history update failed.", exc_info=e)


def __get_transcript_from_memory(
    memory: Memory | Mem0Memory,
    last_user_msg: str | None = None,
    last_agent_msg: str | None = None,
) -> List[Dict[str, str]]:
    """Build a user/agent transcript from the agent memory. Falls back to the latest exchange if not yet persisted."""
    raw: List[Any] = []
    try:
        raw = list(memory.get_all())  # type: ignore[attr-defined]
    except Exception:
        raw = []
    transcript: List[Dict[str, str]] = []
    for m in raw:
        # Try common shapes: object with attrs, or dict-like
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
        if r in ("user", "human"):  # normalize
            out_role = "user"
        else:
            out_role = "agent"  # assistant/ai/system/tool -> agent bucket
        transcript.append({"role": out_role, "content": str(content)})
    # If memory hasn't yet included the very last assistant turn, append the last exchange as a fallback.
    if last_user_msg:
        # Only append if the last user message content isn't already present as the last user entry
        if not transcript or transcript[-1]["role"] != "agent":
            # ambiguous ordering; append anyway to ensure recency
            pass
        # Check if the last content appears at the end
        tail = "\n".join(x.get("content", "") for x in transcript[-2:])
        if last_user_msg not in tail:
            transcript.append({"role": "user", "content": last_user_msg})
        if last_agent_msg and last_agent_msg not in tail:
            transcript.append({"role": "agent", "content": last_agent_msg})
    # Keep reasonable size
    if len(transcript) > 200:
        transcript = transcript[-200:]
    return transcript


def __format_transcript(
    transcript: List[Dict[str, str]], last_k: int | None = None
) -> str:
    if last_k is not None and last_k > 0:
        transcript = transcript[-last_k:]
    lines: List[str] = []
    for m in transcript:
        role = m.get("role", "")
        prefix = "User" if role == "user" else "Keeper"
        lines.append(f"{prefix}: {m.get('content', '')}")
    return "\n".join(lines)


async def __should_update_history(transcript: List[Dict[str, str]]) -> bool:
    """
    Lightweight classifier: decide whether the latest exchange advanced the in-world story.
    Returns True for scene progression, new clues/NPCs, outcomes, time/scene changes; False for pure rules/meta/clarifications.
    """
    if not transcript:
        return False
    # Consider only the last one or two turns for classification, but provide minimal context
    recent_text = __format_transcript(transcript, last_k=6)
    prompt = (
        "You are monitoring a Call of Cthulhu session. Decide if the LATEST exchange materially advances the in-world story.\n"
        "Update the 'History' pane ONLY if there was story progression (e.g., scene changes, discoveries, NPC interactions, clues found, outcomes of actions/dice, travel/time skips, character creation results).\n"
        "Do NOT update for pure rules clarification, mechanics/Q&A, small talk, or UI/meta talk.\n\n"
        "Conversation (most recent last):\n"
        f"{recent_text}\n\n"
        "Answer strictly with YES or NO."
    )
    try:
        # Run blocking LLM completion in a worker thread to avoid blocking the event loop
        decision: str = await asyncio.to_thread(
            lambda: Settings.llm.complete(prompt).text.strip().lower()
        )
        return decision.startswith("y")
    except asyncio.CancelledError:
        raise
    except Exception:
        return False


async def __summarize_story(
    transcript: List[Dict[str, str]], current_history: str
) -> str:
    """
    Summarize the story so far for the History pane. Uses the existing history as prior context plus recent turns.
    Keeps it concise and spoiler-free from the player's perspective.
    """
    # Provide existing summary and recent turns to keep token use reasonable
    recent_text = __format_transcript(transcript, last_k=30)
    prompt = (
        "You are the Keeper summarizing an ongoing Call of Cthulhu session for a left-pane 'History' box.\n"
        "Write a concise 120-180 word summary that reflects what the players/PCs know so far.\n"
        "Include: current location/situation, key NPCs encountered, clues discovered, notable events/outcomes, and open leads.\n"
        "Avoid spoilers beyond player knowledge. Prefer past tense or neutral narrative, no second-person instructions.\n\n"
        f"Existing excerpt (may be empty):\n---\n{current_history}\n---\n\n"
        f"Recent conversation (most recent last):\n---\n{recent_text}\n---\n\n"
        "Now produce ONLY the updated summary text."
    )
    try:
        # Run blocking LLM completion in a worker thread to avoid blocking the event loop
        summary: str = await asyncio.to_thread(
            lambda: Settings.llm.complete(prompt).text.strip()
        )
        # Basic clamp to avoid overly long outputs
        if len(summary) > 1500:
            summary = summary[:1500]
        return summary
    except asyncio.CancelledError:
        raise
    except Exception:
        # Fallback: keep existing history
        return current_history
