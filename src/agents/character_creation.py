"""Character creation phase tools and tool retriever."""

import logging
from typing import List

from llama_index.core.objects.base import ObjectRetriever
from llama_index.core.schema import QueryType
from llama_index.core.tools import BaseTool, FunctionTool
from llama_index.core.workflow import Context

from agentic_tools.create_character import build_tool_for_creating_character
from agentic_tools.misc import ToolForConsultingTheModule

logger = logging.getLogger(__name__)


class CharacterCreationToolRetriever(ObjectRetriever[BaseTool]):
    """
    Tool retriever for the CHARACTER_CREATION phase.

    In this phase, the player is creating a character. Only tools relevant
    to character creation and game module consultation are available.
    """

    def __init__(self, ctx: Context):
        """Initialize with agent context."""
        self._ctx = ctx
        logger.info("🛠️  Initialized CharacterCreationToolRetriever")

    def retrieve(self, str_or_query_bundle: QueryType) -> List[BaseTool]:
        """Return tools available in CHARACTER_CREATION phase."""
        tools: List[BaseTool] = [
            # Character creation tool (context-aware)
            build_tool_for_creating_character(self._ctx),
            # Consult module for inspiration
            FunctionTool.from_defaults(
                ToolForConsultingTheModule().consult_the_game_module,
            ),
        ]
        return tools  # type: ignore

    async def aretrieve(self, str_or_query_bundle: QueryType) -> List[BaseTool]:
        """Async retrieve (same as sync for now)."""
        return self.retrieve(str_or_query_bundle)
