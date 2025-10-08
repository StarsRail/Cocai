from agentic_tools.roll_dices import Difficulty, map_dice_outcome_to_degree_of_success


def test_degree_mapping_boundaries():
    mp = map_dice_outcome_to_degree_of_success
    # Critical success on 1 always
    assert mp(Difficulty.REGULAR, 1, 10).name == "CRITICAL_SUCCESS"
    # Fumble on 100 always
    assert mp(Difficulty.REGULAR, 100, 10).name == "FUMBLE"
    # Regular difficulty: thresholds
    assert mp(Difficulty.REGULAR, 50, 50).name == "SUCCESS"
    assert mp(Difficulty.REGULAR, 25, 50).name == "HARD_SUCCESS"
    assert mp(Difficulty.REGULAR, 10, 50).name == "EXTREME_SUCCESS"
    assert mp(Difficulty.REGULAR, 90, 50).name == "FAIL"
    # Difficult requires hard or better (<= half skill)
    assert mp(Difficulty.DIFFICULT, 25, 50).name == "HARD_SUCCESS"
    assert mp(Difficulty.DIFFICULT, 30, 50).name == "FAIL"
    # Extreme requires extreme only (<= one-fifth of skill)
    assert mp(Difficulty.EXTREME, 9, 50).name == "EXTREME_SUCCESS"
    assert mp(Difficulty.EXTREME, 10, 50).name == "EXTREME_SUCCESS"
    assert mp(Difficulty.EXTREME, 11, 50).name == "FAIL"
