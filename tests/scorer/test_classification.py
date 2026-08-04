import pytest
from test_helpers.utils import simple_task_state

from inspect_ai.scorer import Target
from inspect_ai.scorer._classification import exact, f1, max_exact_score, max_f1_score
from inspect_ai.scorer._metric import CORRECT, INCORRECT


@pytest.mark.anyio
async def test_exact_match():
    scorer = exact()
    state = simple_task_state(model_output="foo")
    result = await scorer(state, Target(["foo"]))

    assert result.text == CORRECT


@pytest.mark.anyio
async def test_exact_match_max():
    scorer = exact()
    state = simple_task_state(model_output="foo")
    result = await scorer(state, Target(["foobar", "boofar", "foo"]))

    assert result.text == CORRECT


@pytest.mark.anyio
async def test_exact_nonmatch():
    scorer = exact()
    state = simple_task_state(model_output="foo1")
    result = await scorer(state, Target(["foo"]))

    assert result.text == INCORRECT


@pytest.mark.anyio
async def test_f1_basic_match():
    scorer = f1()
    state = simple_task_state(model_output="foo")
    result = await scorer(state, Target(["foo"]))

    assert result.text == "1.0"


@pytest.mark.anyio
async def test_f1_basic_nonmatch():
    scorer = f1()
    state = simple_task_state(model_output="foo1")
    result = await scorer(state, Target(["foo"]))

    assert result.text == "0.0"


@pytest.mark.anyio
async def test_f1_good_match():
    scorer = f1()
    state = simple_task_state(model_output="Paris")
    result = await scorer(state, Target(["Paris, Texas", "Paris"]))

    assert result.text == "1.0"


@pytest.mark.anyio
async def test_f1_partial_match():
    scorer = f1()
    state = simple_task_state(model_output="Paris")
    result = await scorer(state, Target(["Paris, Texas"]))

    assert result.text == "0.67"


@pytest.mark.anyio
async def test_stop_words():
    scorer = f1(stop_words=["Paris"])
    state = simple_task_state(model_output="Paris")
    result = await scorer(state, Target(["Paris, Texas"]))

    assert result.text == "0.0"


@pytest.mark.anyio
async def test_stop_words2():
    scorer = f1(stop_words=["Texas"])
    state = simple_task_state(model_output="Paris")
    result = await scorer(state, Target(["Paris, Texas"]))

    assert result.text == "1.0"


def test_max_score_target_leading_whitespace():
    # Targets with leading whitespace must not be silently skipped — the
    # whole target string is checked, not just its first character.
    assert max_f1_score("hello", [" hello"]) == 1.0
    assert max_exact_score("hello", [" hello"]) == 1.0


def test_max_score_empty_target_no_index_error():
    # An empty target string should be skipped, not raise IndexError.
    assert max_f1_score("hello", [""]) == 0.0
    assert max_exact_score("hello", [""]) == 0.0
    assert max_f1_score("hello", ["", "hello"]) == 1.0


@pytest.mark.anyio
async def test_f1_decimal_number_with_punctuation():
    scorer = f1()
    state1 = simple_task_state(model_output="(3.14)")
    result1 = await scorer(state1, Target(["3.14"]))
    assert result1.text == "1.0"

    state2 = simple_task_state(model_output="The answer is 3.14.")
    result2 = await scorer(state2, Target(["3.14"]))
    assert result2.text == "0.5"


@pytest.mark.anyio
async def test_exact_decimal_number_with_punctuation():
    scorer = exact()
    state = simple_task_state(model_output="(3.14)")
    result = await scorer(state, Target(["3.14"]))

    assert result.text == CORRECT


def test_remove_punc_preserves_existing_normalization():
    # Boundary stripping applies only when it rescues a number — all other
    # tokens keep the remove-all-punctuation semantics.
    assert max_exact_score("3,000", ["3000"]) == 1.0
    assert max_exact_score("$1,000.", ["1000"]) == 1.0
    assert max_exact_score("don't", ["dont"]) == 1.0
    assert max_exact_score("U.S.", ["US"]) == 1.0


def test_max_exact_score_word_order_and_duplicates():
    # max_exact_score must preserve word order and count (not compare word sets)
    assert max_exact_score("world hello", ["hello world"]) == 0.0
    assert max_exact_score("hello hello", ["hello"]) == 0.0
