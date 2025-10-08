import logging
from functools import partial, wraps
from typing import List, Literal, Optional

import cochar
from cochar.character import Character
from llama_index.core.tools import FunctionTool
from llama_index.core.workflow import Context
from pydantic import BaseModel, Field

from events import broadcaster
from state import GameState


class CreateCharacterRequest(BaseModel):
    year: int = Field(
        1925,
        ge=1890,
        description="Year of the game, must be an integer starting from 1890.",
    )
    country: Literal["US", "PL", "ES"] = Field(
        ...,
        description="Country of the character's origin. Available options: 'US', 'PL', 'ES'.",
    )
    first_name: Optional[str] = Field(
        None,
        description="Character's first name, optional. A random name is used if omitted.",
    )
    last_name: Optional[str] = Field(
        None,
        description="Character's last name, optional. A random name is used if omitted.",
    )
    age: Optional[int] = Field(
        None,
        ge=15,
        le=90,
        description="Character's age. Must be between 15 and 90. If omitted, a random age is selected.",
    )
    sex: Optional[Literal["M", "F"]] = Field(
        None,
        description="Character's sex. Available options: 'M', 'F'. If omitted, sex is chosen randomly.",
    )
    random_mode: bool = Field(
        False,
        description="If set to True, characteristics are ignored for random occupation generation.",
    )

    occupation: Literal[*cochar.OCCUPATIONS_LIST] = Field(  # type: ignore[valid-type]
        None,
        description="Character's occupation. Must be a valid occupation or random if omitted.",
    )
    skills: Optional[dict] = Field(
        default_factory=dict,
        description="Dictionary of character's skills. Defaults to an empty dictionary.",
    )
    occup_type: Literal["classic", "expansion", "custom"] = Field(
        "classic",
        description="Occupation set type. Available options: 'classic', 'expansion', 'custom'.",
    )
    era: Literal["classic-1920", "modern"] = Field(
        "classic-1920",
        description="Era for the character. Available options: 'classic-1920', 'modern'.",
    )
    tags: Optional[List[Literal["lovecraftian", "criminal"]]] = Field(
        None,
        description="List of occupation tags. Available options: 'lovecraftian', 'criminal'.",
    )


@wraps(cochar.create_character)
async def create_character(ctx: Context, *args, **kwargs) -> dict:
    logger = logging.getLogger("create_character")
    # Remove 'ctx' from kwargs if present
    kwargs.pop("ctx", None)
    try:
        character: Character = cochar.create_character(*args, **kwargs)
    except Exception as e:
        logger.error(f"Character creation failed: {e}", exc_info=e)
        raise RuntimeError(f"Character creation failed: {e}") from e
    character_as_json = dict()
    # Access or modify state in the context
    async with ctx.store.edit_state() as ctx_state:
        user_visible_state = ctx_state.get("user-visible")
        if type(user_visible_state) is GameState:
            user_visible_state.pc = character
        character_as_json = user_visible_state.to_dict().get("pc", {})
    try:
        broadcaster.publish({"type": "pc", "pc": character_as_json})
    except Exception as e:
        logger.error(f"Failed to publish the new PC via SSE: {e}")
    return character.get_json_format()


def build_tool_for_creating_character(ctx: Context) -> FunctionTool:
    return FunctionTool.from_defaults(
        partial(create_character, ctx),
        name="create_character",
        fn_schema=CreateCharacterRequest,
        description="Create a playable character.",
    )
