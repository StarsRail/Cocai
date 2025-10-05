import logging
from functools import wraps
from typing import List, Literal, Optional

import cochar
from cochar.character import Character
from llama_index.core.tools import FunctionTool
from pydantic import BaseModel, Field

from events import broadcaster
from state import STATE


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
def create_character(*args, **kwargs) -> dict:
    logger = logging.getLogger("create_character")
    character: Character = cochar.create_character(*args, **kwargs)
    # Persist as the current PC and notify UI via SSE
    try:
        STATE.pc = character
        pc_payload = STATE.to_dict().get("pc", {})
        broadcaster.publish({"type": "pc", "pc": pc_payload})
    except Exception as e:
        logger.error(f"Failed to publish the new PC via SSE: {e}")
    return character.get_json_format()


tool_for_creating_character = FunctionTool.from_defaults(
    create_character,
    fn_schema=CreateCharacterRequest,
    description="Create a playable character.",
)
