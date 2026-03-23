import io

import pytest

import agents.agent_factory as agent_factory_module
from agents.agent_factory import AgentFactory
from game_state.data_models import GamePhase


class DummyFunctionAgent:
    def __init__(self, system_prompt, memory):
        self.system_prompt = system_prompt
        self.memory = memory
        self.tool_retriever = None


def test_load_system_prompt_uses_cache(monkeypatch):
    factory = AgentFactory()
    opened = []

    def fake_exists(self):
        return str(self).endswith("character_creation_prompt.md")

    def fake_open(path, *args, **kwargs):
        path_str = str(path)
        opened.append(path_str)
        if path_str == "prompts/character_creation_prompt.md":
            return io.StringIO("character prompt")
        if path_str == "prompts/system_prompt.md":
            return io.StringIO("default prompt")
        raise AssertionError(f"Unexpected path opened: {path_str}")

    monkeypatch.setattr(agent_factory_module.Path, "exists", fake_exists)
    monkeypatch.setattr("builtins.open", fake_open)

    first = factory._load_system_prompt(GamePhase.CHARACTER_CREATION)
    second = factory._load_system_prompt(GamePhase.CHARACTER_CREATION)

    assert first == "character prompt"
    assert second == "character prompt"
    assert opened == ["prompts/character_creation_prompt.md"]


def test_load_system_prompt_falls_back_to_default_when_missing(monkeypatch):
    factory = AgentFactory()

    def fake_exists(self):
        return False

    def fake_open(path, *args, **kwargs):
        if str(path) == "prompts/system_prompt.md":
            return io.StringIO("default prompt")
        raise AssertionError(f"Unexpected path opened: {path}")

    monkeypatch.setattr(agent_factory_module.Path, "exists", fake_exists)
    monkeypatch.setattr("builtins.open", fake_open)

    prompt = factory._load_system_prompt(GamePhase.ADVENTURE)

    assert prompt == "default prompt"


def test_get_tool_retriever_for_phase_returns_expected_retriever_types():
    factory = AgentFactory()

    cc_retriever = factory._get_tool_retriever_for_phase(
        GamePhase.CHARACTER_CREATION, object()
    )
    adventure_retriever = factory._get_tool_retriever_for_phase(
        GamePhase.ADVENTURE, object()
    )

    assert cc_retriever.__class__.__name__ == "CharacterCreationToolRetriever"
    assert adventure_retriever.__class__.__name__ == "AdventureToolRetriever"


def test_get_tool_retriever_for_phase_raises_for_invalid_phase():
    factory = AgentFactory()

    class FakePhase:
        value = "invalid-phase"

    with pytest.raises(ValueError):
        factory._get_tool_retriever_for_phase(FakePhase(), object())  # type: ignore[arg-type]


def test_create_agent_for_phase_sets_prompt_memory_and_retriever(monkeypatch):
    factory = AgentFactory()
    fake_memory = object()
    fake_ctx = object()
    fake_retriever = object()

    monkeypatch.setattr(agent_factory_module, "FunctionAgent", DummyFunctionAgent)
    monkeypatch.setattr(
        factory,
        "_load_system_prompt",
        lambda phase: "phase prompt",
    )
    monkeypatch.setattr(
        factory,
        "_get_tool_retriever_for_phase",
        lambda phase, ctx: fake_retriever,
    )

    agent = factory.create_agent_for_phase(
        GamePhase.CHARACTER_CREATION,
        fake_ctx,  # type: ignore[arg-type]
        fake_memory,  # type: ignore[arg-type]
    )

    assert isinstance(agent, DummyFunctionAgent)
    assert agent.system_prompt == "phase prompt"
    assert agent.memory is fake_memory
    assert agent.tool_retriever is fake_retriever
