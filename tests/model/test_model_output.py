import json
import math
from pathlib import Path
from typing import Any

import pytest

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.event import ModelEvent
from inspect_ai.log._file import read_eval_log
from inspect_ai.model import (
    ChatMessageAssistant,
    ChatMessageUser,
    GenerateConfig,
    ModelOutput,
    compute_model_cost,
    get_model,
)
from inspect_ai.model._model import init_active_model
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


def test_compute_model_cost_no_double_billing_cached_tokens() -> None:
    """Verify cached tokens are not double-billed.

    With normalized usage (input_tokens excludes cache), the cost should be:
    - Non-cached input tokens charged at full input rate
    - Cached tokens charged at cache read rate only
    """
    cost_data = ModelCost(
        input=3.0,  # $3/M for input
        output=15.0,  # $15/M for output
        input_cache_write=0.0,
        input_cache_read=1.5,  # $1.50/M for cached (50% discount)
    )
    # Simulating OpenAI-style response after normalization:
    # API reports prompt_tokens=1000 (inclusive), cached=600
    # After normalization: input_tokens=400 (non-cached), cache_read=600
    usage = ModelUsage(
        input_tokens=400,
        output_tokens=100,
        total_tokens=1100,
        input_tokens_cache_read=600,
    )

    cost = compute_model_cost(cost_data, usage)

    # input:      400 * 3.0 / 1M = 0.0012
    # output:     100 * 15.0 / 1M = 0.0015
    # cache_read: 600 * 1.5 / 1M = 0.0009
    # total: 0.0036
    expected = (400 * 3.0 + 100 * 15.0 + 600 * 1.5) / 1_000_000
    assert math.isclose(cost, expected)


def test_compute_model_cost_1h_cache_write_billed_above_5m_rate() -> None:
    """1-hour cache writes bill at 2x base input, vs 1.25x for 5-minute writes."""
    base_input = 3.0
    cost_data = ModelCost(
        input=base_input,
        output=15.0,
        input_cache_write=base_input * 1.25,  # the 5-minute rate
        input_cache_read=0.3,
    )
    usage = ModelUsage(
        input_tokens=0,
        output_tokens=0,
        total_tokens=1_000_000,
        input_tokens_cache_write=1_000_000,
    )

    # exactly 1M cache-write tokens, so each cost is the effective $/M rate
    assert math.isclose(compute_model_cost(cost_data, usage, "5m"), base_input * 1.25)
    assert math.isclose(compute_model_cost(cost_data, usage, "1h"), base_input * 2.0)

    # an unspecified TTL keeps the previous (5-minute) behaviour
    assert math.isclose(compute_model_cost(cost_data, usage), base_input * 1.25)

    # "auto" is never billed as such (providers report the resolved TTL via
    # cache_write_ttl); if it leaks through it bills at the 5-minute rate
    assert math.isclose(compute_model_cost(cost_data, usage, "auto"), base_input * 1.25)


def test_compute_model_cost_cache_ttl_does_not_affect_other_tokens() -> None:
    cost_data = ModelCost(
        input=1000.0, output=2000.0, input_cache_write=0.0, input_cache_read=100.0
    )
    usage = ModelUsage(
        input_tokens=10,
        output_tokens=5,
        total_tokens=45,
        input_tokens_cache_read=30,
    )

    assert math.isclose(
        compute_model_cost(cost_data, usage, "1h"),
        compute_model_cost(cost_data, usage),
    )


def test_input_context_tokens_absent_from_old_log() -> None:
    log_file = (
        Path(__file__).parent.parent
        / "log"
        / "test_list_logs"
        / "2024-11-05T13-31-45-05-00_input-task_8zXjbRzCWrL9GXiXo2vus9.json"
    )
    log = read_eval_log(log_file)
    assert log.samples
    assert log.samples[0].output.input_context_tokens is None


def test_input_context_tokens_round_trip() -> None:
    output = ModelOutput.from_content("mockllm/model", "hi")
    output.usage = ModelUsage(input_tokens=30, output_tokens=2, total_tokens=32)
    output.input_context_tokens = 10
    restored = ModelOutput.model_validate_json(output.model_dump_json())
    assert restored.input_context_tokens == 10
    assert restored.usage == output.usage

    dumped = output.model_dump()
    del dumped["input_context_tokens"]
    assert ModelOutput.model_validate(dumped).input_context_tokens is None


def test_input_context_tokens_defaults_from_usage(tmp_path: Path) -> None:
    """Generate fills the context size from a single request's usage, and logs keep it."""
    output = ModelOutput.from_content("mockllm/model", "hi")
    output.usage = ModelUsage(
        input_tokens=30,
        output_tokens=2,
        total_tokens=42,
        input_tokens_cache_read=7,
        input_tokens_cache_write=3,
    )
    log = eval(
        Task(dataset=[Sample(input="hello")]),
        model=get_model("mockllm/model", custom_outputs=[output]),
        log_dir=str(tmp_path),
    )[0]

    log = read_eval_log(log.location)
    assert log.samples
    events = [e for e in log.samples[0].events if isinstance(e, ModelEvent)]
    assert len(events) == 1
    assert events[0].output.input_context_tokens == 30 + 7 + 3
    assert log.samples[0].output.input_context_tokens == 30 + 7 + 3


def _model_event(output: ModelOutput) -> ModelEvent:
    from inspect_ai.model import GenerateConfig

    return ModelEvent(
        model="mockllm/model",
        input=[],
        tools=[],
        tool_choice="none",
        config=GenerateConfig(),
        output=output,
    )


_WRITERS = [
    "jsonable_python",
    "json_exclude_none",
    "acp",
    "python",
    "python_json",
    "json",
    "sample_json",
]


def _round_trip(event: ModelEvent, writer: str) -> tuple[dict[str, Any], ModelOutput]:
    """Serialize an event (or a sample holding it) and read the output back."""
    from inspect_ai._util.json import jsonable_python
    from inspect_ai.log import EvalSample

    match writer:
        case "jsonable_python":
            dumped = jsonable_python(event)
        case "json_exclude_none":
            dumped = json.loads(event.model_dump_json(exclude_none=True))
        case "acp":
            dumped = event.model_dump(mode="json", by_alias=True, exclude_none=True)
        case "python":
            dumped = event.model_dump()
        case "python_json":
            dumped = event.model_dump(mode="json")
        case "json":
            dumped = json.loads(event.model_dump_json())
        case _:
            sample = EvalSample(
                id=1,
                epoch=1,
                input="hi",
                target="",
                events=[event],
                output=event.output,
            )
            dumped_sample = json.loads(sample.model_dump_json())
            restored_sample = EvalSample.model_validate(dumped_sample)
            assert isinstance(restored_sample.events[0], ModelEvent)
            assert dumped_sample["output"] == dumped_sample["events"][0]["output"]
            return dumped_sample["events"][0], restored_sample.events[0].output
    return dumped, ModelEvent.model_validate(dumped).output


@pytest.mark.parametrize(
    ("input_context_tokens", "expected"),
    [
        # known size
        (10, 10),
        # not known: falls back to usage
        (None, 12),
    ],
)
@pytest.mark.parametrize("writer", _WRITERS)
def test_input_context_tokens_survives_serialization(
    input_context_tokens: int | None, expected: int, writer: str
) -> None:
    """Every writer keeps the context size, or the usage fallback when it is None."""
    from inspect_ai.model._model_output import output_input_context_tokens

    output = ModelOutput.from_content("mockllm/model", "hi")
    output.usage = ModelUsage(input_tokens=12, output_tokens=30, total_tokens=42)
    output.input_context_tokens = input_context_tokens

    _, restored = _round_trip(_model_event(output), writer)

    assert restored.input_context_tokens == input_context_tokens
    assert output_input_context_tokens(restored) == expected
    assert restored.usage == output.usage


@pytest.mark.parametrize("writer", _WRITERS)
def test_old_log_context_falls_back_after_round_trip(writer: str) -> None:
    """An old log's outputs still fall back to usage after being written again."""
    from inspect_ai.model._model_output import output_input_context_tokens

    log_file = (
        Path(__file__).parent.parent
        / "log"
        / "test_list_logs"
        / "2024-11-05T13-31-45-05-00_input-task_8zXjbRzCWrL9GXiXo2vus9.json"
    )
    log = read_eval_log(log_file)
    assert log.samples
    event = next(e for e in log.samples[0].events if isinstance(e, ModelEvent))
    assert output_input_context_tokens(event.output) == 53

    _, restored = _round_trip(event, writer)

    assert restored.input_context_tokens is None
    assert output_input_context_tokens(restored) == 53


def test_from_message_uses_active_model_name() -> None:
    active = get_model("mockllm/model")
    init_active_model(active, GenerateConfig())

    output = ModelOutput.from_message(ChatMessageAssistant(content="2"))

    assert output.model == active.api.model_name


def test_from_message_converts_non_assistant_message() -> None:
    active = get_model("mockllm/model")
    init_active_model(active, GenerateConfig())

    output = ModelOutput.from_message(ChatMessageUser(content="2"))

    assert output.model == active.api.model_name
    assert output.message.text == "2"


def test_from_message_prefers_explicit_and_message_model() -> None:
    init_active_model(get_model("mockllm/model"), GenerateConfig())

    with_model = ChatMessageAssistant(content="2", model="from-message")
    without_model = ChatMessageAssistant(content="2")

    assert ModelOutput.from_message(with_model).model == "from-message"
    assert ModelOutput.from_message(with_model, model="explicit").model == "explicit"
    assert ModelOutput.from_message(without_model, model="explicit").model == "explicit"


def test_from_message_without_active_model() -> None:
    assert ModelOutput.from_message(ChatMessageAssistant(content="2")).model == ""


def test_from_message_keeps_empty_message_model() -> None:
    init_active_model(get_model("mockllm/model"), GenerateConfig())

    output = ModelOutput.from_message(ChatMessageAssistant(content="2", model=""))

    assert output.model == ""
