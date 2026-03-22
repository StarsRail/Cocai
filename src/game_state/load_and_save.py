"""
Game state persistence layer using Chainlit's data layer.

Stores GameState in the thread metadata JSONB field so it survives session restarts.
"""

import logging
from typing import Optional

import chainlit as cl

from game_state.data_models import GameState
from utils import set_up_data_layer

logger = logging.getLogger(__name__)


async def save_game_state(game_state: GameState) -> bool:
    """
    Persist the game state to the current thread's metadata.

    Returns True if successful, False otherwise.
    """
    try:
        thread_id = cl.context.session.thread_id
        if not thread_id:
            logger.warning("No thread_id available; cannot persist game state")
            return False

        # Get the data layer instance
        data_layer = set_up_data_layer()
        if not data_layer:
            logger.warning("No data_layer available; cannot persist game state")
            return False

        # Get current thread metadata
        thread = await data_layer.get_thread(thread_id)
        if not thread:
            logger.warning(f"Thread {thread_id} not found; cannot persist game state")
            return False

        # Serialize game state to dict
        game_state_dict = game_state.to_dict()

        # Store in thread metadata
        metadata = thread.metadata or {}
        metadata["game_state"] = game_state_dict

        # Update thread with new metadata
        thread.metadata = metadata
        await data_layer.update_thread(thread_id, metadata)

        logger.debug(f"Persisted game state for thread {thread_id}")
        return True
    except Exception as e:
        logger.error(f"Failed to persist game state: {e}", exc_info=True)
        return False


async def load_game_state() -> Optional[GameState]:
    """
    Load game state from the current thread's metadata.

    Returns None if no saved state exists or if loading fails.
    """
    try:
        thread_id = cl.context.session.thread_id
        if not thread_id:
            logger.debug("No thread_id available; cannot load game state")
            return None

        # Get the data layer instance
        data_layer = set_up_data_layer()
        if not data_layer:
            logger.debug("No data_layer available; cannot load game state")
            return None

        # Get thread metadata
        thread = await data_layer.get_thread(thread_id)
        if not thread or not thread.metadata:
            logger.debug(f"No metadata found for thread {thread_id}")
            return None

        # Extract game state from metadata
        game_state_dict = thread.metadata.get("game_state")
        if not game_state_dict:
            logger.debug(f"No game_state in metadata for thread {thread_id}")
            return None

        # Reconstruct GameState from dict
        game_state = GameState.from_dict(game_state_dict)
        logger.debug(f"Loaded game state for thread {thread_id}")
        return game_state
    except Exception as e:
        logger.error(f"Failed to load game state: {e}", exc_info=True)
        return None
