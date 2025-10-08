"""
Auto-detect significant scene changes and update the center "scene pane" illustration in the UI.

This mirrors the non-blocking pattern used by history.py: after each exchange,
we decide quickly if the scene changed; if yes, we synthesize a concise visual
description, generate an image via Stable Diffusion WebUI (if available), save
it under public/illustrations, and publish the new URL to the UI.

All potentially blocking LLM calls run in a thread via asyncio.to_thread, and
network I/O for image generation uses httpx AsyncClient. Cancellation is
propagated promptly.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
from llama_index.core import Settings
from llama_index.core.memory import Memory
from llama_index.core.workflow import Context
from llama_index.memory.mem0 import Mem0Memory

from events import broadcaster
from state import GameState


async def update_scene_if_needed(
    ctx: Context,
    memory: Memory | Mem0Memory,
    last_user_msg: str | None = None,
    last_agent_msg: str | None = None,
) -> None:
    """
    Decide if the latest exchange implies a new scene/setting. If so, generate an
    illustration and update the UI pane. Runs entirely in the background and can be
    cancelled cooperatively.
    """
    logger = logging.getLogger("auto_scene_update")
    transcript = __get_transcript_from_memory(
        memory=memory, last_user_msg=last_user_msg, last_agent_msg=last_agent_msg
    )
    if not transcript:
        logger.debug("No transcript found for scene update.")
        return
    try:
        if not await __should_update_scene(transcript):
            return
        # Create a compact visual description first
        desc = await __describe_visual_scene(transcript)
        if not desc.strip():
            logger.debug("Scene change detected but no description produced; skipping.")
            return

        # Try to generate an image and save it; gracefully degrade if unavailable
        url = await __generate_scene_image(desc)
        if not url:
            # If generation failed, do not overwrite existing illustration
            logger.info("Scene image generation unavailable; skipping UI update.")
            return

        # Update state and notify UI
        async with ctx.store.edit_state() as ctx_state:
            user_visible_state: GameState = ctx_state.get("user-visible")
            user_visible_state.illustration_url = url
        try:
            broadcaster.publish({"type": "illustration", "url": url})
        except Exception as e:
            logger.error("Failed to publish updated illustration.", exc_info=e)
    except asyncio.CancelledError:
        logging.getLogger("auto_scene_update").info("auto_scene_update task cancelled")
        raise
    except Exception as e:
        logging.getLogger("auto_scene_update").error(
            "Auto scene update failed.", exc_info=e
        )


def __get_transcript_from_memory(
    memory: Memory | Mem0Memory,
    last_user_msg: str | None = None,
    last_agent_msg: str | None = None,
) -> list[dict[str, str]]:
    """Build a normalized transcript like history.py does, limited in size."""
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

    # Include the very latest turn if not yet persisted
    if last_user_msg:
        tail = "\n".join(x.get("content", "") for x in transcript[-2:])
        if last_user_msg not in tail:
            transcript.append({"role": "user", "content": last_user_msg})
        if last_agent_msg and last_agent_msg not in tail:
            transcript.append({"role": "agent", "content": last_agent_msg})

    if len(transcript) > 200:
        transcript = transcript[-200:]
    return transcript


def __format_transcript(transcript: list[dict[str, str]], last_k: int) -> str:
    recent = transcript[-last_k:] if last_k > 0 else transcript
    lines: list[str] = []
    for m in recent:
        role = m.get("role", "")
        prefix = "User" if role == "user" else "Keeper"
        lines.append(f"{prefix}: {m.get('content', '')}")
    return "\n".join(lines)


async def __should_update_scene(transcript: list[dict[str, str]]) -> bool:
    """
    Lightweight classifier: decide if the latest exchange changed the SCENE (location, setting, time of day, mood, entering/exiting a place, major shift in focus).
    Return True if a new illustration would help; False for rules chatter or minor talk.
    """
    if not transcript:
        return False
    recent_text = __format_transcript(transcript, last_k=8)
    prompt = (
        "You are monitoring a Call of Cthulhu session. Decide if the LATEST exchange significantly changes the scene/setting.\n"
        "Scene changes include: moving to a different location (inside/outside), entering a new room/building, time of day shifts, lighting/weather changes, a new set piece revealed, or a major shift in focus (e.g., basement to street, office to library).\n"
        "Do NOT trigger for rules clarifications, minor dialogue, or small detail tweaks.\n\n"
        "Conversation (most recent last):\n"
        f"{recent_text}\n\n"
        "Answer strictly with YES or NO."
    )
    try:
        decision: str = await asyncio.to_thread(
            lambda: Settings.llm.complete(prompt).text.strip().lower()
        )
        return decision.startswith("y")
    except asyncio.CancelledError:
        raise
    except Exception:
        return False


async def __describe_visual_scene(transcript: list[dict[str, str]]) -> str:
    """
    Produce a succinct, image-friendly description of the CURRENT scene suitable for a text-to-image model.
    Keep it concrete and avoid spoilers, 35-60 words.
    """
    recent_text = __format_transcript(transcript, last_k=20)
    prompt = (
        "From the recent Call of Cthulhu exchange, extract a concise, vivid description of the current physical scene for illustration.\n"
        "Focus on: location, key objects, lighting/weather, mood, and perspective (e.g., mid-shot). Avoid character names unless visually important. 35-60 words.\n\n"
        f"Recent conversation (most recent last):\n---\n{recent_text}\n---\n\n"
        "Now output only the description."
    )
    try:
        desc: str = await asyncio.to_thread(
            lambda: Settings.llm.complete(prompt).text.strip()
        )
        # light clamp
        return desc[:600]
    except asyncio.CancelledError:
        raise
    except Exception:
        return ""


async def __generate_scene_image(description: str) -> str | None:
    """
    Ask Stable Diffusion WebUI to render an image for the scene. Save to public/illustrations and return the public URL.
    If the service is unavailable, return None.
    """
    logger = logging.getLogger("auto_scene_update")
    base_url = os.environ.get("STABLE_DIFFUSION_API_URL", "http://127.0.0.1:7860")
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                f"{base_url.rstrip('/')}/sdapi/v1/txt2img",
                headers={
                    "accept": "application/json",
                    "Content-Type": "application/json",
                },
                json={
                    "prompt": description,
                    "negative_prompt": "",
                    "sampler": "DPM++ SDE",
                    "scheduler": "Automatic",
                    "steps": 6,
                    "cfg_scale": 2,
                    "width": 900,
                    "height": 300,
                },
            )
            resp.raise_for_status()
            data = resp.json()
        b64 = (data or {}).get("images", [None])[0]
        if not b64:
            return None
        image = base64.b64decode(b64)
        # Persist under public/illustrations
        out_dir = Path("public/illustrations")
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        fname = f"scene-{ts}.png"
        (out_dir / fname).write_bytes(image)
        return f"/public/illustrations/{fname}"
    except asyncio.CancelledError:
        raise
    except Exception as e:
        logger.warning("Illustration service unavailable; skipping image.", exc_info=e)
        return None
