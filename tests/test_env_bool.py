from agentic_tools.misc import env_flag


def test_env_bool_helper_true(monkeypatch):
    monkeypatch.setenv("SHOULD_REUSE_EXISTING_INDEX", "1")
    assert env_flag("SHOULD_REUSE_EXISTING_INDEX") is True
    monkeypatch.setenv("SHOULD_REUSE_EXISTING_INDEX", "true")
    assert env_flag("SHOULD_REUSE_EXISTING_INDEX") is True
    monkeypatch.setenv("SHOULD_REUSE_EXISTING_INDEX", "on")
    assert env_flag("SHOULD_REUSE_EXISTING_INDEX") is True


def test_env_bool_helper_false(monkeypatch):
    monkeypatch.setenv("SHOULD_REUSE_EXISTING_INDEX", "0")
    assert env_flag("SHOULD_REUSE_EXISTING_INDEX") is False
    monkeypatch.setenv("SHOULD_REUSE_EXISTING_INDEX", "false")
    assert env_flag("SHOULD_REUSE_EXISTING_INDEX") is False
    monkeypatch.setenv("SHOULD_REUSE_EXISTING_INDEX", "off")
    assert env_flag("SHOULD_REUSE_EXISTING_INDEX") is False
