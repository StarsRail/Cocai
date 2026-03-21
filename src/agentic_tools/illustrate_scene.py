import base64
import logging
import os
from functools import partial

import chainlit as cl
import httpx
from llama_index.core.tools import FunctionTool
from llama_index.core.workflow import Context
from pydantic import Field
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from events import broadcaster
from state import GameState


def _extract_base64_from_data_url(data_url: str) -> bytes:
    """Extract and decode base64 from a data URL."""
    if data_url.startswith("data:"):
        # Format: data:image/png;base64,<base64_data>
        base64_part = data_url.split(",", 1)[1]
        return base64.b64decode(base64_part)
    else:
        # Assume it's raw base64
        return base64.b64decode(data_url)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential_jitter(initial=0.5, max=3),
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.HTTPStatusError)),
)
async def _illustrate_from_openrouter(
    scene_description: str,
    api_key: str,
) -> str:
    """Generate an image using OpenRouter API."""
    logger = logging.getLogger("_illustrate_from_openrouter")
    model = os.environ.get("OPENROUTER_IMG_GEN_LLM_ID", "sourceful/riverflow-v2-pro")
    logger.info(f"Using OpenRouter model: {model}")

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [
                    {
                        "role": "user",
                        "content": scene_description,
                    }
                ],
                "modalities": ["image"],
            },
        )
        response.raise_for_status()
        data = response.json()

    if not data.get("choices") or not data["choices"][0].get("message", {}).get(
        "images"
    ):
        raise ValueError("No images in OpenRouter response")

    image_data = _extract_base64_from_data_url(
        data["choices"][0]["message"]["images"][0]["image_url"]["url"]
    )
    message = cl.Message(
        content=scene_description,
        author="illustrate_a_scene",
        elements=[
            cl.Image(name=scene_description, display="inline", content=image_data)
        ],
    )
    await message.send()
    return "The illustrator has handed the player a drawing of the scene. You can continue."


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential_jitter(initial=0.5, max=3),
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.HTTPStatusError)),
)
async def _illustrate_from_stable_diffusion(scene_description: str) -> str:
    """Generate an image using Stable Diffusion API."""
    base_url = os.environ.get("STABLE_DIFFUSION_API_URL", "http://127.0.0.1:7860")

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{base_url.rstrip('/')}/sdapi/v1/txt2img",
            headers={
                "accept": "application/json",
                "Content-Type": "application/json",
            },
            json={
                "prompt": scene_description,
                "negative_prompt": "",
                "sampler": "DPM++ SDE",
                "scheduler": "Automatic",
                "steps": 6,
                "cfg_scale": 2,
                "width": 768,
                "height": 512,
            },
        )
        response.raise_for_status()
        data = response.json()

    image = base64.b64decode(data.get("images", [b""])[0])
    message = cl.Message(
        content=scene_description,
        author="illustrate_a_scene",
        elements=[cl.Image(name=scene_description, display="inline", content=image)],
    )
    await message.send()
    return "The illustrator has handed the player a drawing of the scene. You can continue."


async def illustrate_a_scene(
    scene_description: str = Field(description="a detailed description of the scene"),
) -> str:
    """
    Illustrate a scene based on the description.
    The player may prefer seeing a visual representation of the scene,
    so it may be a good idea to use this tool when you progress the story.

    Uses OpenRouter if OPENROUTER_API_KEY is available, otherwise falls back to Stable Diffusion.
    """
    logger = logging.getLogger("illustrate_a_scene")

    # Try OpenRouter first if API key is available
    openrouter_api_key = os.environ.get("OPENROUTER_API_KEY")
    if openrouter_api_key:
        logger.info("Attempting to illustrate scene using OpenRouter.")
        try:
            return await _illustrate_from_openrouter(
                scene_description, openrouter_api_key
            )
        except Exception as e:
            logger.warning(
                "OpenRouter illustration failed; falling back to Stable Diffusion.",
                exc_info=e,
            )

    # Fall back to Stable Diffusion
    try:
        logger.info("Attempting to illustrate scene using Stable Diffusion.")
        return await _illustrate_from_stable_diffusion(scene_description)
    except Exception as e:
        logger.warning(
            "Illustration service unavailable; skipping image generation.", exc_info=e
        )
        return "The illustrator is currently unavailable. Proceeding without an image."


async def set_illustration_url(
    ctx: Context,
    url: str = Field(description="Public URL to display in the Illustration pane"),
) -> str:
    """
    Set the current scene illustration by providing a URL (e.g. /public/.. or https://..).
    """
    async with ctx.store.edit_state() as ctx_state:
        user_visible_state: GameState = ctx_state.get("user-visible")
        user_visible_state.illustration_url = url
    broadcaster.publish(
        {"type": "illustration", "url": url}, context="set_illustration_url"
    )
    return "Updated the illustration pane."


def build_tool_for_setting_illustration_url(ctx: Context) -> FunctionTool:
    return FunctionTool.from_defaults(
        partial(set_illustration_url, ctx),
        name="set_illustration_url",
        description="Set the current scene illustration by providing a URL.",
    )
