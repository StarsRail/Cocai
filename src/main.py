#!/usr/bin/env python
import hmac
import logging
import os
from contextvars import copy_context
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
from openinference.semconv.trace import (
    OpenInferenceMimeTypeValues,
    OpenInferenceSpanKindValues,
    SpanAttributes,
)
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from agents.agent_factory import AgentFactory
from agents.game_fsm import get_game_fsm
from async_panes.history import update_history_if_needed
from async_panes.pane_update_manager import BackgroundPaneUpdateManager
from async_panes.scene import update_scene_if_needed
from config import AppConfig
from game_state.data_models import GamePhase, GameState
from game_state.load_and_save import load_game_state
from utils import (
    build_llama_index_llm,
    get_llm_provider_display_name,
    set_up_data_layer,
)

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


@cl.data_layer
def get_data_layer():
    return set_up_data_layer()


@cl.password_auth_callback
def auth_callback(username: str, password: str) -> cl.User | None:
    """Authenticate users for Chainlit using env-configured credentials.

    Required env vars:
    - CHAINLIT_AUTH_USERNAME
    - CHAINLIT_AUTH_PASSWORD
    """
    expected_username = os.getenv("CHAINLIT_AUTH_USERNAME", "")
    expected_password = os.getenv("CHAINLIT_AUTH_PASSWORD", "")

    if not expected_username or not expected_password:
        logger.warning(
            "Auth callback enabled but CHAINLIT_AUTH_USERNAME/CHAINLIT_AUTH_PASSWORD are not configured. Denying login."
        )
        return None

    valid_user = hmac.compare_digest(username, expected_username)
    valid_pass = hmac.compare_digest(password, expected_password)
    if not (valid_user and valid_pass):
        return None

    return cl.User(
        identifier=username,
        metadata={"auth_provider": "password", "role": "player"},
    )


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


def set_up_llama_index(app_config: AppConfig) -> None:
    """
    One-time setup code for shared objects across all AgentRunners.

    Returns the system prompt string configured for the agent.
    """
    logger = logging.getLogger("set_up_llama_index")
    # ============= Beginning of the code block for wiring on to models. =============
    # At least when Chainlit is involved, LLM initializations must happen upon the `@cl.on_chat_start` event,
    # not in the global scope.
    # Otherwise, it messes up with Arize Phoenix: LLM calls won't be captured as parts of an Agent Step.

    Settings.llm = build_llama_index_llm(app_config)
    provider_name = get_llm_provider_display_name(app_config)
    logger.info(f"Using {provider_name}.")

    Settings.embed_model = OllamaEmbedding(
        model_name=app_config.ollama_embed_model_id,
        base_url=app_config.ollama_base_url,
    )
    # ============= End of the code block for wiring on to models. =============

    # Needed for "Retrieved the following sources" to show up on Chainlit.
    # This procedure will register Chainlit's callback manager, which will require Chainlit's context variables to
    # be ready before receiving an event, so it should be called AFTER calling the tool.
    Settings.callback_manager = create_callback_manager()


@cl.set_starters
async def set_starters(
    user: cl.User | None = None, default_path: str | None = None
) -> list[cl.Starter]:
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
async def factory() -> None:
    # Build LLMs/tools and prompts per session to avoid global background resources
    app_config = AppConfig.from_env()
    set_up_llama_index(app_config)

    # Each chat session should have its own agent runner, because each chat session has different chat histories.
    key = cl.user_session.get("id")
    agent_memory = __prepare_memory(key, app_config)

    # User-visible game state includes things like the player character, a brief summary of the story so far, clues & items discovered, etc.
    # Try to load persisted game state from storage; if none exists, create a new one
    user_visible_game_state = await load_game_state()
    if user_visible_game_state is None:
        logger.info("No persisted game state found; creating a new session.")
        user_visible_game_state = GameState()
    else:
        logger.info("Loaded persisted game state.")

    # Make agent aware of the user-visible game state.
    agent_ctx = Context(None)  # Context without an agent initially
    async with agent_ctx.store.edit_state() as ctx_state:
        ctx_state["user-visible"] = user_visible_game_state

    # Initialize AgentFactory for phase-specific agents
    agent_factory = AgentFactory()

    # Create initial agent for the current phase
    current_phase = user_visible_game_state.phase
    agent = agent_factory.create_agent_for_phase(current_phase, agent_ctx, agent_memory)

    # Update context to reference the agent (needed for some tool bindings)
    agent_ctx.agent = agent

    # Initialize FSM (tracks game phase state)
    game_fsm = get_game_fsm()

    # Store in user session for message handling
    cl.user_session.set("agent", agent)
    cl.user_session.set("agent_ctx", agent_ctx)
    cl.user_session.set("agent_memory", agent_memory)
    cl.user_session.set("app_config", app_config)
    cl.user_session.set("agent_factory", agent_factory)
    cl.user_session.set("game_fsm", game_fsm)

    # Initialize pane update manager for this session
    cl.user_session.set("pane_update_manager", BackgroundPaneUpdateManager())

    # Send the initial game state to the parent window via Chainlit window messaging
    game_state_dict = user_visible_game_state.to_dict()
    await cl.send_window_message(
        {"type": "history", "history": game_state_dict.get("history", "")}
    )
    await cl.send_window_message(
        {"type": "clues", "clues": game_state_dict.get("clues", [])}
    )
    if game_state_dict.get("illustration_url"):
        await cl.send_window_message(
            {"type": "illustration", "url": game_state_dict.get("illustration_url")}
        )
    await cl.send_window_message({"type": "pc", "pc": game_state_dict.get("pc", {})})

    logger.info(
        f"✅ Set up agent for phase: {current_phase.emoji()} {current_phase.value}"
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
        from utils import build_mem0_llm_config

        mem0_config = {
            "version": "v1.1",
            "vector_store": {
                "provider": "qdrant",
                "config": {
                    "collection_name": app_config.qdrant_collection,
                    "embedding_model_dims": 768,
                    "host": app_config.qdrant_host,
                    "port": app_config.qdrant_port,
                },
            },
            "embedder": {
                "provider": "ollama",
                "config": {
                    "model": app_config.ollama_embed_model_id,
                    "ollama_base_url": app_config.ollama_base_url,
                    "embedding_dims": 768,
                },
            },
            "llm": build_mem0_llm_config(app_config),
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
        if manager := cl.user_session.get("pane_update_manager"):
            manager.cancel_all()
    except Exception as e:
        logger.warning(f"Cleanup encountered an issue: {e}")


@cl.on_chat_resume
async def on_chat_resume(thread):
    """Resume a previously persisted conversation.

    Chainlit calls this when a user resumes an existing thread.
    We restore the agent, game state, and memory.
    """
    logger = logging.getLogger("on_chat_resume")
    logger.info(f"Resuming chat session from thread {thread.get('id')}")

    # Build LLMs/tools and prepare for phase-based agents
    app_config = AppConfig.from_env()
    set_up_llama_index(app_config)

    # Restore memory
    key = cl.user_session.get("id")
    agent_memory = __prepare_memory(key, app_config)

    # Load persisted game state from thread metadata
    game_state_dict = thread.metadata.get("game_state") if thread.metadata else None
    if game_state_dict:
        logger.info("Restoring persisted game state")
        user_visible_game_state = GameState.from_dict(game_state_dict)
    else:
        logger.info("No game state found in thread; creating fresh state")
        user_visible_game_state = GameState()

    # Restore agent context with game state
    agent_ctx = Context(None)  # Context without an agent initially
    async with agent_ctx.store.edit_state() as ctx_state:
        ctx_state["user-visible"] = user_visible_game_state

    # Initialize AgentFactory for phase-specific agents
    agent_factory = AgentFactory()

    # Create phase-appropriate agent
    current_phase = user_visible_game_state.phase
    agent = agent_factory.create_agent_for_phase(current_phase, agent_ctx, agent_memory)

    # Update context to reference the agent
    agent_ctx.agent = agent

    # Initialize FSM
    game_fsm = get_game_fsm()

    # Store in user session
    cl.user_session.set("agent", agent)
    cl.user_session.set("agent_ctx", agent_ctx)
    cl.user_session.set("agent_memory", agent_memory)
    cl.user_session.set("app_config", app_config)
    cl.user_session.set("agent_factory", agent_factory)
    cl.user_session.set("game_fsm", game_fsm)

    # Initialize pane update manager
    cl.user_session.set("pane_update_manager", BackgroundPaneUpdateManager())

    # Send initial game state to the parent window via Chainlit window messaging
    game_state_dict = user_visible_game_state.to_dict()
    await cl.send_window_message(
        {"type": "history", "history": game_state_dict.get("history", "")}
    )
    await cl.send_window_message(
        {"type": "clues", "clues": game_state_dict.get("clues", [])}
    )
    if game_state_dict.get("illustration_url"):
        await cl.send_window_message(
            {"type": "illustration", "url": game_state_dict.get("illustration_url")}
        )
    await cl.send_window_message({"type": "pc", "pc": game_state_dict.get("pc", {})})

    logger.info(
        f"✅ Chat session resumed successfully; current phase: {current_phase.emoji()} {current_phase.value}"
    )


def _build_guardrail_context(game_state: GameState) -> str:
    """Return a bracketed context block injected before the player's message.

    This gives the LLM phase-aware reminders every turn so it doesn't
    forget critical rules (e.g. no adventure without a character sheet).
    """
    parts: list[str] = []

    if game_state.phase == GamePhase.CHARACTER_CREATION or game_state.pc is None:
        parts.append(
            "[KEEPER NOTES — The player does NOT have a character yet. "
            "You MUST guide them to create one using the `create_character` tool "
            "before starting any in-game scenes or investigation. "
            "Do not narrate plot events until a character exists.]"
        )
    else:
        # Summarize the PC so the LLM remembers who the investigator is.
        pc_dict = game_state.to_dict().get("pc", {})
        name = pc_dict.get("name", "Unknown")
        parts.append(f"[KEEPER NOTES — Current investigator: {name}.]")

    # Universal reminder every turn (cheap but effective).
    parts.append(
        "[RULE REMINDER — NEVER fabricate dice outcomes. "
        "ALL skill checks and rolls MUST use the `roll_a_skill` or `roll_a_dice` tool.]"
    )

    return "\n".join(parts)


@cl.on_message
async def handle_message_from_user(message: cl.Message):
    logger = logging.getLogger("handle_message_from_user")
    with tracer.start_as_current_span("chat.turn") as turn_span:
        user_input = message.content or ""
        turn_span.set_attribute(
            SpanAttributes.OPENINFERENCE_SPAN_KIND,
            OpenInferenceSpanKindValues.CHAIN.value,
        )
        turn_span.set_attribute(SpanAttributes.INPUT_VALUE, user_input)
        turn_span.set_attribute(
            SpanAttributes.INPUT_MIME_TYPE,
            OpenInferenceMimeTypeValues.TEXT.value,
        )
        turn_span.set_attribute("chat.turn.message_id", str(message.id))
        turn_span.set_attribute("chat.turn.thread_id", str(message.thread_id))

        try:
            manager: BackgroundPaneUpdateManager | None = cl.user_session.get(
                "pane_update_manager"
            )
            if manager is None:
                manager = BackgroundPaneUpdateManager()
                cl.user_session.set("pane_update_manager", manager)
            # Advance generation for this new user message (cancels per-pane when rescheduling)
            gen = manager.advance_generation()
            turn_span.set_attribute("chat.turn.generation", gen)

            agent: FunctionAgent = cl.user_session.get("agent")
            if agent is None or not isinstance(agent, FunctionAgent):
                await cl.Message(
                    content="Agent not found. Please restart the chat session."
                ).send()
                turn_span.set_status(Status(StatusCode.ERROR, "missing agent"))
                return

            agent_ctx: Context = cl.user_session.get("agent_ctx")
            if agent_ctx is None or not isinstance(agent_ctx, Context):
                await cl.Message(
                    content="Agent context not found. Please restart the chat session."
                ).send()
                turn_span.set_status(Status(StatusCode.ERROR, "missing agent context"))
                return

            agent_memory: Memory | Mem0Memory = cl.user_session.get("agent_memory")
            if agent_memory is None or not isinstance(
                agent_memory, (Memory, Mem0Memory)
            ):
                await cl.Message(
                    content="Agent memory not found. Please restart the chat session."
                ).send()
                turn_span.set_status(Status(StatusCode.ERROR, "missing agent memory"))
                return

            config: AppConfig = cl.user_session.get("app_config")
            if config is None or not isinstance(config, AppConfig):
                await cl.Message(
                    content="AppConfig not found. Please restart the chat session."
                ).send()
                turn_span.set_status(Status(StatusCode.ERROR, "missing app config"))
                return

            # Save the user message ID and thread ID to the context state, so that tools can use them.
            async with agent_ctx.store.edit_state() as ctx_state:
                # Don't use `message` directly, because it is not serializable (by the default serializer of `DictState`, probably).
                ctx_state["user_message_id"] = message.id
                ctx_state["user_message_thread_id"] = message.thread_id

            # Get current game state (for phase transition detection)
            game_state: GameState = await agent_ctx.store.get("user-visible")
            old_phase = game_state.phase

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
            turn_span.set_attribute(SpanAttributes.OUTPUT_VALUE, agent_text)
            turn_span.set_attribute(
                SpanAttributes.OUTPUT_MIME_TYPE,
                OpenInferenceMimeTypeValues.TEXT.value,
            )

            task_context = copy_context()
            if config.enable_auto_history_update:
                manager.schedule(
                    "history",
                    gen,
                    lambda: update_history_if_needed(
                        ctx=agent_ctx,
                        memory=agent_memory,
                        last_user_msg=message.content,
                        last_agent_msg=agent_text,
                    ),
                    timeout=60.0,
                    debounce=0.15,
                    task_context=task_context,
                )
                logger.info("Scheduled background history update (gen=%s)", gen)

            if config.enable_auto_scene_update:
                manager.schedule(
                    "scene",
                    gen,
                    lambda: update_scene_if_needed(
                        ctx=agent_ctx,
                        memory=agent_memory,
                        last_user_msg=message.content,
                        last_agent_msg=agent_text,
                    ),
                    timeout=120.0,
                    debounce=0.15,
                    task_context=task_context,
                )
                logger.info("Scheduled background scene update (gen=%s)", gen)

            turn_span.set_status(Status(StatusCode.OK))

            # Check if game phase transitioned during agent execution
            game_state_after: GameState = await agent_ctx.store.get("user-visible")
            new_phase = game_state_after.phase
            if new_phase != old_phase:
                logger.info(
                    f"🔄 Phase transition detected: {old_phase.emoji()} {old_phase.value} → {new_phase.emoji()} {new_phase.value}"
                )
                # Get the stored factory and FSM
                agent_factory: AgentFactory = cl.user_session.get("agent_factory")
                if agent_factory:
                    # Create new agent for the new phase
                    new_agent = agent_factory.create_agent_for_phase(
                        new_phase, agent_ctx, agent_memory
                    )
                    # Update session storage with new agent
                    cl.user_session.set("agent", new_agent)
                    logger.info(
                        f"✅ Agent swapped for new phase: {new_phase.emoji()} {new_phase.value}"
                    )
                else:
                    logger.warning(
                        "AgentFactory not found in session; cannot swap agent"
                    )

        except Exception as e:
            turn_span.set_status(Status(StatusCode.ERROR, str(e)))
            turn_span.record_exception(e)
            raise
