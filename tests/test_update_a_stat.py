import pytest

from agentic_tools.misc import update_a_stat


def test_update_a_stat_diff():
    # Ensure only diff provided; value left as None explicitly
    msg = update_a_stat(stat_name="STR", diff=5, value=None)
    assert "diff=5" in msg


def test_update_a_stat_value():
    msg = update_a_stat(stat_name="DEX", value=12, diff=None)
    assert "value=12" in msg


@pytest.mark.parametrize(
    "kwargs",
    [
        {},  # neither provided
        {"diff": 1, "value": 2},  # both provided
    ],
)
def test_update_a_stat_validation_errors(kwargs):
    with pytest.raises(ValueError):
        update_a_stat("INT", **kwargs)  # type: ignore[arg-type]
