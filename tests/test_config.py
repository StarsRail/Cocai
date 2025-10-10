from config import AppConfig


def test_config_defaults(monkeypatch):
    # Clear potentially set vars
    for k in [
        "OPENAI_API_KEY",
        "TOGETHER_AI_API_KEY",
        "MEM0_API_KEY",
        "DISABLE_MEMORY",
        "SHOULD_PREREAD_GAME_MODULE",
    ]:
        monkeypatch.delenv(k, raising=False)
    cfg = AppConfig.from_env({})
    assert cfg.llm_provider == "ollama"
    assert cfg.game_module_path.endswith("Clean-Up-Aisle-Four")
    assert cfg.should_preread_game_module is False
    assert cfg.disable_memory is False
    assert cfg.enable_auto_history_update is True


def test_config_llm_precedence_openai_over_together(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai")
    monkeypatch.setenv("TOGETHER_AI_API_KEY", "sk-together")
    cfg = AppConfig.from_env()
    assert cfg.llm_provider == "openai"


def test_config_llm_precedence_together_over_ollama(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("TOGETHER_AI_API_KEY", "sk-together")
    cfg = AppConfig.from_env()
    assert cfg.llm_provider == "together"


def test_config_preread_flag(monkeypatch):
    monkeypatch.setenv("SHOULD_PREREAD_GAME_MODULE", "yes")
    cfg = AppConfig.from_env()
    assert cfg.should_preread_game_module is True


def test_config_memory_disable(monkeypatch):
    monkeypatch.setenv("DISABLE_MEMORY", "1")
    cfg = AppConfig.from_env()
    assert cfg.disable_memory is True


def test_config_mem0(monkeypatch):
    monkeypatch.delenv("DISABLE_MEMORY", raising=False)
    monkeypatch.setenv("MEM0_API_KEY", "mem0-key")
    cfg = AppConfig.from_env()
    assert cfg.mem0_api_key == "mem0-key"
