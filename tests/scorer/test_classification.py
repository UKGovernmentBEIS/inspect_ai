from decimal import Inexact, InvalidOperation, Rounded, localcontext
from pathlib import Path
from typing import Literal

import anyio
import pytest
from test_helpers.utils import simple_task_state

from inspect_ai import Task, eval_async, score_async
from inspect_ai.dataset import Sample
from inspect_ai.log import (
    EvalLog,
    read_eval_log_async,
    recompute_metrics,
    write_eval_log_async,
)
from inspect_ai.model import ChatMessage, GenerateConfig, ModelOutput, get_model
from inspect_ai.scorer import Target
from inspect_ai.scorer._classification import (
    _normalize_number,
    exact,
    f1,
    max_exact_score,
    max_f1_score,
)
from inspect_ai.scorer._metric import CORRECT, INCORRECT
from inspect_ai.solver import generate
from inspect_ai.tool import ToolChoice, ToolInfo


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


@pytest.mark.parametrize(
    "answer,target,exact_value,f1_value",
    [
        ("9007199254740992", "9007199254740993", INCORRECT, 0.0),
        ("9007199254740993", "9007199254740992", INCORRECT, 0.0),
        ("-9007199254740992", "-9007199254740993", INCORRECT, 0.0),
        ("1.00000000000000001", "1", INCORRECT, 0.0),
        (
            "1.0000000000000000000000000001",
            "1.0000000000000000000000000002",
            INCORRECT,
            0.0,
        ),
        ("0." + "0" * 400 + "1", "0." + "0" * 400 + "2", INCORRECT, 0.0),
        ("value 9007199254740993", "value 9007199254740992", INCORRECT, 0.5),
        ("(9007199254740993)", "9007199254740992", INCORRECT, 0.0),
        ("42", "43", INCORRECT, 0.0),
        ("9007199254740993", "9007199254740993", CORRECT, 1.0),
        ("+001.0000", "1", CORRECT, 1.0),
        ("0012300.000", "1.23e+4", CORRECT, 1.0),
        ("-1e+3", "-1000", CORRECT, 1.0),
        ("(-9007199254740993)", "-9007199254740993.0", CORRECT, 1.0),
        ("-0", "-0.00", CORRECT, 1.0),
        ("-0", "0", INCORRECT, 0.0),
        ("NaN", "nan", CORRECT, 1.0),
        ("inf", "infinity", INCORRECT, 0.0),
    ],
)
async def test_classification_numeric_precision(
    answer: str, target: str, exact_value: str, f1_value: float
) -> None:
    state = simple_task_state(model_output=answer)
    exact_result = await exact()(state, Target(target))
    f1_result = await f1()(state, Target(target))
    assert exact_result is not None
    assert f1_result is not None
    assert exact_result.value == exact_value
    assert f1_result.value == f1_value


async def test_classification_numeric_multiple_targets_and_stop_words() -> None:
    state = simple_task_state(model_output="9007199254740993")
    target = Target(["9007199254740992", "9007199254740993.0"])
    exact_result = await exact()(state, target)
    f1_result = await f1()(state, target)
    assert exact_result is not None
    assert f1_result is not None
    assert exact_result.value == CORRECT
    assert f1_result.value == 1.0

    state = simple_task_state(model_output="number 9007199254740993")
    result = await f1(stop_words=["number"])(state, Target("9007199254740992"))
    assert result is not None
    assert result.value == 0.0
    result = await f1(stop_words=["1.0"])(
        simple_task_state(model_output="1 answer"), Target("answer")
    )
    assert result is not None
    assert result.value == 1.0


def test_classification_numeric_precision_ignores_decimal_context() -> None:
    with localcontext() as context:
        context.prec = 2
        context.traps[Inexact] = True
        context.traps[Rounded] = True
        context.clear_flags()
        before = context.copy()

        answer = "123456789.12345678901234567890123456789"
        target = "123456789.12345678901234567890123456788"
        assert max_exact_score(answer, [target]) == 0.0
        assert max_f1_score(answer, [target]) == 0.0
        assert max_exact_score(answer, [answer + "0"]) == 1.0
        assert max_f1_score(answer, [answer + "0"]) == 1.0
        assert context.prec == before.prec
        assert context.traps == before.traps
        assert context.flags == before.flags


@pytest.mark.parametrize("trap_invalid", [False, True])
def test_classification_extreme_numeric_exponents(trap_invalid: bool) -> None:
    with localcontext() as context:
        context.traps[InvalidOperation] = trap_invalid
        context.clear_flags()
        before = context.copy()

        tiny = _normalize_number("1e-1000000")
        assert tiny != _normalize_number("0")
        assert len(tiny) < 32
        # Outside Decimal's exponent range: retain the token without changing
        # the caller's exception flags or turning a nonzero value into zero.
        extreme = "1e-9999999999999999999"
        assert _normalize_number(extreme) != _normalize_number("0")
        assert context.prec == before.prec
        assert context.traps == before.traps
        assert context.flags == before.flags


@pytest.mark.parametrize("log_format", ["eval", "json"])
async def test_numeric_classification_concurrent_eval_round_trip(
    tmp_path: Path, log_format: Literal["eval", "json"]
) -> None:
    cases = {
        "integer": ("9007199254740993", "9007199254740992", INCORRECT, 0.0),
        "decimal": (
            "0.12345678901234567890",
            "0.12345678901234567891",
            INCORRECT,
            0.0,
        ),
        "equivalent": ("0003.1400", "3.14", CORRECT, 1.0),
        "partial": ("value 9007199254740993", "value 9007199254740992", INCORRECT, 0.5),
    }
    gate = anyio.Event()
    started = 0
    in_flight = 0
    peak = 0

    async def output(
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        nonlocal started, in_flight, peak
        started += 1
        in_flight += 1
        peak = max(peak, in_flight)
        if started == len(cases):
            gate.set()
        try:
            await gate.wait()
            return ModelOutput.from_content("mockllm/model", cases[input[-1].text][0])
        finally:
            in_flight -= 1

    def check_log(log: EvalLog) -> None:
        assert log.status == "success"
        assert log.samples is not None
        samples = {sample.id: sample for sample in log.samples}
        assert set(samples) == set(cases)
        for sample_id, (answer, target, exact_value, f1_value) in cases.items():
            sample = samples[sample_id]
            assert sample.error is None
            assert sample.target == target
            assert sample.output.completion == answer
            assert sample.scores is not None
            assert sample.scores["exact"].value == exact_value
            assert sample.scores["f1"].value == f1_value
            assert sample.scores["exact"].answer == answer
            assert sample.scores["f1"].answer == answer
        assert log.results is not None
        results = {score.name: score for score in log.results.scores}
        assert set(results) == {"exact", "f1"}
        assert results["exact"].metrics["mean"].value == 0.25
        assert results["f1"].metrics["mean"].value == 0.375

    with anyio.fail_after(30):
        logs = await eval_async(
            Task(
                dataset=[
                    Sample(id=key, input=key, target=case[1])
                    for key, case in cases.items()
                ],
                solver=generate(),
                scorer=[exact(), f1()],
            ),
            model=get_model("mockllm/model", custom_outputs=output),
            max_samples=len(cases),
            max_connections=len(cases),
            log_dir=str(tmp_path),
            log_format=log_format,
        )
    assert started == peak == len(cases)
    assert in_flight == 0
    log = logs[0]
    check_log(log)
    reloaded = await read_eval_log_async(log.location)
    check_log(reloaded)
    recompute_metrics(reloaded)
    check_log(reloaded)
    rescored = await score_async(
        reloaded,
        [exact(), f1()],
        action="overwrite",
        model="mockllm/model",
        display="none",
    )
    check_log(rescored)
    path = tmp_path / f"rescored.{log_format}"
    await write_eval_log_async(rescored, path, format=log_format)
    check_log(await read_eval_log_async(path))


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


def test_max_score_blank_after_normalization_target():
    # Targets made only of articles or punctuation normalize to the empty
    # string and are skipped like empty targets: an answer that also
    # normalizes to nothing must not score as a perfect match.
    for target in ["a", "an", "the", "-"]:
        assert max_exact_score("", [target]) == 0.0
        assert max_f1_score("", [target]) == 0.0
        assert max_exact_score("   ", [target]) == 0.0
        assert max_f1_score("\n\t ", [target]) == 0.0
        # A blank-normalizing target alongside a real one does not
        # affect the real target's score.
        assert max_exact_score("hello", [target, "hello"]) == 1.0
        assert max_f1_score("hello", [target, "hello"]) == 1.0
    # The controls named on the issue, verbatim.
    assert max_exact_score("", ["a", "blue"]) == 0.0
    assert max_f1_score("", ["a", "blue"]) == 0.0
    assert max_f1_score("blue", ["a", "blue"]) == 1.0


def test_max_f1_score_stop_words_only_target():
    # A target whose every word is a configured stop word has no scorable
    # content left after stop-word removal and is skipped like an empty
    # target, even though it is non-empty before normalization.
    assert max_f1_score("", ["Paris"], stop_words=["PARIS"]) == 0.0
    # Targets with remaining content still score as before.
    assert max_f1_score("", ["Paris", "Berlin"], stop_words=["PARIS"]) == 0.0
    assert max_f1_score("Berlin", ["Paris", "Berlin"], stop_words=["PARIS"]) == 1.0


@pytest.mark.anyio
async def test_exact_blank_normalized_target_scores_incorrect():
    scorer = exact()
    state = simple_task_state(model_output="")
    result = await scorer(state, Target(["a"]))

    assert result.text == INCORRECT


@pytest.mark.anyio
async def test_f1_blank_normalized_target_scores_zero():
    scorer = f1()
    state = simple_task_state(model_output="")
    result = await scorer(state, Target(["the"]))

    assert result.text == "0.0"


def test_f1_duplicate_tokens_pay_precision_cost():
    # SQuAD F1 is count-sensitive: repeating a target word must not score 1.0.
    assert max_f1_score("hello hello", ["hello"]) == 0.67
    assert max_f1_score("Paris Paris Paris Paris Paris", ["Paris"]) == 0.33
    assert max_f1_score("the answer is 42 42", ["the answer is 42"]) == 0.86


def test_f1_multiset_overlap_counts_multiplicity_on_both_sides():
    assert max_f1_score("cat cat dog", ["cat dog dog"]) == 0.67
    # Order-insensitivity is deliberate and stays: same counts, any order.
    assert max_f1_score("dog cat", ["cat dog"]) == 1.0
    assert max_f1_score("dog dog cat", ["cat dog dog"]) == 1.0


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


@pytest.mark.anyio
async def test_exact_and_f1_keep_the_sign_of_a_negative_answer():
    exact_result = await exact()(simple_task_state(model_output="-5"), Target(["5"]))
    assert exact_result.text == INCORRECT
    f1_result = await f1()(simple_task_state(model_output="-5"), Target(["5"]))
    assert f1_result.text == "0.0"


def test_negative_numbers_keep_their_sign():
    assert max_exact_score("-5", ["5"]) == 0.0
    assert max_exact_score("-5", ["-5"]) == 1.0
    assert max_exact_score("-3.5", ["3.5"]) == 0.0
    assert max_exact_score("The answer is -40", ["The answer is 40"]) == 0.0
    assert max_exact_score("The answer is -40", ["the answer is -40"]) == 1.0
    # boundary punctuation is still stripped, but not the sign
    assert max_exact_score("(-40)", ["40"]) == 0.0
    assert max_exact_score("(-40)", ["-40"]) == 1.0
    assert max_exact_score("-40,", ["-40"]) == 1.0
    assert max_f1_score("-5", ["5"]) == 0.0
    assert max_f1_score("x is -5", ["x is 5"]) == 0.67
    assert max_f1_score("x is -5", ["x is -5"]) == 1.0


def test_hyphens_as_punctuation_and_in_ranges_score_as_before():
    assert max_exact_score("well-known", ["well known"]) == 1.0
    assert max_exact_score("e-mail", ["e mail"]) == 1.0
    assert max_exact_score("x-5", ["x 5"]) == 1.0
    assert max_exact_score("x - 5", ["x 5"]) == 1.0
    assert max_exact_score("3-5", ["3 5"]) == 1.0
    assert max_exact_score("pages 3-5", ["pages 3 5"]) == 1.0
    assert max_exact_score("5%-10%", ["5 10"]) == 1.0
    assert max_exact_score("2024-05-01", ["2024 05 01"]) == 1.0
    assert max_f1_score("3-5 apples", ["3 5 apples"]) == 1.0
    assert max_f1_score("f(-1)", ["f 1"]) == 1.0
    assert max_f1_score("\\frac{-1}{2}", ["frac 12"]) == 1.0


@pytest.mark.anyio
async def test_exact_and_f1_split_a_minus_after_a_word_and_nested_brackets():
    exact_result = await exact()(
        simple_task_state(model_output="f([-1])"), Target(["f1"])
    )
    assert exact_result.text == INCORRECT
    f1_result = await f1()(simple_task_state(model_output="f([-1])"), Target(["f1"]))
    assert f1_result.text == "0.0"


def test_minus_after_a_word_and_nested_brackets_splits_as_before():
    assert max_exact_score("f([-1])", ["f1"]) == 0.0
    assert max_exact_score("f((-1))", ["f1"]) == 0.0
    assert max_exact_score("\\frac{{-1}}{2}", ["frac12"]) == 0.0
    assert max_f1_score("f([-1])", ["f1"]) == 0.0
    assert max_f1_score("f([-1])", ["f 1"]) == 1.0
    assert max_f1_score("f((-1))", ["f 1"]) == 1.0
    assert max_f1_score("\\frac{{-1}}{2}", ["frac 12"]) == 1.0
    # a minus behind a run of brackets that opens the token is still a sign
    assert max_exact_score("((-40))", ["-40"]) == 1.0
    assert max_exact_score("((-40))", ["40"]) == 0.0
    assert max_exact_score("x is ([-40])", ["x is -40"]) == 1.0
