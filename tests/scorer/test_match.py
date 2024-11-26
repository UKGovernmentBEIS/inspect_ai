import pytest
from test_helpers.utils import simple_task_state

from inspect_ai.scorer import CORRECT, Target, match


@pytest.mark.asyncio
async def test_number_eol():
    scorer = match(numeric=True)
    state = simple_task_state(model_output="28 + 32 = 60\nThis solves the problem.")
    result = await scorer(state, Target(["60"]))

    assert result.text == CORRECT
