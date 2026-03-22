import logging
from functools import partial

import chainlit as cl
from llama_index.core.tools import FunctionTool
from llama_index.core.workflow import Context
from pydantic import Field

from game_state.data_models import GameState
from game_state.load_and_save import save_game_state

from .image_generation import generate_image_with_cache


async def illustrate_a_scene(
    scene_description: str = Field(description="a detailed description of the scene"),
) -> str:
    """
    Illustrate a scene based on the description.
    The player may prefer seeing a visual representation of the scene,
    so it may be a good idea to use this tool when you progress the story.

    Uses cached images when available (semantic similarity search via Qdrant).
    Falls back to OpenRouter if API key available, then Stable Diffusion.
    """
    logger = logging.getLogger("illustrate_a_scene")

    image_bytes = await generate_image_with_cache(
        scene_description, width=768, height=512
    )
    if not image_bytes:
        logger.warning("Image generation unavailable; skipping.")
        return "The illustrator is currently unavailable. Proceeding without an image."

    message = cl.Message(
        content=scene_description,
        author="illustrate_a_scene",
        elements=[
            cl.Image(name=scene_description, display="inline", content=image_bytes)
        ],
    )
    await message.send()
    return "The illustrator has handed the player a drawing of the scene. You can continue."


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
    await cl.send_window_message({"type": "illustration", "url": url})
    # Persist the updated game state
    await save_game_state(user_visible_state)
    return "Updated the illustration pane."


def build_tool_for_setting_illustration_url(ctx: Context) -> FunctionTool:
    return FunctionTool.from_defaults(
        partial(set_illustration_url, ctx),
        name="set_illustration_url",
        description="Set the current scene illustration by providing a URL.",
    )
