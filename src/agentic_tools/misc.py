import logging
import os
from functools import partial

# How to use enums in Python: https://docs.python.org/3/howto/enum.html
from pathlib import Path
from typing import Optional

import qdrant_client
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
from pydantic import Field

from events import broadcaster
from state import Clue, GameState
from utils import env_flag


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

        qdrant_host = os.environ.get("QDRANT_HOST", "localhost")
        qdrant_port = int(os.environ.get("QDRANT_PORT", "6333"))
        collection = os.environ.get("QDRANT_COLLECTION", "game_module")

        index: VectorStoreIndex
        vector_store = None

        try:
            client = qdrant_client.QdrantClient(host=qdrant_host, port=qdrant_port)
            vector_store = QdrantVectorStore(client=client, collection_name=collection)
            reuse = env_flag("SHOULD_REUSE_EXISTING_INDEX", True)
            if client.collection_exists(collection) and reuse:
                logger.info(
                    f"Qdrant collection '{collection}' exists at {qdrant_host}:{qdrant_port}. Loading."
                )
                index = VectorStoreIndex.from_vector_store(vector_store=vector_store)
            else:
                logger.info(
                    "Qdrant collection absent or reuse disabled. Building index from documents."
                )
                documents = SimpleDirectoryReader(
                    input_dir=str(path_to_module_folder),
                    recursive=True,
                    required_exts=[".md", ".txt"],
                ).load_data()
                storage_context = StorageContext.from_defaults(
                    vector_store=vector_store
                )
                index = VectorStoreIndex.from_documents(
                    documents=documents,
                    storage_context=storage_context,
                    show_progress=True,
                )
        except Exception as e:
            # Fallback to in-memory index if Qdrant is unavailable
            logger.warning(
                "Qdrant unavailable or misconfigured; falling back to in-memory vector store.",
                exc_info=e,
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
            index = VectorStoreIndex.from_documents(
                documents=documents, show_progress=True
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


async def record_a_clue(
    ctx: Context,
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
    logger = logging.getLogger("record_a_clue")
    read_only_user_visible_state: GameState = await ctx.store.get("user-visible")
    cid = str(clue_id or f"c{len(read_only_user_visible_state.clues) + 1}")
    clue = Clue(id=cid, title=title, content=content, found_at=found_at)
    new_all_clues = [c for c in read_only_user_visible_state.clues if c.id != cid] + [
        clue
    ]
    # Update the user-visible state in the context.
    async with ctx.store.edit_state() as ctx_state:
        user_visible_state: GameState = ctx_state.get("user-visible")
        user_visible_state.clues = new_all_clues
    try:
        broadcaster.publish(
            {
                "type": "clues",
                "clues": [c.__dict__ for c in new_all_clues],
                "updated": clue.__dict__,
            }
        )
    except Exception as e:
        logger.error("Failed to publish updated clues.", exc_info=e)
    return f"Recorded clue '{title}'."


def build_tool_for_recording_a_clue(ctx: Context) -> FunctionTool:
    return FunctionTool.from_defaults(
        partial(record_a_clue, ctx),
        name="record_a_clue",
        description="Add or update a clue in the left-pane accordion.",
    )
