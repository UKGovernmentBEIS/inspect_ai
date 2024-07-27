import statistics
from collections import Counter
from typing import Callable, Protocol, cast, runtime_checkable

from inspect_ai.scorer._metric import Score, Value, ValueToFloat, value_to_float


@runtime_checkable
class ScoreReducer(Protocol):
    def __call__(self, scores: list[Score]) -> Score: ...

    @property
    def __name__(self) -> str: ...


def majority() -> ScoreReducer:
    def majority(scores: list[Score]) -> Score:
        r"""A utility function for taking a majority vote over a list of scores.

        Args:
            scores: a list of Scores.
        """

        def most_common(
            counts: Counter[str | int | float | bool],
        ) -> str | int | float | bool:
            return counts.most_common(1)[0][0]

        if isinstance(scores[0].value, dict):
            return _count_dict(scores, most_common)
        elif isinstance(scores[0].value, list):
            return _count_list(scores, most_common)
        else:
            return _count_scalar(scores, most_common)

    return majority


def avg(value_to_float: ValueToFloat = value_to_float()) -> ScoreReducer:
    def avg(scores: list[Score]) -> Score:
        r"""A utility function for taking a mean value over a list of scores.

        Args:
            scores: a list of Scores.
        """
        if isinstance(scores[0].value, dict):
            return _compute_dict_stat(scores, value_to_float, statistics.mean)
        elif isinstance(scores[0].value, list):
            return _compute_list_stat(scores, value_to_float, statistics.mean)
        else:
            return _compute_primitive_stat(scores, value_to_float, statistics.mean)

    return avg


def median(value_to_float: ValueToFloat = value_to_float()) -> ScoreReducer:
    def median(scores: list[Score]) -> Score:
        r"""A utility function for taking a median value over a list of scores.

        Args:
            scores: a list of Scores.
        """
        if isinstance(scores[0].value, dict):
            return _compute_dict_stat(scores, value_to_float, statistics.median)
        elif isinstance(scores[0].value, list):
            return _compute_list_stat(scores, value_to_float, statistics.median)
        else:
            return _compute_primitive_stat(scores, value_to_float, statistics.median)

    return median


def at_least(
    n: int, value: float = 1.0, value_to_float: ValueToFloat = value_to_float()
) -> ScoreReducer:
    def at_least(scores: list[Score]) -> Score:
        r"""A utility function for scoring a value as correct if there are at least n score values greater than or equal to the value

        Args:
            scores: a list of Scores.
        """

        def gte_n(
            counter: Counter[str | int | float | bool],
        ) -> str | int | float | bool:
            count_gte_n = sum(
                count for key, count in counter.items() if value_to_float(key) >= value
            )
            return 1 if count_gte_n >= n else 0

        if isinstance(scores[0].value, dict):
            return _count_dict(scores, gte_n)
        elif isinstance(scores[0].value, list):
            return _count_list(scores, gte_n)
        else:
            return _count_scalar(scores, gte_n)

    setattr(at_least, REDUCER_NAME, f"at_least_{n}")

    return at_least


def best_of(value_to_float: ValueToFloat = value_to_float()) -> ScoreReducer:
    def best_of(scores: list[Score]) -> Score:
        r"""A utility function for taking the best value from a list of scores

        Args:
            scores: a list of Scores.
        """
        if isinstance(scores[0].value, dict):
            dict_result: dict[str, str | int | float | bool | None] = {}
            keys = scores[0].value.keys()  # type: ignore
            for key in keys:
                max_value = max(
                    [score.value[key] for score in scores],  # type: ignore
                    key=value_to_float,  # type: ignore
                )
                dict_result[key] = max_value
            return _reduced_score(dict_result, scores)
        elif isinstance(scores[0].value, list):
            list_result: list[str | int | float | bool] = []
            list_size = len(scores[0].value)  # type: ignore
            for i in range(list_size):
                max_value = max(
                    [score.value[i] for score in scores],  # type:ignore
                    key=value_to_float,  # type: ignore
                )
                if max_value is None:
                    raise ValueError(
                        "List of scores values unexpectedly had a `None` best score"
                    )
                else:
                    list_result.append(max_value)
            return _reduced_score(list_result, scores)
        else:
            max_score = max(scores, key=lambda score: value_to_float(score.value))
            return _reduced_score(max_score.value, scores)

    return best_of


def _count_scalar(
    scores: list[Score],
    counter_fn: Callable[[Counter[str | int | float | bool]], str | int | float | bool],
) -> Score:
    counts = Counter([score._as_scalar() for score in scores])
    return _reduced_score(counter_fn(counts), scores)


def _count_dict(
    scores: list[Score],
    counter_fn: Callable[[Counter[str | int | float | bool]], str | int | float | bool],
) -> Score:
    # Make sure these are all dictionaries be we proceed
    _check_value_dict(scores)

    dict_result: dict[str, str | int | float | bool] = {}
    keys = scores[0].value.keys()  # type: ignore
    for key in keys:
        counts: Counter[str | int | float | bool] = Counter(
            [score.value[key] for score in scores]  # type: ignore
        )
        dict_result[key] = counter_fn(counts)
    return _reduced_score(
        cast(dict[str, str | int | float | bool | None], dict_result), scores
    )


def _count_list(
    scores: list[Score],
    counter_fn: Callable[[Counter[str | int | float | bool]], str | int | float | bool],
) -> Score:
    # Make sure these are all lists before we continue
    _check_value_list(scores)

    list_result: list[str | int | float | bool] = []
    list_size = len(scores[0].value)  # type: ignore
    for i in range(list_size):
        counts: Counter[str | int | float | bool] = Counter(
            [score.value[i] for score in scores]  # type:ignore
        )
        list_result.append(counter_fn(counts))
    return _reduced_score(list_result, scores)


def _compute_dict_stat(
    scores: list[Score],
    value_to_float: ValueToFloat,
    statistic: Callable[[list[float]], float],
) -> Score:
    # Make sure these are all dictionaries be we proceed
    _check_value_dict(scores)

    dict_result: dict[str, str | int | float | bool | None] = {}
    for key in scores[0].value.keys():  # type: ignore
        values = [value_to_float(score.value[key]) for score in scores]  # type: ignore
        dict_result[key] = statistic(values)
    return _reduced_score(dict_result, scores)


def _compute_list_stat(
    scores: list[Score],
    value_to_float: ValueToFloat,
    statistic: Callable[[list[float]], float],
) -> Score:
    # Make sure these are all lists before we continue
    _check_value_list(scores)

    list_result: list[str | int | float | bool] = []
    list_size = len(scores[0].value)  # type: ignore
    for i in range(list_size):
        values = [value_to_float(score.value[i]) for score in scores]  # type: ignore
        list_result.append(statistic(values))
    return _reduced_score(list_result, scores)


def _compute_primitive_stat(
    scores: list[Score],
    value_to_float: ValueToFloat,
    statistic: Callable[[list[float]], float],
) -> Score:
    values = [value_to_float(score.value) for score in scores]
    result = statistic(values)
    return _reduced_score(result, scores)


def _check_value_dict(scores: list[Score]) -> None:
    for score in scores:
        if not isinstance(score.value, dict):
            raise ValueError(
                "Attempting to reduce a dictionary score for a non-dictionary value"
            )


def _check_value_list(scores: list[Score]) -> None:
    for score in scores:
        if not isinstance(score.value, list):
            raise ValueError("Attempting to reduce a list score for a non-list value")


def _reduced_score(value: Value, scores: list[Score]) -> Score:
    return Score(
        value=value,
        answer=scores[0].answer,
        explanation=scores[0].explanation,
        metadata={
            "individual_scores": scores
        },  # TODO: massage into format better for display
    )


REDUCER_NAME = "__REDUCER_NAME__"


def reducer_name(reducer: ScoreReducer) -> str:
    return getattr(reducer, REDUCER_NAME, reducer.__name__)
