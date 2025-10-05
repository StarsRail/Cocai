import logging
import os
from typing import List

from llama_index.core.objects.base import ObjectRetriever
from llama_index.core.schema import QueryType
from llama_index.core.tools import BaseTool, FunctionTool
from llama_index.core.workflow import Context
from llama_index.tools.tavily_research import TavilyToolSpec

from agentic_tools.create_character import build_tool_for_creating_character
from agentic_tools.misc import (
    ToolForConsultingTheModule,
    ToolForSuggestingChoices,
    illustrate_a_scene,
    record_a_clue_tool,
    set_illustration_url_tool,
)
from agentic_tools.roll_dices import roll_a_dice, roll_a_skill


class AgentContextAwareToolRetriever(ObjectRetriever[BaseTool]):
    """
    Just like defining a list of tools directly when initializing the agent,
    only that here we can initialize tools that need to access the agentWorkflow's context.

    This workaround is needed because LlamaIndex's Workflow Context can't be initialized without initializing the agentWorkflow first,
    but the agentWorkflow needs either a list of tools upfront or a tool retriever.
    """

    def __init__(self, ctx: Context):
        logger = logging.getLogger("AgentContextAwareToolRetriever")
        if api_key := os.environ.get("TAVILY_API_KEY", None):
            # Manage your API keys here: https://app.tavily.com/home
            logger.info(
                "Thanks for providing a Tavily API key. This AI agent will be able to use search the internet."
            )
            tavily_tool = TavilyToolSpec(
                api_key=api_key,
            ).to_tool_list()
        else:
            tavily_tool = []
        self._tools: List[FunctionTool] = tavily_tool + [
            FunctionTool.from_defaults(ToolForSuggestingChoices().suggest_choices),
            FunctionTool.from_defaults(
                ToolForConsultingTheModule().consult_the_game_module,
            ),
            FunctionTool.from_defaults(roll_a_dice),
            FunctionTool.from_defaults(roll_a_skill),
            FunctionTool.from_defaults(illustrate_a_scene),
            build_tool_for_creating_character(ctx),
            record_a_clue_tool,
            set_illustration_url_tool,
        ]
        self._ctx = ctx

    def retrieve(self, str_or_query_bundle: QueryType) -> List[BaseTool]:
        # Here you can customize which tools to return based on the context.
        # For simplicity, we return all tools.
        return self._tools  # type: ignore

    async def aretrieve(self, str_or_query_bundle: QueryType) -> List[BaseTool]:
        return self.retrieve(str_or_query_bundle)
