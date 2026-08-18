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


# --- location="exact" strictness ---------------------------------------------
# normalize_number must not silently truncate a value with trailing content
# to its numeric prefix (e.g. "5 some text" -> "5").


@pytest.mark.anyio
async def test_numeric_exact_rejects_trailing_text():
    scorer = match(numeric=True, location="exact")
    state = simple_task_state(model_output="5 some text")
    result = await scorer(state, Target(["5"]))

    assert result.text == INCORRECT


@pytest.mark.anyio
async def test_numeric_exact_rejects_trailing_alpha():
    scorer = match(numeric=True, location="exact")
    state = simple_task_state(model_output="5abc")
    result = await scorer(state, Target(["5"]))

    assert result.text == INCORRECT


@pytest.mark.anyio
async def test_numeric_exact_clean_match():
    scorer = match(numeric=True, location="exact")
    state = simple_task_state(model_output="5")
    result = await scorer(state, Target(["5"]))

    assert result.text == CORRECT


# --- unicode / sign-variant numbers in model output --------------------------
# The gate predicate must agree with the parser: any token the parser can
# turn into a finite number is recognised as a number token.


@pytest.mark.anyio
async def test_numeric_unicode_minus_in_output():
    # U+2212 MINUS SIGN, not ASCII hyphen-minus
    scorer = match(numeric=True)
    state = simple_task_state(model_output="answer: −5")
    result = await scorer(state, Target(["-5"]))

    assert result.text == CORRECT


@pytest.mark.anyio
async def test_numeric_vulgar_fraction_in_output():
    scorer = match(numeric=True)
    state = simple_task_state(model_output="the result is ½")
    result = await scorer(state, Target(["0.5"]))

    assert result.text == CORRECT


@pytest.mark.anyio
async def test_numeric_negative_vulgar_fraction_in_output():
    scorer = match(numeric=True, location="any")
    state = simple_task_state(model_output="got -½ as the result")
    result = await scorer(state, Target(["-0.5"]))

    assert result.text == CORRECT


@pytest.mark.anyio
async def test_numeric_mixed_fraction_in_output():
    scorer = match(numeric=True)
    state = simple_task_state(model_output="answer 2½")
    result = await scorer(state, Target(["2.5"]))

    assert result.text == CORRECT


@pytest.mark.anyio
async def test_numeric_chinese_numeral_in_output():
    scorer = match(numeric=True)
    state = simple_task_state(model_output="result: 三")
    result = await scorer(state, Target(["3"]))

    assert result.text == CORRECT


@pytest.mark.anyio
async def test_numeric_fullwidth_digits_in_output():
    scorer = match(numeric=True)
    state = simple_task_state(model_output="the answer is １２３")
    result = await scorer(state, Target(["123"]))

    assert result.text == CORRECT


# --- position-fragility guards ----------------------------------------------
# Before the fix, `first_number_normalized` fell back to words[0] when no
# token was recognised as a number, so a unicode token would only match
# when it happened to land at the scan's starting position. Both cases
# below must now match regardless of position.


@pytest.mark.anyio
async def test_numeric_unicode_minus_with_trailing_text():
    scorer = match(numeric=True)
    state = simple_task_state(model_output="the answer is -½ extra")
    result = await scorer(state, Target(["-0.5"]))

    assert result.text == CORRECT


@pytest.mark.anyio
async def test_numeric_unicode_minus_with_leading_text():
    scorer = match(numeric=True, location="begin")
    state = simple_task_state(model_output="leading text then -½")
    result = await scorer(state, Target(["-0.5"]))

    # location="begin" semantically means "the first number in the value",
    # not "the value must start with a number".
    assert result.text == CORRECT


# --- any unmatched returns raw output ---------------------------------------
# Counterpoint to test_numeric_any_answer_is_matched_number: when no number
# matches, fall back to the raw model output rather than an extracted form.


@pytest.mark.anyio
async def test_numeric_any_answer_when_no_match():
    scorer = match(numeric=True, location="any")
    state = simple_task_state(model_output="got 7 and 11")
    result = await scorer(state, Target(["25"]))

    assert result.text == INCORRECT
    assert result.answer == "got 7 and 11"
