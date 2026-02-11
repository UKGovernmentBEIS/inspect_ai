import math
from pathlib import Path

from inspect_ai.log._file import read_eval_log
from inspect_ai.model._model import compute_model_cost
from inspect_ai.model._model_data.model_data import ModelCost
from inspect_ai.model._model_output import ModelUsage


def test_completion_deserialization() -> None:
    log_file = (
        Path(__file__).parent.parent
        / "log"
        / "test_list_logs"
        / "2024-11-05T13-31-45-05-00_input-task_8zXjbRzCWrL9GXiXo2vus9.json"
    )
    log = read_eval_log(log_file)
    assert log.samples
    assert len(log.samples[0].output.completion) > 0


def test_model_usage_addition() -> None:
    usage1 = ModelUsage(
        input_tokens=1,
        output_tokens=2,
        total_tokens=3,
        input_tokens_cache_write=4,
        input_tokens_cache_read=5,
        reasoning_tokens=6,
    )
    usage2 = ModelUsage(
        input_tokens=10,
        output_tokens=20,
        total_tokens=30,
        input_tokens_cache_write=40,
        input_tokens_cache_read=50,
        reasoning_tokens=60,
    )

    result = usage1 + usage2

    assert result.input_tokens == 11
    assert result.output_tokens == 22
    assert result.total_tokens == 33
    assert result.input_tokens_cache_write == 44
    assert result.input_tokens_cache_read == 55
    assert result.reasoning_tokens == 66


def test_model_usage_addition_with_none_fields() -> None:
    usage1 = ModelUsage(
        input_tokens_cache_write=None,
        input_tokens_cache_read=2,
        reasoning_tokens=None,
    )
    usage2 = ModelUsage(
        input_tokens_cache_write=1,
        input_tokens_cache_read=None,
        reasoning_tokens=None,
    )

    result = usage1 + usage2

    assert result.input_tokens_cache_write == 1
    assert result.input_tokens_cache_read == 2
    assert result.reasoning_tokens is None


def test_compute_model_cost_basic() -> None:
    cost_data = ModelCost(
        input=1000.0, output=2000.0, input_cache_write=0.0, input_cache_read=0.0
    )
    usage = ModelUsage(input_tokens=3, output_tokens=4, total_tokens=7)

    # (3 * 1000 + 4 * 2000) / 1_000_000 = 0.011
    assert compute_model_cost(cost_data, usage) == 0.011


def test_compute_model_cost_with_cache_tokens() -> None:
    cost_data = ModelCost(
        input=1000.0, output=2000.0, input_cache_write=1500.0, input_cache_read=100.0
    )
    usage = ModelUsage(
        input_tokens=10,
        output_tokens=5,
        total_tokens=15,
        input_tokens_cache_write=20,
        input_tokens_cache_read=30,
    )

    # input:       10 * 1000 / 1M = 0.01
    # output:       5 * 2000 / 1M = 0.01
    # cache_write: 20 * 1500 / 1M = 0.03
    # cache_read:  30 *  100 / 1M = 0.003
    # total: 0.053
    assert math.isclose(compute_model_cost(cost_data, usage), 0.053)


def test_compute_model_cost_with_all_token_types() -> None:
    cost_data = ModelCost(
        input=1000.0, output=2000.0, input_cache_write=1500.0, input_cache_read=100.0
    )
    usage = ModelUsage(
        input_tokens=10,
        output_tokens=20,
        total_tokens=30,
        reasoning_tokens=8,
        input_tokens_cache_write=20,
        input_tokens_cache_read=30,
    )

    # input:       10 * 1000 / 1M = 0.01
    # output:      20 * 2000 / 1M = 0.04  (includes reasoning tokens)
    # cache_write: 20 * 1500 / 1M = 0.03
    # cache_read:  30 *  100 / 1M = 0.003
    # total: 0.083
    assert math.isclose(compute_model_cost(cost_data, usage), 0.083)
