from types import SimpleNamespace

from async_panes.async_panes_utils import build_transcript, format_transcript


class DummyMemory:
    def __init__(self, items):
        self._items = items

    def get_all(self):
        return list(self._items)


def test_build_transcript_basic_roles():
    mem = DummyMemory(
        [
            SimpleNamespace(role="user", content="Hello"),
            SimpleNamespace(role="assistant", content="Hi there"),
            {"role": "human", "content": "Where are we?"},
            {"role": "tool", "content": "irrelevant tool output"},
        ]
    )
    t = build_transcript(mem)
    # Normalizes roles to user/agent
    assert t[0]["role"] == "user"
    assert t[1]["role"] == "agent"
    assert t[2]["role"] == "user"
    assert t[3]["role"] == "agent"


def test_build_transcript_appends_latest_exchange():
    mem = DummyMemory([SimpleNamespace(role="user", content="A")])
    t = build_transcript(mem, last_user_msg="B", last_agent_msg="C")
    assert t[-2:] == [
        {"role": "user", "content": "B"},
        {"role": "agent", "content": "C"},
    ]


def test_format_transcript_prefixes():
    transcript = [
        {"role": "user", "content": "Ask"},
        {"role": "agent", "content": "Reply"},
    ]
    s = format_transcript(transcript)
    assert s.splitlines()[0].startswith("User:")
    assert s.splitlines()[1].startswith("Keeper:")
