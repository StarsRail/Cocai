"""
Helpers for auto-updating the left-pane History text based on agent memory and recent exchanges.
"""

from __future__ import annotations

import asyncio
import logging

from llama_index.core.memory import Memory
from llama_index.core.workflow import Context
from llama_index.memory.mem0 import Mem0Memory

from events import broadcaster
from state import GameState

from .async_panes_utils import build_transcript, format_transcript, llm_complete_text


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
    transcript = build_transcript(
        memory=memory,
        last_user_msg=last_user_msg,
        last_agent_msg=last_agent_msg,
    )
    if not transcript:
        logger.warning("No transcript found for history update.")
        return
    try:
        if await __should_update_history(transcript):
            read_only_user_visible_state: GameState = await ctx.store.get(
                "user-visible"
            )
            current_history = read_only_user_visible_state.history
            new_summary = await __summarize_story(transcript, current_history)
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
        logger.info("auto_history_update task was cancelled")
        raise
    except Exception as e:
        logger.error("Auto history update failed.", exc_info=e)


def __format_recent(transcript: list[dict[str, str]], k: int) -> str:
    return format_transcript(transcript, last_k=k)


async def __should_update_history(transcript: list[dict[str, str]]) -> bool:
    if not transcript:
        return False
    recent_text = __format_recent(transcript, k=6)
    prompt = (
        "You are monitoring a Call of Cthulhu session. Decide if the LATEST exchange materially advances the in-world story.\n"
        "Update the 'History' pane ONLY if there was story progression (e.g., scene changes, discoveries, NPC interactions, clues found, outcomes of actions/dice, travel/time skips, character creation results).\n"
        "Do NOT update for pure rules clarification, mechanics/Q&A, small talk, or UI/meta talk.\n\n"
        "Conversation (most recent last):\n"
        f"{recent_text}\n\n"
        "Answer strictly with YES or NO."
    )
    decision = await llm_complete_text(prompt)
    try:
        return decision.lower().startswith("y")
    except Exception:
        return False


async def __summarize_story(
    transcript: list[dict[str, str]], current_history: str
) -> str:
    recent_text = format_transcript(transcript, last_k=30)
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
        summary = await llm_complete_text(prompt)
        if len(summary) > 1500:
            summary = summary[:1500]
        return summary or current_history
    except asyncio.CancelledError:
        raise
    except Exception:
        return current_history
