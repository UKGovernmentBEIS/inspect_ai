import pytest
from test_helpers.utils import simple_task_state

from inspect_ai.scorer import CORRECT, INCORRECT, Target, match


@pytest.mark.anyio
async def test_number_eol():
    scorer = match(numeric=True)
    state = simple_task_state(model_output="28 + 32 = 60\nThis solves the problem.")
    result = await scorer(state, Target(["60"]))

    assert result.text == CORRECT


@pytest.mark.anyio
async def test_non_number_eol_markdown():
    scorer = match(numeric=True)
    state = simple_task_state(
        model_output="**ANSWER: 28 + 32 = 60**\nThis solves the problem."
    )
    result = await scorer(state, Target(["60"]))

    assert result.text == CORRECT


@pytest.mark.anyio
async def test_non_numeric_match():
    scorer = match(numeric=True, location="any")
    state = simple_task_state(model_output="28 + 32 = 60%\nThis solves the problem.")
    result = await scorer(state, Target(["60", "60%"]))

    assert result.text == CORRECT


@pytest.mark.anyio
async def test_non_numeric_match_end():
    scorer = match(numeric=True)
    state = simple_task_state(model_output="28 + 32 = 60%")
    result = await scorer(state, Target(["60%"]))

    assert result.text == CORRECT


@pytest.mark.anyio
async def test_non_numeric_match_plain():
    scorer = match(numeric=True)
    state = simple_task_state(model_output="28 + 32 = 60%")
    result = await scorer(state, Target(["32"]))

    assert result.text == CORRECT


@pytest.mark.anyio
async def test_numeric_end_no_digit_suffix_match():
    # "25" ends with "5" as a string, but 25 != 5 as a number
    scorer = match(numeric=True)
    state = simple_task_state(model_output="The answer is 25")
    result = await scorer(state, Target(["5"]))

    assert result.text == INCORRECT


@pytest.mark.anyio
async def test_numeric_end_no_digit_suffix_match_multidigit():
    scorer = match(numeric=True)
    state = simple_task_state(model_output="the value is 110")
    result = await scorer(state, Target(["10"]))

    assert result.text == INCORRECT


@pytest.mark.anyio
async def test_numeric_begin_no_digit_prefix_match():
    # "50" starts with "5" as a string, but 50 != 5 as a number
    scorer = match(numeric=True, location="begin")
    state = simple_task_state(model_output="50 is the answer")
    result = await scorer(state, Target(["5"]))

    assert result.text == INCORRECT


@pytest.mark.anyio
async def test_numeric_any_no_digit_substring_match():
    # "5" is a substring of "25", but no token equals 5
    scorer = match(numeric=True, location="any")
    state = simple_task_state(model_output="got 25 here")
    result = await scorer(state, Target(["5"]))

    assert result.text == INCORRECT


@pytest.mark.anyio
async def test_numeric_any_finds_number_in_middle():
    scorer = match(numeric=True, location="any")
    state = simple_task_state(model_output="first 7 then 25 then done")
    result = await scorer(state, Target(["25"]))

    assert result.text == CORRECT


@pytest.mark.anyio
async def test_numeric_any_answer_is_matched_number():
    # the Score.answer should be the matched number, not the full output
    scorer = match(numeric=True, location="any")
    state = simple_task_state(model_output="first 7 then 25 then done")
    result = await scorer(state, Target(["25"]))

    assert result.text == CORRECT
    assert result.answer == "25"


@pytest.mark.anyio
async def test_numeric_negative_target_wrong_sign():
    # target -5 must not match output 5
    scorer = match(numeric=True)
    state = simple_task_state(model_output="5")
    result = await scorer(state, Target(["-5"]))

    assert result.text == INCORRECT


@pytest.mark.anyio
async def test_numeric_negative_target_correct():
    scorer = match(numeric=True)
    state = simple_task_state(model_output="the result is -5")
    result = await scorer(state, Target(["-5"]))

    assert result.text == CORRECT


@pytest.mark.anyio
async def test_numeric_negative_target_correct_with_trailing_text():
    scorer = match(numeric=True)
    state = simple_task_state(model_output="the result is -5 exactly")
    result = await scorer(state, Target(["-5"]))

    assert result.text == CORRECT


@pytest.mark.anyio
async def test_numeric_decimal_target():
    scorer = match(numeric=True)
    state = simple_task_state(model_output="pi is approximately 3.14")
    result = await scorer(state, Target(["3.14"]))

    assert result.text == CORRECT


@pytest.mark.anyio
async def test_numeric_decimal_target_wrong():
    scorer = match(numeric=True)
    state = simple_task_state(model_output="pi is approximately 33.14")
    result = await scorer(state, Target(["3.14"]))

    assert result.text == INCORRECT


@pytest.mark.anyio
async def test_numeric_scientific_target():
    scorer = match(numeric=True)
    state = simple_task_state(model_output="the value is 1000")
    result = await scorer(state, Target(["1e3"]))

    assert result.text == CORRECT


@pytest.mark.anyio
async def test_numeric_normalization_preserved():
    # 2.0 should still match 2 after normalization
    scorer = match(numeric=True)
    state = simple_task_state(model_output="2.0")
    result = await scorer(state, Target(["2"]))

    assert result.text == CORRECT


@pytest.mark.anyio
async def test_numeric_negative_normalization():
    # -5.0 should match -5 after normalization
    scorer = match(numeric=True)
    state = simple_task_state(model_output="result: -5.0")
    result = await scorer(state, Target(["-5"]))

    assert result.text == CORRECT
