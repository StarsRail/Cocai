import base64
import logging
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
from llama_index.vector_stores.qdrant import QdrantVectorStore
from pydantic import BaseModel, Field


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
    character: Character = cochar.create_character(*args, **kwargs)
    # TODO: Store the character somewhere.
    return character.get_json_format()


tool_for_creating_character = FunctionTool.from_defaults(
    create_character,
    fn_schema=CreateCharacterRequest,
    description="Create a character.",
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
        return Settings.llm.complete(prompt)


class ToolForConsultingTheModule:
    query_engine: BaseQueryEngine = None

    def __init__(
        self,
        path_to_module_folder: Path = Path("game_modules/"),
    ):
        logger = logging.getLogger("ToolForConsultingTheModule")
        client = qdrant_client.QdrantClient(
            host="localhost",
            port=6333,
        )
        vector_store = QdrantVectorStore(client=client, collection_name="game_module")
        if client.collection_exists("game_module"):
            logger.info("The collection exists. Loading.")
            index = VectorStoreIndex.from_vector_store(vector_store=vector_store)
        else:
            logger.info("The collection does not exist. Creating.")
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
        return self.query_engine.query(query).response or ""


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


def roll_a_skill(
    skill_value: int = Field(description="skill value", ge=0, le=100),
    difficulty: Difficulty = Field(
        description="difficulty level", default=Difficulty.REGULAR
    ),
) -> str:
    """
    Roll a skill check and check the result.
    """
    dice_outcome = random.randint(1, 100)
    tenth_digit = dice_outcome // 10
    if tenth_digit == 0:
        tenth_digit = 10
    ones_digit = dice_outcome % 10
    if ones_digit == 0:
        ones_digit = 10
    message = cl.Message(
        content="",
        author="roll_a_skill",
        elements=[
            cl.Pdf(
                name="fake-pdf",
                display="inline",
                url=f"/roll_dice?d10={tenth_digit}&d10={ones_digit}",
            )
        ],
    )
    cl.run_sync(message.send())

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
