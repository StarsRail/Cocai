"""Adventure phase tools and tool retriever."""

import logging
import os
from typing import List

from llama_index.core.objects.base import ObjectRetriever
from llama_index.core.schema import QueryType
from llama_index.core.tools import BaseTool, FunctionTool
from llama_index.core.workflow import Context
from llama_index.tools.tavily_research import TavilyToolSpec

from agentic_tools.illustrate_scene import (
    build_tool_for_setting_illustration_url,
    illustrate_a_scene,
)
from agentic_tools.misc import (
    ToolForConsultingTheModule,
    ToolForSuggestingChoices,
    build_tool_for_recording_a_clue,
    update_a_stat_tool,
)
from agentic_tools.roll_dices import roll_a_dice, roll_a_skill

logger = logging.getLogger(__name__)


class AdventureToolRetriever(ObjectRetriever[BaseTool]):
    """
    Tool retriever for the ADVENTURE phase.

    In this phase, the player is investigating and exploring. All game-relevant
    tools are available (rolling dice, suggesting choices, recording clues, etc.).
    """

    def __init__(self, ctx: Context):
        """Initialize with agent context."""
        self._ctx = ctx
        logger.info("🛠️  Initialized AdventureToolRetriever")

    def retrieve(self, str_or_query_bundle: QueryType) -> List[BaseTool]:
        """Return tools available in ADVENTURE phase."""
        # Optional: Tavily search if API key is available
        if api_key := os.environ.get("TAVILY_API_KEY", None):
            logger.info(
                "✓ Tavily API key found; search will be available to the agent."
            )
            tavily_tools = TavilyToolSpec(api_key=api_key).to_tool_list()
        else:
            tavily_tools = []
            logger.debug("Tavily API key not found; search tool disabled.")

        tools: List[BaseTool] = tavily_tools + [
            # Game module consultation (for lore, NPC info, etc.)
            FunctionTool.from_defaults(
                ToolForConsultingTheModule().consult_the_game_module,
            ),
            # Dice rolls (essential for CoC mechanics)
            FunctionTool.from_defaults(roll_a_dice),
            FunctionTool.from_defaults(roll_a_skill),
            # Scene illustration
            FunctionTool.from_defaults(illustrate_a_scene),
            # Tactical suggestions
            FunctionTool.from_defaults(ToolForSuggestingChoices().suggest_choices),
            # Game state tracking
            update_a_stat_tool,
            build_tool_for_recording_a_clue(self._ctx),
            build_tool_for_setting_illustration_url(self._ctx),
        ]
        return tools  # type: ignore

    async def aretrieve(self, str_or_query_bundle: QueryType) -> List[BaseTool]:
        """Async retrieve (same as sync for now)."""
        return self.retrieve(str_or_query_bundle)
