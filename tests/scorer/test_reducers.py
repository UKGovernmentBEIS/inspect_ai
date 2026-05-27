from collections import namedtuple
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from functools import reduce
from typing import Any

import numpy as np

from inspect_ai import Epochs, Task, eval
from inspect_ai._eval.score import score
from inspect_ai._util.registry import registry_info
from inspect_ai.dataset import Sample
from inspect_ai.scorer import (
    Score,
    ScoreReducer,
    ValueToFloat,
    at_least,
    match,
    max_score,
    mean_score,
    median_score,
    mode_score,
    score_reducer,
    value_to_float,
)
from inspect_ai.scorer._reducer import create_reducers
from inspect_ai.scorer._reducer.reducer import pass_at, pass_k
from inspect_ai.scorer._reducer.registry import REDUCER_NAME, reducer_log_name

avg_reducer = mean_score()
median_reducer = median_score()
mode_reducer = mode_score()
max_reducer = max_score()
at_least_3_reducer = at_least(3)
at_least_4_reducer = at_least(4)
at_least_5_reducer = at_least(5, 3)
pass_at_2_no_threshhold = pass_at(2)
pass_at_3_threshhold = pass_at(3, 2)
pass_at_5_no_threshhold = pass_at(5)
pass_at_5_threshhold = pass_at(5, 2)
pass_k_2_no_threshold = pass_k(2)
pass_k_3_threshold = pass_k(3, 2)
pass_k_5_no_threshold = pass_k(5)
pass_k_5_threshold = pass_k(5, 2)


def test_simple_reducers() -> None:
    _test_simple_reducers_impl(include_nan=False)


def test_nan_simple_reducers() -> None:
    _test_simple_reducers_impl(include_nan=True)


def test_all_nan_simple_reducers() -> None:
    simple_scores = [
        Score(value=float("nan")),
        Score(value=float("nan")),
        Score(value=float("nan")),
    ]

    assert _is_nan(avg_reducer(simple_scores).value)
    assert _is_nan(median_reducer(simple_scores).value)
    assert _is_nan(mode_reducer(simple_scores).value)
    assert _is_nan(max_reducer(simple_scores).value)
    assert _is_nan(at_least_3_reducer(simple_scores).value)
    assert _is_nan(pass_at_2_no_threshhold(simple_scores).value)
    assert _is_nan(pass_at_3_threshhold(simple_scores).value)
    assert _is_nan(pass_at_5_no_threshhold(simple_scores).value)
    assert _is_nan(pass_at_5_threshhold(simple_scores).value)
    assert _is_nan(pass_k_2_no_threshold(simple_scores).value)
    assert _is_nan(pass_k_3_threshold(simple_scores).value)
    assert _is_nan(pass_k_5_no_threshold(simple_scores).value)
    assert _is_nan(pass_k_5_threshold(simple_scores).value)


def test_list_reducers() -> None:
    _test_list_reducers_impl(include_nan=False)


def test_nan_list_reducers() -> None:
    _test_list_reducers_impl(include_nan=True)


def test_all_nan_list_reducers() -> None:
    list_scores = [
        Score(value=[float("nan"), float("nan")]),
        Score(value=[float("nan"), float("nan")]),
        Score(value=[float("nan"), float("nan")]),
    ]

    def assert_list_nan(x: Any) -> bool:
        return isinstance(x, list) and all(_is_nan(v) for v in x)

    reduced = avg_reducer(list_scores).value
    assert_list_nan(reduced)
    reduced = median_reducer(list_scores).value
    assert_list_nan(reduced)
    reduced = mode_reducer(list_scores).value
    assert_list_nan(reduced)
    reduced = max_reducer(list_scores).value
    assert_list_nan(reduced)
    reduced = at_least_3_reducer(list_scores).value
    assert_list_nan(reduced)
    reduced = pass_at_2_no_threshhold(list_scores).value
    assert_list_nan(reduced)
    reduced = pass_k_2_no_threshold(list_scores).value
    assert_list_nan(reduced)


def test_nan_root_list_reducers() -> None:
    # Mix of list-shaped scores and NaN-at-root unscored sentinels. The
    # NaN-at-root entries should be skipped, with reduction computed over
    # the list-shaped subset (1, 1).
    list_scores = [
        Score(value=[1, 2]),
        Score(value=[4, 3]),
        Score(value=float("nan")),
        Score(value=[3, 1]),
        Score(value=[1, 2]),
        Score(value=float("nan")),
        Score(value=[1, 2]),
    ]

    assert avg_reducer(list_scores).value == [2, 2]
    assert median_reducer(list_scores).value == [1, 2]
    assert mode_reducer(list_scores).value == [1, 2]
    assert max_reducer(list_scores).value == [4, 3]
    assert at_least_3_reducer(list_scores).value == [1, 1]
    assert pass_at_2_no_threshhold(list_scores).value == [1, 1]
    assert pass_k_2_no_threshold(list_scores).value == [1, 1]


def test_all_nan_root_list_reducers() -> None:
    # When every score is NaN-at-root, list reducers fall through to a
    # NaN-scalar Score (no list shape to construct from).
    list_scores = [
        Score(value=float("nan")),
        Score(value=float("nan")),
        Score(value=float("nan")),
    ]

    assert _is_nan(avg_reducer(list_scores).value)
    assert _is_nan(median_reducer(list_scores).value)
    assert _is_nan(mode_reducer(list_scores).value)
    assert _is_nan(max_reducer(list_scores).value)
    assert _is_nan(at_least_3_reducer(list_scores).value)
    assert _is_nan(pass_at_2_no_threshhold(list_scores).value)
    assert _is_nan(pass_k_2_no_threshold(list_scores).value)


def test_dict_reducers() -> None:
    _test_dict_reducers_impl(include_nan=False)


def test_nan_dict_reducers() -> None:
    _test_dict_reducers_impl(include_nan=True)


def test_all_nan_dict_reducers() -> None:
    dict_scores = [
        Score(value={"coolness": float("nan"), "spiciness": float("nan")}),
        Score(value={"coolness": float("nan"), "spiciness": float("nan")}),
        Score(value={"coolness": float("nan"), "spiciness": float("nan")}),
    ]

    def assert_dict_nan(x: Any) -> bool:
        return (
            isinstance(x, dict)
            and all(key in x for key in ["coolness", "spiciness"])
            and all(_is_nan(v) for v in x.values())
        )

    reduced = avg_reducer(dict_scores).value
    assert_dict_nan(reduced)
    reduced = median_reducer(dict_scores).value
    assert_dict_nan(reduced)
    reduced = mode_reducer(dict_scores).value
    assert_dict_nan(reduced)
    reduced = max_reducer(dict_scores).value
    assert_dict_nan(reduced)
    reduced = at_least_3_reducer(dict_scores).value
    assert_dict_nan(reduced)
    reduced = pass_at_2_no_threshhold(dict_scores).value
    assert_dict_nan(reduced)
    reduced = pass_k_2_no_threshold(dict_scores).value
    assert_dict_nan(reduced)


def test_nan_root_dict_reducers() -> None:
    # Mix of dict-shaped scores and NaN-at-root unscored sentinels. The
    # NaN-at-root entries should be skipped, with reduction computed over
    # the dict-shaped subset.
    dict_scores = [
        Score(value={"coolness": 5, "spiciness": 1}),
        Score(value={"coolness": 4, "spiciness": 1}),
        Score(value=float("nan")),
        Score(value={"coolness": 3, "spiciness": 1}),
        Score(value={"coolness": 2, "spiciness": 1}),
        Score(value={"coolness": 1, "spiciness": 21}),
        Score(value=float("nan")),
    ]

    assert avg_reducer(dict_scores).value == {"coolness": 3, "spiciness": 5}
    assert median_reducer(dict_scores).value == {"coolness": 3, "spiciness": 1}
    assert mode_reducer(dict_scores).value == {"coolness": 5, "spiciness": 1}
    assert max_reducer(dict_scores).value == {"coolness": 5, "spiciness": 21}
    assert at_least_3_reducer(dict_scores).value == {"coolness": 1, "spiciness": 1}
    assert at_least_4_reducer(dict_scores).value == {"coolness": 1, "spiciness": 1}
    assert at_least_5_reducer(dict_scores).value == {"coolness": 0, "spiciness": 0}
    assert pass_at_2_no_threshhold(dict_scores).value == {"coolness": 1, "spiciness": 1}
    assert pass_k_2_no_threshold(dict_scores).value == {"coolness": 1, "spiciness": 1}


def test_all_nan_root_dict_reducers() -> None:
    # When every score is NaN-at-root, dict reducers fall through to a
    # NaN-scalar Score (no dict shape to construct from).
    scores = [
        Score(value=float("nan")),
        Score(value=float("nan")),
        Score(value=float("nan")),
    ]

    assert _is_nan(avg_reducer(scores).value)
    assert _is_nan(median_reducer(scores).value)
    assert _is_nan(mode_reducer(scores).value)
    assert _is_nan(max_reducer(scores).value)
    assert _is_nan(at_least_3_reducer(scores).value)
    assert _is_nan(pass_at_2_no_threshhold(scores).value)
    assert _is_nan(pass_k_2_no_threshold(scores).value)


def test_nan_root_first_score_dict_reducers() -> None:
    # Regression test: when the FIRST score is NaN-at-root, the reducer
    # must still detect the dict shape from a later score and produce a
    # dict-valued reduction (rather than dispatching to the scalar branch).
    dict_scores = [
        Score(value=float("nan")),
        Score(value={"coolness": 4, "spiciness": 1}),
        Score(value={"coolness": 2, "spiciness": 1}),
    ]

    assert avg_reducer(dict_scores).value == {"coolness": 3, "spiciness": 1}
    assert max_reducer(dict_scores).value == {"coolness": 4, "spiciness": 1}


def test_score_unscored() -> None:
    # Score.unscored() constructs a NaN-valued Score and preserves
    # answer/explanation/metadata.
    s = Score.unscored(
        answer="?", explanation="scanner returned None", metadata={"reason": "error"}
    )
    assert _is_nan(s.value)
    assert s.answer == "?"
    assert s.explanation == "scanner returned None"
    assert s.metadata == {"reason": "error"}


def test_reducer_preserve_metadata() -> None:
    simple_scores = [
        # first five scores are identical
        Score(
            value=1, answer="1", explanation="An explanation", metadata={"foo": "bar"}
        ),
        Score(
            value=1, answer="1", explanation="An explanation", metadata={"foo": "bar"}
        ),
        Score(
            value=1, answer="1", explanation="An explanation", metadata={"foo": "bar"}
        ),
        Score(
            value=1, answer="1", explanation="An explanation", metadata={"foo": "bar"}
        ),
        Score(
            value=1, answer="1", explanation="An explanation", metadata={"foo": "bar"}
        ),
        # last score is different
        Score(
            value=2,
            answer="2",
            explanation="Different explanation",
            metadata={"foo": "BAZ"},
        ),
    ]

    reducers = [
        avg_reducer,
        median_reducer,
        mode_reducer,
        max_reducer,
        at_least_3_reducer,
        pass_at_2_no_threshhold,
        pass_k_2_no_threshold,
    ]

    # verify that other fields are set only if equal across all samples
    for reducer in reducers:
        # reduce all scores _including_ the last one that's different
        reduced = reducer(simple_scores)
        assert reduced.answer is None
        assert reduced.explanation is None
        assert reduced.metadata == simple_scores[0].metadata
        # reduce all scores _except_ the last one
        reduced = reducer(simple_scores[:-1])
        assert reduced.answer == simple_scores[0].answer
        assert reduced.explanation == simple_scores[0].explanation
        assert reduced.metadata == simple_scores[0].metadata

    # verify that other fields are preserved for a single epoch
    for reducer in reducers:
        reduced = reducer([simple_scores[0]])
        assert reduced.answer == simple_scores[0].answer
        assert reduced.explanation == simple_scores[0].explanation
        assert reduced.metadata == simple_scores[0].metadata


@dataclass
class Foo:
    foo: bool


class DifficultyLevel(Enum):
    EASY = 1
    MEDIUM = 2
    HARD = 3


Point = namedtuple("Point", ["x", "y"])  # noqa: F821


def test_complex_metadata_reduce():
    list_scores = [
        Score(
            value=1,
            answer="A",
            explanation="It is A",
            metadata={
                "foo": Foo(foo=True),
                "count": 5,
                "probability": 0.75,
                "tags": ["math", "algebra"],
                "user": {"id": 123, "name": "John"},
                "timestamp": datetime.now(timezone.utc),
                "difficulty": DifficultyLevel.MEDIUM,
                "optional_data": None,
                "stats": {"attempts": 3, "success_rate": 0.67},
                "frozen_set": frozenset([1, 2, 3]),
                "point": Point(x=1, y=2),
            },
        ),
        Score(
            value=1,
            answer="A",
            explanation="It is A",
            metadata={
                "foo": Foo(foo=True),
                "count": 5,
                "probability": 0.75,
                "tags": ["math", "algebra"],
                "user": {"id": 123, "name": "John"},
                "timestamp": datetime.now(timezone.utc),
                "difficulty": DifficultyLevel.MEDIUM,
                "optional_data": None,
                "stats": {"attempts": 3, "success_rate": 0.67},
                "frozen_set": frozenset([1, 2, 3]),
                "point": Point(x=1, y=2),
            },
        ),
        Score(
            value=1,
            answer="A",
            explanation="It is A",
            metadata={
                "foo": Foo(foo=True),
                "count": 5,
                "probability": 0.75,
                "tags": ["math", "algebra"],
                "user": {"id": 123, "name": "John"},
                "timestamp": datetime.now(timezone.utc),
                "difficulty": DifficultyLevel.MEDIUM,
                "optional_data": None,
                "stats": {"attempts": 3, "success_rate": 0.67},
                "frozen_set": frozenset([1, 2, 3]),
                "point": Point(x=1, y=2),
            },
        ),
    ]

    reduced = avg_reducer(list_scores)
    assert reduced.value == 1
    assert reduced.answer == "A"
    assert reduced.explanation == "It is A"
    assert reduced.metadata == list_scores[0].metadata


@score_reducer(name="add_em_up")
def sum(value_to_float: ValueToFloat = value_to_float()) -> ScoreReducer:
    def sum(scores: list[Score]) -> Score:
        value = reduce(lambda x, y: x + value_to_float(y.value), scores, 0.0)
        return Score(value=value)

    return sum


def test_scorer_lookup():
    assert create_reducers("add_em_up")


@score_reducer(name="top_5")
def top_five() -> ScoreReducer:
    def reduce(scores: list[Score]) -> Score:
        return scores[0]

    return reduce


def test_create_reducers_exact_name_with_trailing_digits() -> None:
    # Regression: a custom reducer whose registered name happens to end in
    # `_<digits>` (e.g. "top_5") must be looked up literally rather than
    # being rewritten by the at_least_k / pass_at_k convenience regex into
    # a lookup of "top" with k=5.
    reducers = create_reducers("top_5")
    assert reducers is not None and len(reducers) == 1
    info = registry_info(reducers[0])
    assert info.name == "top_5"

    # built-in `_<k>` shorthand must still work
    assert create_reducers("at_least_2")
    assert create_reducers("pass_at_3")
    assert create_reducers("pass_k_3")


def test_at_least_reducer_name_includes_k() -> None:
    # Regression: the REDUCER_NAME override inside at_least()/pass_at() was
    # being written to the global factory wrapper rather than the returned
    # reducer closure, so the registry name never picked up the `k` suffix
    # and each call leaked global state onto the factory.
    r3 = at_least(3)
    assert registry_info(r3).name.endswith("at_least_3")
    # creating another instance must not retroactively affect r3
    _ = at_least(7)
    assert registry_info(r3).name.endswith("at_least_3")
    # the factory itself should not accumulate per-call state
    assert not hasattr(at_least, REDUCER_NAME)
    # log name must not double-append the suffix
    assert reducer_log_name(r3) == "at_least_3"
    assert reducer_log_name(pass_at(4)) == "pass_at_4"
    assert reducer_log_name(pass_k(4)) == "pass_k_4"
    assert not hasattr(pass_k, REDUCER_NAME)


def test_max_reducer_dict_per_key_nan_order_independent() -> None:
    # Regression: max_score's bespoke dict path fed raw per-key values to
    # builtin max() without filtering NaN. Because NaN compares False with
    # everything, the result depended on epoch order. The scalar path and
    # _compute_dict_stat already filter via _is_reducible; the dict/list
    # max paths must do the same.
    nan_first = [Score(value={"x": float("nan")}), Score(value={"x": 1.0})]
    one_first = [Score(value={"x": 1.0}), Score(value={"x": float("nan")})]
    assert max_reducer(nan_first).value == {"x": 1.0}
    assert max_reducer(one_first).value == {"x": 1.0}

    # list path
    nan_first_l = [Score(value=[float("nan")]), Score(value=[1.0])]
    one_first_l = [Score(value=[1.0]), Score(value=[float("nan")])]
    assert max_reducer(nan_first_l).value == [1.0]
    assert max_reducer(one_first_l).value == [1.0]

    # all-NaN per key falls back to NaN for that key
    all_nan = [Score(value={"x": float("nan")}), Score(value={"x": float("nan")})]
    reduced = max_reducer(all_nan).value
    assert isinstance(reduced, dict) and _is_nan(reduced["x"])


def test_pass_at_k_insufficient_scored_epochs() -> None:
    # Regression: pass_at(k) computes over the NaN-filtered value list. When
    # filtering shrinks the valid count below k, the `total - correct < k`
    # short-circuit fired even with zero correct, reporting pass@k = 1.0.
    # With fewer than k scored epochs the estimator is undefined, so the
    # reducer should yield the unscored NaN sentinel rather than 1.0.
    scores = [
        Score(value=0.0),
        Score(value=0.0),
        Score(value=float("nan")),
        Score(value=float("nan")),
    ]
    result = pass_at(3)(scores).value
    assert _is_nan(result), f"expected NaN for <k scored epochs, got {result!r}"

    # sanity: with k scored epochs and zero correct, pass@k is 0.0
    assert pass_at(3)([Score(value=0.0)] * 4).value == 0.0


def test_pass_k_insufficient_scored_epochs() -> None:
    # pass_k mirrors pass_at: when NaN-filtering shrinks the valid count
    # below k, the estimator is undefined and the reducer yields the
    # unscored NaN sentinel rather than a spurious 0.0 from comb(c, k)=0.
    scores = [
        Score(value=1.0),
        Score(value=1.0),
        Score(value=float("nan")),
        Score(value=float("nan")),
    ]
    result = pass_k(3)(scores).value
    assert _is_nan(result), f"expected NaN for <k scored epochs, got {result!r}"

    # sanity: with k scored epochs and all correct, pass^k is 1.0
    assert pass_k(3)([Score(value=1.0)] * 3).value == 1.0


def test_validate_pass_k_reducer() -> None:
    import pytest

    from inspect_ai._util.error import PrerequisiteError
    from inspect_ai.scorer._reducer.registry import validate_reducer

    # k <= epochs: ok
    validate_reducer(5, pass_k(5))
    validate_reducer(8, pass_k(3))

    # k > epochs: raises with the reducer's logged name in the message
    with pytest.raises(PrerequisiteError, match="pass_k_5"):
        validate_reducer(3, pass_k(5))


def eval_with_reducer():
    task = Task(dataset=[Sample(input="Say hello.", target="Hello")], scorer=match())
    return eval(task, model="mockllm/model", epochs=Epochs(5, max_score()))[0]


def eval_no_reducer():
    task = Task(dataset=[Sample(input="Say hello.", target="Hello")], scorer=match())
    return eval(task, model="mockllm/model", epochs=Epochs(5, []))[0]


def test_reducer_by_name():
    task = Task(dataset=[Sample(input="Say hello.", target="Hello")], scorer=match())
    log = eval(task, model="mockllm/model", epochs=Epochs(5, "at_least_2"))[0]
    assert log.eval.config.epochs_reducer == ["at_least_2"]


def test_pass_k_reducer_by_name():
    task = Task(dataset=[Sample(input="Say hello.", target="Hello")], scorer=match())
    log = eval(task, model="mockllm/model", epochs=Epochs(5, "pass_k_2"))[0]
    assert log.eval.config.epochs_reducer == ["pass_k_2"]


def test_no_reducer():
    task = Task(dataset=[Sample(input="Say hello.", target="Hello")], scorer=match())
    log = eval(task, model="mockllm/model", epochs=Epochs(5, []))[0]
    assert log.eval.config.epochs_reducer == []


def test_default_reducer():
    task = Task(dataset=[Sample(input="Say hello.", target="Hello")], scorer=match())
    log = eval(task, model="mockllm/model", epochs=4)[0]
    assert log.eval.config.epochs_reducer == ["mean"]


def test_eval_reducer():
    log = eval_with_reducer()
    assert log.eval.config.epochs_reducer == ["max"]


def test_score_reducer():
    log = score(eval_with_reducer(), match())
    assert log.eval.config.epochs_reducer == ["max"]

    log = score(
        eval_with_reducer(), match(), epochs_reducer=[mode_score(), mean_score()]
    )
    assert log.eval.config.epochs_reducer == ["mode", "mean"]


def test_score_no_reducer():
    log = score(eval_no_reducer(), match())
    assert log.eval.config.epochs_reducer == []


def test_main_reducer():
    str_scores = [
        Score(value="I"),
        Score(value="I"),
        Score(value="I"),
        Score(value="C"),
        Score(value="C"),
    ]
    assert mean_score()(str_scores).value == 0.4


def test_main_reducer_nan():
    str_scores = [
        Score(value="I"),
        Score(value="I"),
        Score(value="I"),
        Score(value="C"),
        Score(value="C"),
        Score(value=float("nan")),
    ]
    assert mean_score()(str_scores).value == 0.4


def _test_simple_reducers_impl(include_nan: bool = False) -> None:
    simple_scores = [
        Score(value=6),
        Score(value=0),
        Score(value=0),
        Score(value=0),
        Score(value=8),
        Score(value=4),
    ]
    if include_nan:
        simple_scores.append(Score(value=float("nan")))

    assert avg_reducer(simple_scores).value == 3
    assert median_reducer(simple_scores).value == 2
    assert mode_reducer(simple_scores).value == 0
    assert max_reducer(simple_scores).value == 8
    assert at_least_3_reducer(simple_scores).value == 1
    assert at_least_4_reducer(simple_scores).value == 0
    assert pass_at_2_no_threshhold(simple_scores).value == 0.8
    assert pass_at_3_threshhold(simple_scores).value == 0.95
    assert pass_at_5_no_threshhold(simple_scores).value == 1.0
    assert pass_at_5_threshhold(simple_scores).value == 1.0
    # pass_k = comb(correct, k) / comb(total, k). For simple_scores
    # (correct=3, total=6): pass_k(2)=3/15=0.2; pass_k(3, value=2)=1/20=0.05;
    # pass_k(5,*)=0/6=0.0 since correct < k.
    assert pass_k_2_no_threshold(simple_scores).value == 0.2
    assert pass_k_3_threshold(simple_scores).value == 0.05
    assert pass_k_5_no_threshold(simple_scores).value == 0.0
    assert pass_k_5_threshold(simple_scores).value == 0.0


def _test_list_reducers_impl(include_nan: bool = False) -> None:
    list_scores = [
        Score(value=[1, 2]),
        Score(value=[4, 3]),
        Score(value=[3, 1]),
        Score(value=[1, 2]),
        Score(value=[1, 2]),
    ]
    if include_nan:
        list_scores.append(Score(value=[float("nan"), float("nan")]))

    assert avg_reducer(list_scores).value == [2, 2]
    assert median_reducer(list_scores).value == [1, 2]
    assert mode_reducer(list_scores).value == [1, 2]
    assert max_reducer(list_scores).value == [4, 3]
    assert at_least_3_reducer(list_scores).value == [1, 1]
    assert at_least_4_reducer(list_scores).value == [1, 1]
    assert pass_at_2_no_threshhold(list_scores).value == [1, 1]
    assert pass_k_2_no_threshold(list_scores).value == [1, 1]


def _test_dict_reducers_impl(include_nan: bool = False) -> None:
    dict_scores = [
        Score(value={"coolness": 5, "spiciness": 1}),
        Score(value={"coolness": 4, "spiciness": 1}),
        Score(value={"coolness": 3, "spiciness": 1}),
        Score(value={"coolness": 2, "spiciness": 1}),
        Score(value={"coolness": 1, "spiciness": 21}),
    ]
    if include_nan:
        dict_scores.append(
            Score(value={"coolness": float("nan"), "spiciness": float("nan")})
        )

    assert avg_reducer(dict_scores).value == {"coolness": 3, "spiciness": 5}
    assert median_reducer(dict_scores).value == {"coolness": 3, "spiciness": 1}
    assert mode_reducer(dict_scores).value == {"coolness": 5, "spiciness": 1}
    assert max_reducer(dict_scores).value == {"coolness": 5, "spiciness": 21}
    assert at_least_3_reducer(dict_scores).value == {"coolness": 1, "spiciness": 1}
    assert at_least_4_reducer(dict_scores).value == {"coolness": 1, "spiciness": 1}
    assert at_least_5_reducer(dict_scores).value == {"coolness": 0, "spiciness": 0}
    assert pass_at_2_no_threshhold(dict_scores).value == {"coolness": 1, "spiciness": 1}
    assert pass_k_2_no_threshold(dict_scores).value == {"coolness": 1, "spiciness": 1}


def _is_nan(x: Any) -> bool:
    return isinstance(x, float) and np.isnan(x)
