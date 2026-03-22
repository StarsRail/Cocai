"""Agent factory for creating phase-optimized agents."""

import logging
from pathlib import Path
from typing import Callable, Dict

from llama_index.core.agent.workflow import FunctionAgent
from llama_index.core.memory import Memory
from llama_index.core.objects.base import ObjectRetriever
from llama_index.core.tools import BaseTool
from llama_index.core.workflow import Context

from agents.adventure import AdventureToolRetriever
from agents.character_creation import CharacterCreationToolRetriever
from game_state.data_models import GamePhase

logger = logging.getLogger(__name__)


class AgentFactory:
    """Factory for creating phase-optimized FunctionAgent instances."""

    def __init__(self):
        """Initialize the factory."""
        self._prompt_cache: Dict[GamePhase, str] = {}

    def create_agent_for_phase(
        self,
        phase: GamePhase,
        ctx: Context,
        memory: Memory,
    ) -> FunctionAgent:
        """
        Create a FunctionAgent optimized for the given game phase.

        Args:
            phase: The game phase (CHARACTER_CREATION, ADVENTURE, etc.)
            ctx: The agent workflow context
            memory: The shared memory instance (Mem0 or default)

        Returns:
            A FunctionAgent configured for the phase with appropriate tools and system prompt
        """
        # Load phase-specific system prompt
        system_prompt = self._load_system_prompt(phase)

        # Get phase-specific tool retriever
        tool_retriever = self._get_tool_retriever_for_phase(phase, ctx)

        # Create agent
        agent = FunctionAgent(
            system_prompt=system_prompt,
            memory=memory,
        )

        # Set phase-specific tool retriever
        agent.tool_retriever = tool_retriever

        logger.info(
            f"✅ Created agent for phase: {phase.emoji()} {phase.value}",
            extra={"phase": phase.value},
        )

        return agent

    def _load_system_prompt(self, phase: GamePhase) -> str:
        """
        Load phase-specific system prompt from file.

        Caches loaded prompts for performance.
        """
        # Check cache
        if phase in self._prompt_cache:
            return self._prompt_cache[phase]

        # Map phase to prompt file
        prompt_map: Dict[GamePhase, str] = {
            GamePhase.CHARACTER_CREATION: "prompts/character_creation_prompt.md",
            GamePhase.ADVENTURE: "prompts/adventure_prompt.md",
        }

        prompt_file = prompt_map.get(phase)
        if not prompt_file:
            logger.warning(f"No prompt file for phase {phase.value}, using default")
            with open("prompts/system_prompt.md", encoding="utf-8") as f:
                prompt = f.read()
        else:
            # Try to load phase-specific prompt, fall back to default
            prompt_path = Path(prompt_file)
            if prompt_path.exists():
                with open(prompt_path, encoding="utf-8") as f:
                    prompt = f.read()
                logger.info(f"✓ Loaded prompt: {prompt_file}")
            else:
                logger.warning(
                    f"Prompt file not found: {prompt_file}, using default system prompt"
                )
                with open("prompts/system_prompt.md", encoding="utf-8") as f:
                    prompt = f.read()

        # Cache for future use
        self._prompt_cache[phase] = prompt
        return prompt

    def _get_tool_retriever_for_phase(
        self, phase: GamePhase, ctx: Context
    ) -> ObjectRetriever[BaseTool]:
        """Get phase-specific tool retriever."""
        retriever_map: Dict[GamePhase, Callable] = {
            GamePhase.CHARACTER_CREATION: lambda: CharacterCreationToolRetriever(ctx),
            GamePhase.ADVENTURE: lambda: AdventureToolRetriever(ctx),
        }

        retriever_fn = retriever_map.get(phase)
        if not retriever_fn:
            raise ValueError(f"No tool retriever defined for phase: {phase.value}")

        return retriever_fn()

    def clear_cache(self) -> None:
        """Clear the prompt cache (useful for development/testing)."""
        self._prompt_cache.clear()
        logger.debug("Cleared prompt cache")
