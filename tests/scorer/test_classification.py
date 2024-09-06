import pytest
from test_helpers.utils import simple_task_state

from inspect_ai.scorer import Target
from inspect_ai.scorer._classification import exact, f1
from inspect_ai.scorer._metric import CORRECT, INCORRECT


@pytest.mark.asyncio
async def test_exact_match():
    scorer = exact()
    state = simple_task_state(model_output="foo")
    result = await scorer(state, Target(["foo"]))

    assert result.text == CORRECT


@pytest.mark.asyncio
async def test_exact_match_max():
    scorer = exact()
    state = simple_task_state(model_output="foo")
    result = await scorer(state, Target(["foobar", "boofar", "foo"]))

    assert result.text == CORRECT


@pytest.mark.asyncio
async def test_exact_nonmatch():
    scorer = exact()
    state = simple_task_state(model_output="foo1")
    result = await scorer(state, Target(["foo"]))

    assert result.text == INCORRECT


@pytest.mark.asyncio
async def test_f1_basic_match():
    scorer = f1()
    state = simple_task_state(model_output="foo")
    result = await scorer(state, Target(["foo"]))

    assert result.text == "1.0"


@pytest.mark.asyncio
async def test_f1_basic_nonmatch():
    scorer = f1()
    state = simple_task_state(model_output="foo1")
    result = await scorer(state, Target(["foo"]))

    assert result.text == "0.0"


@pytest.mark.asyncio
async def test_f1_good_match():
    scorer = f1()
    state = simple_task_state(model_output="Paris")
    result = await scorer(state, Target(["Paris, Texas", "Paris"]))

    assert result.text == "1.0"


@pytest.mark.asyncio
async def test_f1_partial_match():
    scorer = f1()
    state = simple_task_state(model_output="Paris")
    result = await scorer(state, Target(["Paris, Texas"]))

    assert result.text == "0.67"
