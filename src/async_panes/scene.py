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

import httpx
from llama_index.core.memory import Memory
from llama_index.core.workflow import Context
from llama_index.memory.mem0 import Mem0Memory

from events import broadcaster
from state import GameState

from .async_panes_utils import build_transcript, format_transcript, llm_complete_text


async def update_scene_if_needed(
    ctx: Context,
    memory: Memory | Mem0Memory,
    last_user_msg: str | None = None,
    last_agent_msg: str | None = None,
) -> None:
    logger = logging.getLogger("auto_scene_update")
    transcript = build_transcript(
        memory=memory, last_user_msg=last_user_msg, last_agent_msg=last_agent_msg
    )
    if not transcript:
        logger.debug("No transcript found for scene update.")
        return
    try:
        broadcaster.publish({"type": "scene_status", "phase": "evaluating"})
        should = await __should_update_scene(transcript)
        if not should:
            broadcaster.publish({"type": "scene_status", "phase": "unchanged"})
            return
        broadcaster.publish({"type": "scene_status", "phase": "describing"})
        desc = await __describe_visual_scene(transcript)
        if not desc.strip():
            logger.debug("Scene change detected but no description produced; skipping.")
            broadcaster.publish({"type": "scene_status", "phase": "unchanged"})
            return
        broadcaster.publish({"type": "scene_status", "phase": "imaging"})
        url = await __generate_scene_image(desc)
        if not url:
            logger.info("Scene image generation unavailable; skipping UI update.")
            broadcaster.publish({"type": "scene_status", "phase": "imaging_failed"})
            return
        async with ctx.store.edit_state() as ctx_state:
            user_visible_state: GameState = ctx_state.get("user-visible")
            user_visible_state.illustration_url = url
        try:
            broadcaster.publish({"type": "illustration", "url": url})
            broadcaster.publish({"type": "scene_status", "phase": "updated"})
        except Exception as e:
            logger.error("Failed to publish updated illustration.", exc_info=e)
    except asyncio.CancelledError:
        logging.getLogger("auto_scene_update").info("auto_scene_update task cancelled")
        try:
            broadcaster.publish({"type": "scene_status", "phase": "cancelled"})
        except Exception:
            pass
        raise
    except Exception as e:
        logging.getLogger("auto_scene_update").error(
            "Auto scene update failed.", exc_info=e
        )
        try:
            broadcaster.publish({"type": "scene_status", "phase": "error"})
        except Exception:
            pass


async def __should_update_scene(transcript: list[dict[str, str]]) -> bool:
    if not transcript:
        return False
    recent_text = format_transcript(transcript, last_k=8)
    prompt = (
        "You are monitoring a Call of Cthulhu session. Decide if the LATEST exchange significantly changes the scene/setting.\n"
        "Scene changes include: moving to a different location (inside/outside), entering a new room/building, time of day shifts, lighting/weather changes, a new set piece revealed, or a major shift in focus (e.g., basement to street, office to library).\n"
        "Do NOT trigger for rules clarifications, minor dialogue, or small detail tweaks.\n\n"
        "Conversation (most recent last):\n"
        f"{recent_text}\n\n"
        "Answer strictly with YES or NO."
    )
    decision = await llm_complete_text(prompt)
    try:
        return decision.lower().startswith("y")
    except Exception:
        return False


async def __describe_visual_scene(transcript: list[dict[str, str]]) -> str:
    recent_text = format_transcript(transcript, last_k=20)
    prompt = (
        "From the recent Call of Cthulhu exchange, extract a concise, vivid description of the current physical scene for illustration.\n"
        "Focus on: location, key objects, lighting/weather, mood, and perspective (e.g., mid-shot). Avoid character names unless visually important. 35-60 words.\n\n"
        f"Recent conversation (most recent last):\n---\n{recent_text}\n---\n\n"
        "Now output only the description."
    )
    try:
        desc = await llm_complete_text(prompt)
        return desc[:600]
    except asyncio.CancelledError:
        raise
    except Exception:
        return ""


async def __generate_scene_image(description: str) -> str | None:
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
