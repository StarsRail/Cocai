import base64
import logging
import os
import random

# How to use enums in Python: https://docs.python.org/3/howto/enum.html
from enum import IntEnum
from functools import wraps
from pathlib import Path
from typing import List, Literal, Optional

import chainlit as cl
import cochar.skill
import qdrant_client
import requests
from cochar.character import Character
from llama_index.core import (
    Settings,
    SimpleDirectoryReader,
    StorageContext,
    VectorStoreIndex,
)
from llama_index.core.base.base_query_engine import BaseQueryEngine
from llama_index.core.tools import FunctionTool
from llama_index.core.workflow import Context
from llama_index.vector_stores.qdrant import QdrantVectorStore
from pydantic import BaseModel, Field

from events import broadcaster
from state import STATE, Clue


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
        # Reuse state's serializer to get UI-friendly pc shape
        from state import STATE as _S  # avoid confusion with local STATE

        pc_payload = _S.to_dict().get("pc", {})
        broadcaster.publish({"type": "pc", "pc": pc_payload})
    except Exception as e:
        logger.error(f"Failed to publish the new PC via SSE: {e}")
    return character.get_json_format()


tool_for_creating_character = FunctionTool.from_defaults(
    create_character,
    fn_schema=CreateCharacterRequest,
    description="Create a playable character.",
)


class ToolForSuggestingChoices:
    def __init__(self, path_to_prompts_file: Path = Path("prompts/choices_prompt.md")):
        self.__prompt = path_to_prompts_file.read_text()

    def suggest_choices(
        self, situation: str = Field(description="a brief description of the situation")
    ) -> str:
        """
        If the user wants to know what skills their character can use in a particular situation (and what the possible consequences might be), you can use this tool.
        Note: This tool can only be used when the game is in progress. This is not a tool for meta-tasks like character creation.
        """
        prompt = self.__prompt.format(situation=situation)
        return Settings.llm.complete(prompt).text


class ToolForConsultingTheModule:
    query_engine: Optional[BaseQueryEngine] = None

    def __init__(
        self,
        path_to_module_folder: Path = Path(
            os.environ.get("GAME_MODULE_PATH", "game_modules/Clean-Up-Aisle-Four")
        ),
    ):
        logger = logging.getLogger("ToolForConsultingTheModule")
        client = qdrant_client.QdrantClient(
            host="localhost",
            port=6333,
        )
        vector_store = QdrantVectorStore(client=client, collection_name="game_module")
        if client.collection_exists("game_module") and bool(
            os.environ.get("SHOULD_REUSE_EXISTING_INDEX", True)
        ):
            logger.info("The collection exists. Loading.")
            index = VectorStoreIndex.from_vector_store(vector_store=vector_store)
        else:
            logger.info(
                "The collection does not exist, or the environment variable indicates that we should ignore the existing index. Creating."
            )
            documents = SimpleDirectoryReader(
                input_dir=str(path_to_module_folder),
                # https://docs.llamaindex.ai/en/stable/module_guides/loading/simpledirectoryreader.html#reading-from-subdirectories
                recursive=True,
                # https://docs.llamaindex.ai/en/stable/module_guides/loading/simpledirectoryreader.html#restricting-the-files-loaded
                # Before including image files here, `mamba install pillow`.
                # Before including audio files here, `pip install openai-whisper`.
                required_exts=[".md", ".txt"],
            ).load_data()
            storage_context = StorageContext.from_defaults(vector_store=vector_store)
            index = VectorStoreIndex.from_documents(
                # https://docs.llamaindex.ai/en/stable/api_reference/indices/vector_store.html#llama_index.indices.vector_store.base.VectorStoreIndex.from_documents
                documents=documents,
                storage_context=storage_context,
                show_progress=True,
            )
        self.query_engine = index.as_query_engine(
            similarity_top_k=5,
            # For a query engine hidden inside an Agent, streaming really doesn't make sense.
            # https://docs.llamaindex.ai/en/stable/module_guides/deploying/query_engine/streaming.html#streaming
            streaming=False,
        )

    def consult_the_game_module(
        self,
        query: str = Field(
            description="a brief description of what you want to consult about"
        ),
    ) -> str:
        """
        If you feel you need to consult the module ("playbook" / handbook) about:

        - how the story should progress,
        - some factual data, or
        - how the situation / a particular NPC is set up,

        you can use this tool.
        """
        logger = logging.getLogger("consult_the_game_module")
        if not self.query_engine:
            return ""
        try:
            response = self.query_engine.query(query)
            # The response can be a Response object or string-like; convert safely to str.
            return str(getattr(response, "response", response) or "")
        except Exception as e:
            logger.error(f"Error occurred while consulting the game module: {e}")
            return ""


def roll_a_dice(
    n: int = Field(description="number of faces of the dice to roll", gt=0, le=100),
) -> int:
    """
    Roll an n-faced dice and return the result.
    """
    return random.randint(1, int(n))


class DegreesOfSuccess(IntEnum):
    FUMBLE = 0
    FAIL = 1
    SUCCESS = 2
    HARD_SUCCESS = 3
    EXTREME_SUCCESS = 4
    CRITICAL_SUCCESS = 5


class Difficulty(IntEnum):
    """
    For tasks:
    > A regular task requires a roll of equal to or less than your skill value on 1D100 (a Regular success).
    > A difficult task requires a roll result equal to or less than half your skill value (a Hard success).
    > A task approaching the limits of human capability requires a roll equal to or less than one-fifth of your skill
    >   value (an Extreme success).

    ([source](https://cthulhuwiki.chaosium.com/rules/game-system.html#skill-rolls-and-difficulty-levels))


    For opposed rolls:
    - Regular: Opposing skill/characteristic is below 50.
    - Hard: Opposing skill/characteristic is equal to or above 50.
    - Extreme: Opposing skill/characteristic is equal to or above 90.

    ([source](https://trpgline.com/en/rules/coc7/summary))
    """

    REGULAR = 0
    DIFFICULT = 1
    EXTREME = 2


def __roll_a_skill(
    skill_value: int = Field(description="skill value", ge=0, le=100),
    difficulty: Difficulty = Field(
        description="difficulty level", default=Difficulty.REGULAR
    ),
) -> DegreesOfSuccess:
    """
    Roll a skill check and return the result.
    """
    result = roll_a_dice(n=100)
    logger = logging.getLogger("__roll_a_skill")
    logger.info(f"result: {result}")
    degree_of_success = __map_dice_outcome_to_degree_of_success(
        difficulty, result, skill_value
    )
    return degree_of_success


def __map_dice_outcome_to_degree_of_success(
    difficulty: Difficulty, result: int, skill_value: int
) -> DegreesOfSuccess:
    if result == 100:
        return DegreesOfSuccess.FUMBLE
    if result == 1:
        return DegreesOfSuccess.CRITICAL_SUCCESS
    result_ignoring_difficulty = DegreesOfSuccess.FAIL
    if result <= skill_value // 5:
        result_ignoring_difficulty = DegreesOfSuccess.EXTREME_SUCCESS
    elif result <= skill_value // 2:
        result_ignoring_difficulty = DegreesOfSuccess.HARD_SUCCESS
    elif result <= skill_value:
        result_ignoring_difficulty = DegreesOfSuccess.SUCCESS
    # Now, we consider the difficulty.
    if difficulty == Difficulty.REGULAR:
        return result_ignoring_difficulty
    elif difficulty == Difficulty.DIFFICULT:
        if result_ignoring_difficulty >= DegreesOfSuccess.HARD_SUCCESS:
            return result_ignoring_difficulty
        # else, fall through to return a FAIL.
    elif difficulty == Difficulty.EXTREME:
        if result_ignoring_difficulty == DegreesOfSuccess.EXTREME_SUCCESS:
            return result_ignoring_difficulty
        # else, fall through to return a FAIL.
    return DegreesOfSuccess.FAIL


async def roll_a_skill(
    ctx: Context,
    skill_value: int = Field(description="skill value", ge=0, le=100),
    difficulty: Difficulty = Field(
        description="difficulty level", default=Difficulty.REGULAR
    ),
) -> str:
    """
    Roll a skill check and check the result.
    """
    logger = logging.getLogger("roll_a_skill")
    # Roll the dice.
    dice_outcome = random.randint(1, 100)
    tenth_digit = dice_outcome // 10
    if tenth_digit == 0:
        tenth_digit = 10
    ones_digit = dice_outcome % 10
    if ones_digit == 0:
        ones_digit = 10

    # Send a fake PDF with the dice-rolling scene.
    try:
        scene = cl.Pdf(
            name="fake-pdf",
            display="inline",
            url=f"/roll_dice?d10={tenth_digit}&d10={ones_digit}",
            # Prevent the default factory from being triggered by giving it a value explicitly.
            thread_id=await ctx.store.get("user_message_thread_id", "unknown"),
        )
        message = cl.Message(
            content="",
            author="roll_a_skill",
            elements=[scene],
            parent_id=await ctx.store.get("user_message_id", None),
        )
        await message.send()
    except Exception as e:
        logger.error(f"Failed to send the scene: {e}")

    # Describe the result.
    result = __map_dice_outcome_to_degree_of_success(
        difficulty, dice_outcome, int(skill_value)
    )
    return f"You rolled a {dice_outcome}. That's a {result.name.lower().replace('_', ' ')}!"


def illustrate_a_scene(
    scene_description: str = Field(description="a detailed description of the scene"),
) -> str:
    """
    Illustrate a scene based on the description.
    The player may prefer seeing a visual representation of the scene,
    so it may be a good idea to use this tool when you progress the story.
    """
    response = requests.post(
        "http://127.0.0.1:7860/sdapi/v1/txt2img",
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
    image = base64.b64decode(data["images"][0])
    message = cl.Message(
        content=scene_description,
        author="illustrate_a_scene",
        elements=[cl.Image(name=scene_description, display="inline", content=image)],
    )
    cl.run_sync(message.send())
    return "The illustrator has handed the player a drawing of the scene. You can continue."


# ---- Stub: update_a_stat -----------------------------------------------------


def update_a_stat(
    stat_name: str = Field(description="Name of the stat to update"),
    diff: Optional[float] = Field(
        default=None,
        description="Delta to add to the current value (mutually exclusive with 'value').",
    ),
    value: Optional[float] = Field(
        default=None,
        description="Absolute value to set (mutually exclusive with 'diff').",
    ),
) -> str:
    """
    Update a character stat by either applying a diff or setting an absolute value.
    Exactly one of `diff` and `value` must be provided. This is a stub for now.
    """
    if (diff is None and value is None) or (diff is not None and value is not None):
        raise ValueError("Provide exactly one of 'diff' or 'value'.")
    # TODO: Integrate with character storage when available.
    if diff is not None:
        return f"Stub: recorded update for '{stat_name}' with diff={diff}."
    else:
        return f"Stub: recorded update for '{stat_name}' with value={value}."


update_a_stat_tool = FunctionTool.from_defaults(
    update_a_stat,
    description=(
        "Update a character stat by either applying a diff or setting an absolute value. "
        "Exactly one of 'diff' and 'value' must be provided."
    ),
)


# ---- UI-state tools: clues, illustration ---------------------------


def record_a_clue(
    title: str = Field(description="Short title for the clue"),
    content: str = Field(description="Detailed description of the clue"),
    found_at: Optional[str] = Field(
        default=None, description="Where/when it was found"
    ),
    clue_id: Optional[str] = Field(
        default=None, description="Stable id if you want to update an existing clue"
    ),
) -> str:
    """
    Add or update a clue in the left-pane accordion.
    If clue_id is provided and already exists, it will be replaced.
    """
    cid = str(clue_id or f"c{len(STATE.clues)+1}")
    clue = Clue(id=cid, title=title, content=content, found_at=found_at)
    STATE.clues = [c for c in STATE.clues if c.id != cid] + [clue]
    try:
        broadcaster.publish(
            {
                "type": "clues",
                "clues": [c.__dict__ for c in STATE.clues],
                "updated": clue.__dict__,
            }
        )
    except Exception:
        pass
    return f"Recorded clue '{title}'."


def set_illustration_url(
    url: str = Field(description="Public URL to display in the Illustration pane"),
) -> str:
    """
    Set the current scene illustration by providing a URL (e.g. /public/.. or https://..).
    """
    STATE.illustration_url = url
    try:
        broadcaster.publish({"type": "illustration", "url": STATE.illustration_url})
    except Exception:
        pass
    return "Updated the illustration pane."


record_a_clue_tool = FunctionTool.from_defaults(
    record_a_clue,
    description="Add or update a clue in the left-pane accordion.",
)

set_illustration_url_tool = FunctionTool.from_defaults(
    set_illustration_url,
    description="Set the current scene illustration by providing a URL.",
)
