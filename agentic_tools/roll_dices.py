import logging
import random

# How to use enums in Python: https://docs.python.org/3/howto/enum.html
from enum import IntEnum

import chainlit as cl
from llama_index.core.workflow import Context
from pydantic import Field


def roll_a_dice(
    n: int = Field(description="number of faces of the dice to roll", gt=0, le=100),
) -> int:
    """
    Roll an n-faced dice and return the result.
    """
    return random.randint(1, int(n))


class DegreesOfSuccess(IntEnum):
    FUMBLE = 0
    FAIL = 1
    SUCCESS = 2
    HARD_SUCCESS = 3
    EXTREME_SUCCESS = 4
    CRITICAL_SUCCESS = 5


class Difficulty(IntEnum):
    """
    For tasks:
    > A regular task requires a roll of equal to or less than your skill value on 1D100 (a Regular success).
    > A difficult task requires a roll result equal to or less than half your skill value (a Hard success).
    > A task approaching the limits of human capability requires a roll equal to or less than one-fifth of your skill
    >   value (an Extreme success).

    ([source](https://cthulhuwiki.chaosium.com/rules/game-system.html#skill-rolls-and-difficulty-levels))


    For opposed rolls:
    - Regular: Opposing skill/characteristic is below 50.
    - Hard: Opposing skill/characteristic is equal to or above 50.
    - Extreme: Opposing skill/characteristic is equal to or above 90.

    ([source](https://trpgline.com/en/rules/coc7/summary))
    """

    REGULAR = 0
    DIFFICULT = 1
    EXTREME = 2


def __map_dice_outcome_to_degree_of_success(
    difficulty: Difficulty, result: int, skill_value: int
) -> DegreesOfSuccess:
    if result == 100:
        return DegreesOfSuccess.FUMBLE
    if result == 1:
        return DegreesOfSuccess.CRITICAL_SUCCESS
    result_ignoring_difficulty = DegreesOfSuccess.FAIL
    if result <= skill_value // 5:
        result_ignoring_difficulty = DegreesOfSuccess.EXTREME_SUCCESS
    elif result <= skill_value // 2:
        result_ignoring_difficulty = DegreesOfSuccess.HARD_SUCCESS
    elif result <= skill_value:
        result_ignoring_difficulty = DegreesOfSuccess.SUCCESS
    # Now, we consider the difficulty.
    if difficulty == Difficulty.REGULAR:
        return result_ignoring_difficulty
    elif difficulty == Difficulty.DIFFICULT:
        if result_ignoring_difficulty >= DegreesOfSuccess.HARD_SUCCESS:
            return result_ignoring_difficulty
        # else, fall through to return a FAIL.
    elif difficulty == Difficulty.EXTREME:
        if result_ignoring_difficulty == DegreesOfSuccess.EXTREME_SUCCESS:
            return result_ignoring_difficulty
        # else, fall through to return a FAIL.
    return DegreesOfSuccess.FAIL


async def roll_a_skill(
    ctx: Context,
    skill_value: int = Field(description="skill value", ge=0, le=100),
    difficulty: Difficulty = Field(
        description="difficulty level", default=Difficulty.REGULAR
    ),
) -> str:
    """
    Roll a skill check and check the result.
    """
    logger = logging.getLogger("roll_a_skill")
    # Roll the dice.
    dice_outcome = random.randint(1, 100)
    tenth_digit = dice_outcome // 10
    if tenth_digit == 0:
        tenth_digit = 10
    ones_digit = dice_outcome % 10
    if ones_digit == 0:
        ones_digit = 10

    # Send a fake PDF with the dice-rolling scene.
    try:
        scene = cl.Pdf(
            name="fake-pdf",
            display="inline",
            url=f"/roll_dice?d10={tenth_digit}&d10={ones_digit}",
            # Prevent the default factory from being triggered by giving it a value explicitly.
            thread_id=await ctx.store.get("user_message_thread_id", "unknown"),
        )
        message = cl.Message(
            content="",
            author="roll_a_skill",
            elements=[scene],
            parent_id=await ctx.store.get("user_message_id", None),
        )
        await message.send()
    except Exception as e:
        logger.error(f"Failed to send the scene: {e}")

    # Describe the result.
    result = __map_dice_outcome_to_degree_of_success(
        difficulty, dice_outcome, int(skill_value)
    )
    return f"You rolled a {dice_outcome}. That's a {result.name.lower().replace('_', ' ')}!"
