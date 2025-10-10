#!/usr/bin/env python
import asyncio
import logging
from collections.abc import Coroutine
from typing import List

import chainlit as cl
from llama_index.core import Settings
from llama_index.core.agent.workflow import AgentStream, FunctionAgent
from llama_index.core.callbacks import CallbackManager, LlamaDebugHandler
from llama_index.core.memory import Memory
from llama_index.core.workflow import Context
from llama_index.embeddings.ollama import OllamaEmbedding
from llama_index.memory.mem0 import Mem0Memory
from openinference.instrumentation.llama_index import LlamaIndexInstrumentor

from agentic_tools import AgentContextAwareToolRetriever as ToolProvider
from agentic_tools.misc import ToolForConsultingTheModule
from async_panes.history import update_history_if_needed
from async_panes.scene import update_scene_if_needed
from config import AppConfig
from state import GameState
from utils import env_flag, set_up_data_layer

logger = logging.getLogger(__name__)

set_up_data_layer()

try:
    # "Phoenix can display in real time the traces automatically collected from your LlamaIndex application."
    # https://docs.llamaindex.ai/en/stable/module_guides/observability/observability.html
    from phoenix.otel import register

    tracer_provider = register()
    LlamaIndexInstrumentor().instrument(tracer_provider=tracer_provider)
except Exception as e:
    logger.warning(f"Failed to register Phoenix OpenTelemetry instrumentation: {e}")


def create_callback_manager() -> CallbackManager:
    # Phoenix can display in real time the traces automatically collected from your LlamaIndex application.
    # The one-click way is as follows:
    # ```
    # llama_index.core.set_global_handler("arize_phoenix")
    # from llama_index.callbacks.arize_phoenix import (
    #     arize_phoenix_callback_handler,
    # )
    # ```
    # But I prefer to do it manually, so that I can put all callback handlers in one place.
    debug_logger = logging.getLogger("debug")
    debug_logger.setLevel(logging.DEBUG)
    callback_handlers = [
        LlamaDebugHandler(logger=debug_logger),
    ]
    # Chainlit's callback handler is buggy. I don't think we need to have the user see
    # all the low-level details of LlamaIndex's operations anyway.
    # callback_handlers.append(cl.LlamaIndexCallbackHandler())
    from typing import List, cast

    from llama_index.core.callbacks.base_handler import BaseCallbackHandler

    return CallbackManager(cast(List[BaseCallbackHandler], callback_handlers))


def set_up_llama_index(app_config: AppConfig):
    """
    One-time setup code for shared objects across all AgentRunners.
    """
    logger = logging.getLogger("set_up_llama_index")
    # ============= Beginning of the code block for wiring on to models. =============
    # At least when Chainlit is involved, LLM initializations must happen upon the `@cl.on_chat_start` event,
    # not in the global scope.
    # Otherwise, it messes up with Arize Phoenix: LLM calls won't be captured as parts of an Agent Step.
    if app_config.openai_api_key:
        logger.info("Using OpenAI API.")
        from llama_index.llms.openai import OpenAI

        Settings.llm = OpenAI(
            model="gpt-4o-mini",
            api_key=app_config.openai_api_key,
            is_function_calling_model=True,
            is_chat_model=True,
        )
    elif app_config.together_api_key:
        logger.info("Using Together AI API.")
        from llama_index.llms.openai_like import OpenAILike

        Settings.llm = OpenAILike(
            model="meta-llama/Meta-Llama-3.1-405B-Instruct-Turbo",
            api_base="https://api.together.xyz/v1",
            api_key=app_config.together_api_key,
            is_function_calling_model=True,
            is_chat_model=True,
        )
    else:
        logger.info("Using Ollama's OpenAI-compatible API.")
        from llama_index.llms.openai_like import OpenAILike

        Settings.llm = OpenAILike(
            model=app_config.ollama_llm_id,
            api_base=app_config.ollama_base_url + "/v1",
            api_key="ollama",
            is_function_calling_model=True,
            is_chat_model=True,
        )

    Settings.embed_model = OllamaEmbedding(
        model_name=app_config.ollama_embed_model_id,
        base_url=app_config.ollama_base_url,
    )
    # ============= End of the code block for wiring on to models. =============

    # Override the default system prompt for ReAct chats.
    with open("prompts/system_prompt.md", encoding="utf-8") as f:
        MY_SYSTEM_PROMPT = f.read()
    if app_config.should_preread_game_module:
        logger.info("Pre-reading the game module...")
        game_module_summary = ToolForConsultingTheModule().consult_the_game_module(
            "Story background, character requirements, and keeper's notes."
        )
        logger.info("Finished pre-reading the game module.")
        my_system_prompt = "\n\n".join(
            [
                MY_SYSTEM_PROMPT,
                "A brief description of the game module you are hosting is as follows:",
                "--------- BEGINNING OF GAME MODULE DESCRIPTION ---------",
                game_module_summary,
                "--------- END OF GAME MODULE DESCRIPTION ---------",
            ]
        )
    else:
        logger.info("Skipping pre-reading the game module.")
        my_system_prompt = MY_SYSTEM_PROMPT
    # Needed for "Retrieved the following sources" to show up on Chainlit.
    # This procedure will register Chainlit's callback manager, which will require Chainlit's context variables to
    # be ready before receiving an event, so it should be called AFTER calling the tool.
    Settings.callback_manager = create_callback_manager()
    return my_system_prompt


@cl.set_starters
async def set_starters(user=None, default_path: str | None = None):
    return [
        cl.Starter(
            label="Roll a 7-faced dice. Outcome?",
            message="Roll a 7-faced dice just for fun. What's the outcome?",
            icon="/public/avatars/roll_a_dice.png",
        ),
        cl.Starter(
            label="I'm stuck in a cave. What skills to use?",
            message="I'm stuck in a dark cave. What can I do?",
            icon="/public/avatars/suggest_choices.png",
        ),
        cl.Starter(
            label="Create a character for me.",
            message='Can you generate a character for me? Let\'s call him "Don Joe". Describe what kind of guy he is.',
            icon="/public/avatars/create_character.png",
        ),
        cl.Starter(
            label="What's the story background?",
            message="According to the game module, what's the background of the story?",
            icon="/public/avatars/consult_the_game_module.png",
        ),
    ]


@cl.on_chat_start
async def factory():
    # Build LLMs/tools and prompts per session to avoid global background resources
    app_config = AppConfig.from_env()
    my_system_prompt = set_up_llama_index(app_config)
    # Each chat session should have his own agent runner, because each chat session has different chat histories.
    key = cl.user_session.get("id")
    agent_memory = __prepare_memory(key, app_config)
    agent = FunctionAgent(
        system_prompt=my_system_prompt,
        memory=agent_memory,
        # We will be initalizing tools later via a custom tool retriever,
        # so that some of the tools can be made context-aware.
    )

    # User-visible game state includes things like the player character, a brief summary of the story so far, clues & items discovered, etc.
    user_visible_game_state = GameState()
    # Make agent aware of the user-visible game state.
    agent_ctx = Context(agent)
    async with agent_ctx.store.edit_state() as ctx_state:
        ctx_state["user-visible"] = user_visible_game_state

    agent.tool_retriever = ToolProvider(agent_ctx)

    cl.user_session.set(
        "agent",
        agent,
    )
    cl.user_session.set(
        "agent_ctx",
        agent_ctx,
    )
    cl.user_session.set(
        "agent_memory",
        agent_memory,
    )


def __prepare_memory(key, app_config: AppConfig) -> Memory | Mem0Memory:
    logger = logging.getLogger("prepare_memory")
    if app_config.disable_memory:
        logger.info("Memory is disabled. Using defaults.")
        return Memory.from_defaults(session_id="my_session", token_limit=40000)
    if app_config.mem0_api_key:
        logger.info("Using Mem0 API.")
        memory = Mem0Memory.from_client(
            context={"user_id": key},
            api_key=app_config.mem0_api_key,
            search_msg_limit=4,  # optional, default is 5
            version="v1.1",
        )
    else:
        logger.info(
            "Using local Mem0, because the env. var. `MEM0_API_KEY` wasn't found."
        )
        mem0_config = {
            "version": "v1.1",
            "vector_store": {
                "provider": "qdrant",
                "config": {
                    "collection_name": "cocai",
                    "embedding_model_dims": 768,  # Change this according to your local model's dimensions
                    "host": "localhost",
                    "port": 6333,
                },
            },
            "embedder": {
                "provider": "ollama",
                "config": {
                    "model": app_config.ollama_embed_model_id,
                    "ollama_base_url": app_config.ollama_base_url,
                    "embedding_dims": 768,  # Change this according to your local model's dimensions
                },
            },
        }
        if app_config.openai_api_key:
            logger.info("Using OpenAI API for Mem0's LLM calls.")
            mem0_config["llm"] = {
                "provider": "openai",
                "config": {
                    "model": "gpt-4o-mini",
                    "temperature": 0,
                    "max_tokens": 8000,
                },
            }
        else:
            logger.info("Using Ollama's OpenAI-compatible API for Mem0's LLM calls.")
            mem0_config["llm"] = {
                "provider": "ollama",
                "config": {
                    "model": app_config.ollama_llm_id,
                    "temperature": 0,
                    "max_tokens": 8000,
                    "ollama_base_url": app_config.ollama_base_url,
                },
            }
        try:
            memory = Mem0Memory.from_config(
                config=mem0_config,
                context={"user_id": key},
            )
        except Exception as e:
            logger.error(
                "Failed to set up Mem0 memory. LlamaIndex will use default implementation (SimpleChatStore) instead.",
                exc_info=e,
            )
            memory = Memory.from_defaults(session_id="my_session", token_limit=40000)
    return memory


@cl.on_chat_end
async def cleanup():
    logger = logging.getLogger("chat_cleanup")
    try:
        if asyncio_task := cl.user_session.get("asyncio_task_for_updating_history"):
            if not asyncio_task.done():
                logger.info("Cancelling background history update task on chat end...")
                asyncio_task.cancel()
        if asyncio_task2 := cl.user_session.get("asyncio_task_for_updating_scene"):
            if not asyncio_task2.done():
                logger.info("Cancelling background scene update task on chat end...")
                asyncio_task2.cancel()
    except Exception as e:
        logger.warning(f"Cleanup encountered an issue: {e}")


@cl.on_message
async def handle_message_from_user(message: cl.Message):
    logger = logging.getLogger("handle_message_from_user")

    # Get `asyncio_task_for_updating_history` from the user session. If it is not yet done, kill it first.
    if existing_asyncio_task := cl.user_session.get(
        "asyncio_task_for_updating_history"
    ):
        logger.info("Found existing asyncio task for updating history.")
        if existing_asyncio_task.done():
            logger.info("But it's already done.")
        else:
            logger.info("It's not yet done. Killing it.")
            existing_asyncio_task.cancel()
    # Same for scene updates
    if existing_scene_task := cl.user_session.get("asyncio_task_for_updating_scene"):
        logger.info("Found existing asyncio task for updating scene.")
        if existing_scene_task.done():
            logger.info("But it's already done.")
        else:
            logger.info("It's not yet done. Killing it.")
            existing_scene_task.cancel()

    agent_from_session = cl.user_session.get("agent")
    if agent_from_session is None or not isinstance(agent_from_session, FunctionAgent):
        await cl.Message(
            content="Agent not found. Please restart the chat session."
        ).send()
        return
    agent: FunctionAgent = agent_from_session

    agent_ctx_from_session = cl.user_session.get("agent_ctx")
    if agent_ctx_from_session is None or not isinstance(
        agent_ctx_from_session, Context
    ):
        await cl.Message(
            content="Agent context not found. Please restart the chat session."
        ).send()
        return
    agent_ctx: Context = agent_ctx_from_session

    agent_memory_from_session = cl.user_session.get("agent_memory")
    if agent_memory_from_session is None or not isinstance(
        agent_memory_from_session, (Memory, Mem0Memory)
    ):
        await cl.Message(
            content="Agent memory not found. Please restart the chat session."
        ).send()
        return
    agent_memory: Memory | Mem0Memory = agent_memory_from_session
    # Save the user message ID and thread ID to the context state, so that tools can use them.
    async with agent_ctx.store.edit_state() as ctx_state:
        # Don't use `message` directly, because it is not serializable (by the default serializer of `DictState`, probably).
        ctx_state["user_message_id"] = message.id
        ctx_state["user_message_thread_id"] = message.thread_id
    # Run the agent.
    handler = agent.run(message.content, context=agent_ctx, memory=agent_memory)
    response_message = cl.Message(content="")
    _agent_text_buffer: List[str] = []
    async for event in handler.stream_events():
        if isinstance(event, AgentStream):
            await response_message.stream_token(event.delta)
            _agent_text_buffer.append(event.delta)
    await response_message.update()
    # Final assistant reply text (for fallback if memory hasn't captured it yet)
    agent_text = ("".join(_agent_text_buffer)).strip() or (
        response_message.content or ""
    )

    if env_flag("ENABLE_AUTO_HISTORY_UPDATE", default=True):
        coroutine_for_updating_history: Coroutine = update_history_if_needed(
            ctx=agent_ctx,
            memory=agent_memory,
            last_user_msg=message.content,
            last_agent_msg=agent_text,
        )
        asyncio_task_for_updating_history: asyncio.Task = asyncio.create_task(
            # The create_task() approach is known as "fire and forget." To run it, you must be within an event loop.
            coroutine_for_updating_history
        )
        logger.info("Created new asyncio task for updating history. Saving it.")
        # Save the coroutine to the user session, so that it can be cancelled when a new message arrives.
        cl.user_session.set(
            "asyncio_task_for_updating_history",
            asyncio_task_for_updating_history,
        )
        logger.info("Saved asyncio task for updating history to user session.")

    if env_flag("ENABLE_AUTO_SCENE_UPDATE", default=True):
        coroutine_for_updating_scene: Coroutine = update_scene_if_needed(
            ctx=agent_ctx,
            memory=agent_memory,
            last_user_msg=message.content,
            last_agent_msg=agent_text,
        )
        asyncio_task_for_updating_scene: asyncio.Task = asyncio.create_task(
            coroutine_for_updating_scene
        )
        logger.info("Created new asyncio task for updating scene. Saving it.")
        cl.user_session.set(
            "asyncio_task_for_updating_scene",
            asyncio_task_for_updating_scene,
        )
        logger.info("Saved asyncio task for updating scene to user session.")
