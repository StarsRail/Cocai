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


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential_jitter(initial=0.5, max=3),
    retry=retry_if_exception_type((httpx.TimeoutException, httpx.HTTPStatusError)),
)
async def illustrate_a_scene(
    scene_description: str = Field(description="a detailed description of the scene"),
) -> str:
    """
    Illustrate a scene based on the description.
    The player may prefer seeing a visual representation of the scene,
    so it may be a good idea to use this tool when you progress the story.
    """
    logger = logging.getLogger("illustrate_a_scene")
    base_url = os.environ.get("STABLE_DIFFUSION_API_URL", "http://127.0.0.1:7860")
    try:
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
            elements=[
                cl.Image(name=scene_description, display="inline", content=image)
            ],
        )
        await message.send()
        return "The illustrator has handed the player a drawing of the scene. You can continue."
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
    logger = logging.getLogger("set_illustration_url")
    async with ctx.store.edit_state() as ctx_state:
        user_visible_state: GameState = ctx_state.get("user-visible")
        user_visible_state.illustration_url = url
    try:
        broadcaster.publish({"type": "illustration", "url": url})
    except Exception as e:
        logger.error("Failed to publish updated illustration.", exc_info=e)
    return "Updated the illustration pane."


def build_tool_for_setting_illustration_url(ctx: Context) -> FunctionTool:
    return FunctionTool.from_defaults(
        partial(set_illustration_url, ctx),
        name="set_illustration_url",
        description="Set the current scene illustration by providing a URL.",
    )
