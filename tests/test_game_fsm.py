import pytest
from statemachine.exceptions import TransitionNotAllowed

from agents.game_fsm import GameFSM


def test_fsm_starts_in_character_creation():
    fsm = GameFSM()
    assert fsm.get_current_phase() == "character_creation"
    assert fsm.get_current_phase_emoji() == "📋"


def test_fsm_transitions_to_adventure_when_pc_exists():
    fsm = GameFSM()
    fsm.send("start_adventure", pc_exists=True)

    assert fsm.get_current_phase() == "adventure"
    assert fsm.get_current_phase_name() == "Adventure"


def test_fsm_blocks_adventure_transition_without_pc():
    fsm = GameFSM()

    with pytest.raises(TransitionNotAllowed):
        fsm.send("start_adventure", pc_exists=False)

    assert fsm.get_current_phase() == "character_creation"


def test_fsm_invalid_transition_from_character_creation_to_combat():
    fsm = GameFSM()

    with pytest.raises(TransitionNotAllowed):
        fsm.send("enter_combat", combat_triggered=True)

    assert fsm.get_current_phase() == "character_creation"
