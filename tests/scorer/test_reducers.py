from functools import reduce

from inspect_ai import Epochs, Task, eval
from inspect_ai._eval.score import score
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

avg_reducer = mean_score()
median_reducer = median_score()
mode_reducer = mode_score()
max_reducer = max_score()
at_least_3_reducer = at_least(3)
at_least_4_reducer = at_least(4)
at_least_5_reducer = at_least(5, 3)


def test_simple_reducers() -> None:
    simple_scores = [
        Score(value=6),
        Score(value=0),
        Score(value=0),
        Score(value=0),
        Score(value=8),
        Score(value=4),
    ]
    assert avg_reducer(simple_scores).value == 3
    assert median_reducer(simple_scores).value == 2
    assert mode_reducer(simple_scores).value == 0
    assert max_reducer(simple_scores).value == 8
    assert at_least_3_reducer(simple_scores).value == 1
    assert at_least_4_reducer(simple_scores).value == 0


def test_list_reducers() -> None:
    list_scores = [
        Score(value=[1, 2]),
        Score(value=[4, 3]),
        Score(value=[3, 1]),
        Score(value=[1, 2]),
        Score(value=[1, 2]),
    ]
    assert avg_reducer(list_scores).value == [2, 2]
    assert median_reducer(list_scores).value == [1, 2]
    assert mode_reducer(list_scores).value == [1, 2]
    assert max_reducer(list_scores).value == [4, 3]
    assert at_least_3_reducer(list_scores).value == [1, 1]
    assert at_least_4_reducer(list_scores).value == [1, 1]


def test_dict_reducers() -> None:
    dict_scores = [
        Score(value={"coolness": 5, "spiciness": 1}),
        Score(value={"coolness": 4, "spiciness": 1}),
        Score(value={"coolness": 3, "spiciness": 1}),
        Score(value={"coolness": 2, "spiciness": 1}),
        Score(value={"coolness": 1, "spiciness": 21}),
    ]
    assert avg_reducer(dict_scores).value == {"coolness": 3, "spiciness": 5}
    assert median_reducer(dict_scores).value == {"coolness": 3, "spiciness": 1}
    assert mode_reducer(dict_scores).value == {"coolness": 5, "spiciness": 1}
    assert max_reducer(dict_scores).value == {"coolness": 5, "spiciness": 21}
    assert at_least_3_reducer(dict_scores).value == {"coolness": 1, "spiciness": 1}
    assert at_least_4_reducer(dict_scores).value == {"coolness": 1, "spiciness": 1}
    assert at_least_5_reducer(dict_scores).value == {"coolness": 0, "spiciness": 0}


@score_reducer(name="add_em_up")
def sum(value_to_float: ValueToFloat = value_to_float()) -> ScoreReducer:
    def sum(scores: list[Score]) -> Score:
        value = reduce(lambda x, y: x + value_to_float(y.value), scores, 0.0)
        return Score(value=value)

    return sum


def test_scorer_lookup():
    assert create_reducers("add_em_up")


def eval_with_reducer():
    task = Task(dataset=[Sample(input="Say hello.", target="Hello")], scorer=match())
    return eval(task, model="mockllm/model", epochs=Epochs(5, max_score()))[0]


def test_reducer_by_name():
    task = Task(dataset=[Sample(input="Say hello.", target="Hello")], scorer=match())
    log = eval(task, model="mockllm/model", epochs=Epochs(5, "at_least_2"))[0]
    assert log.eval.config.epochs_reducer == ["at_least_2"]


def test_eval_reducer():
    log = eval_with_reducer()
    assert log.eval.config.epochs_reducer == ["max"]


def test_score_reducer():
    log = score(eval_with_reducer(), match())
    assert log.eval.config.epochs_reducer == ["max"]

    log = score(eval_with_reducer(), match(), [mode_score(), mean_score()])
    assert log.eval.config.epochs_reducer == ["mode", "mean"]
