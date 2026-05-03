"""End-to-end tests for adaptive_connections wiring through Model.generate."""

from collections.abc import Callable

import pytest

from inspect_ai._util.retry import report_http_retry
from inspect_ai.model import (
    GenerateConfig,
    get_model,
)
from inspect_ai.model._chat_message import ChatMessage
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.tool import ToolChoice, ToolInfo
from inspect_ai.util import AdaptiveConcurrency
from inspect_ai.util._concurrency import (
    _active_controller,
    _request_had_retry,
    adaptive_controllers,
    init_concurrency,
)


def _make_output_fn() -> Callable[..., ModelOutput]:
    def out(
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        return ModelOutput.from_content(model="mockllm", content="ok")

    return out


def _capture_controller_during_generate() -> Callable[..., ModelOutput]:
    """Build a custom_outputs fn that reports the active controller / had_retry on each call."""
    captures: list[tuple[object, bool]] = []

    def out(
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        captures.append((_active_controller.get(), _request_had_retry.get()))
        return ModelOutput.from_content(model="mockllm", content="ok")

    out.captures = captures  # type: ignore[attr-defined]
    return out


@pytest.mark.anyio
async def test_adaptive_off_by_default() -> None:
    """Without adaptive_connections, no controller is set during generate."""
    init_concurrency()
    fn = _capture_controller_during_generate()
    model = get_model("mockllm/model", custom_outputs=fn)
    await model.generate("hello")
    captures = fn.captures  # type: ignore[attr-defined]
    assert captures == [(None, False)]
    assert adaptive_controllers() == []


@pytest.mark.anyio
async def test_adaptive_sets_active_controller_during_generate() -> None:
    init_concurrency()
    fn = _capture_controller_during_generate()
    model = get_model("mockllm/model", custom_outputs=fn)
    await model.generate(
        "hello",
        config=GenerateConfig(adaptive_connections=True),
    )
    captures = fn.captures  # type: ignore[attr-defined]
    assert len(captures) == 1
    controller, had_retry = captures[0]
    assert controller is not None
    assert had_retry is False
    # controller is registered for status display / log capture
    ctrls = adaptive_controllers()
    assert len(ctrls) == 1


@pytest.mark.anyio
async def test_adaptive_struct_config_used() -> None:
    init_concurrency()
    fn = _make_output_fn()
    model = get_model("mockllm/model", custom_outputs=fn)
    await model.generate(
        "hello",
        config=GenerateConfig(
            adaptive_connections=AdaptiveConcurrency(min=2, max=50, start=15)
        ),
    )
    ctrls = adaptive_controllers()
    assert len(ctrls) == 1
    assert ctrls[0].concurrency == 15  # started at custom value


@pytest.mark.anyio
async def test_adaptive_with_max_retries_zero_works() -> None:
    """max_retries=0 doesn't disable retry feedback to the controller.

    Provider SDK internal retries (tracked by HttpHooks) fire report_http_retry
    independently of Inspect's outer retry loop, so the controller still gets
    scale-down signals. And the controller's `max` bound caps growth even if
    no retry signals ever arrive.
    """
    init_concurrency()
    model = get_model("mockllm/model")
    await model.generate(
        "hello",
        config=GenerateConfig(adaptive_connections=True, max_retries=0),
    )
    ctrls = adaptive_controllers()
    assert len(ctrls) == 1


@pytest.mark.anyio
async def test_explicit_max_connections_wins_over_adaptive() -> None:
    """Explicit max_connections takes precedence over adaptive_connections.

    Once adaptive becomes default-on, deliberate max_connections settings must
    continue to be honored — so the static path is taken when both are set.
    """
    init_concurrency()
    fn = _capture_controller_during_generate()
    model = get_model("mockllm/model", custom_outputs=fn)
    await model.generate(
        "hello",
        config=GenerateConfig(adaptive_connections=True, max_connections=20),
    )
    captures = fn.captures  # type: ignore[attr-defined]
    # static path was taken: no controller is active during generate
    assert captures == [(None, False)]
    # no adaptive controller was created
    assert adaptive_controllers() == []


@pytest.mark.anyio
async def test_batch_mode_disables_adaptive() -> None:
    """Batch mode silently overrides adaptive_connections.

    Batch APIs run on a separate quota, the per-request concurrency model
    doesn't bind, and the batch worker's background-task ContextVars don't
    propagate retry/success signals back to awaiting generates — so adaptive
    accounting would be incorrect even if we did set up the controller.
    """
    from inspect_ai.model._generate_config import BatchConfig

    init_concurrency()
    fn = _capture_controller_during_generate()
    model = get_model("mockllm/model", custom_outputs=fn)
    await model.generate(
        "hello",
        config=GenerateConfig(
            adaptive_connections=True,
            batch=BatchConfig(),
        ),
    )
    captures = fn.captures  # type: ignore[attr-defined]
    # static path was taken: no controller active during generate
    assert captures == [(None, False)]
    assert adaptive_controllers() == []


@pytest.mark.anyio
async def test_report_http_retry_signals_active_controller() -> None:
    """When called inside generate, report_http_retry sets had_retry and notifies controller."""
    init_concurrency()

    saw_controller: list[object] = []

    def out(
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        # simulate provider-level rate-limit signal during the generate call
        report_http_retry(kind="rate_limit")
        saw_controller.append(_active_controller.get())
        return ModelOutput.from_content(model="mockllm", content="ok")

    model = get_model("mockllm/model", custom_outputs=out)
    await model.generate(
        "hello",
        config=GenerateConfig(adaptive_connections=True),
    )

    ctrls = adaptive_controllers()
    assert len(ctrls) == 1
    # the retry should have been observed and recorded a scale-down event
    history = ctrls[0].history
    assert any(entry[4] == "rate_limit" for entry in history)


@pytest.mark.anyio
async def test_clean_success_does_not_modify_limit_below_round_size() -> None:
    """A single clean generate doesn't reach round_size, so no scale change happens."""
    init_concurrency()
    model = get_model("mockllm/model", custom_outputs=_make_output_fn())
    await model.generate("hello", config=GenerateConfig(adaptive_connections=True))
    ctrls = adaptive_controllers()
    assert len(ctrls) == 1
    # default start=20, round_size=20, only 1 success → no change yet
    assert ctrls[0].concurrency == 20
    assert ctrls[0].history == []


@pytest.mark.anyio
async def test_connection_limit_history_captured_in_eval_stats() -> None:
    """collect_eval_data populates EvalStats.connection_limit_history from registered controllers."""
    from inspect_ai._eval.task.log import collect_eval_data
    from inspect_ai.log._log import EvalStats

    init_concurrency()

    def out(
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        report_http_retry(kind="rate_limit")
        return ModelOutput.from_content(model="mockllm", content="ok")

    model = get_model("mockllm/model", custom_outputs=out)
    await model.generate("hello", config=GenerateConfig(adaptive_connections=True))

    stats = EvalStats()
    collect_eval_data(stats)
    assert len(stats.connection_limit_history) >= 1
    entry = stats.connection_limit_history[0]
    assert entry.reason == "rate_limit"
    assert entry.model  # non-empty


def test_parse_adaptive_connections_cli_value_forms() -> None:
    """The CLI parser handles bool keywords and shorthand strings, with None passthrough.

    Verifies the four user-visible forms of `--adaptive-connections VALUE`.
    """
    from inspect_ai._cli.eval import _parse_adaptive_connections_cli

    # absence
    assert _parse_adaptive_connections_cli(None) is None

    # bool keywords (case-insensitive)
    assert _parse_adaptive_connections_cli("true") is True
    assert _parse_adaptive_connections_cli("TRUE") is True
    assert _parse_adaptive_connections_cli("1") is True
    assert _parse_adaptive_connections_cli("yes") is True
    assert _parse_adaptive_connections_cli("false") is False
    assert _parse_adaptive_connections_cli("0") is False
    assert _parse_adaptive_connections_cli("no") is False

    # bounds shorthand
    result = _parse_adaptive_connections_cli("4-80")
    assert isinstance(result, AdaptiveConcurrency)
    assert (result.min, result.max, result.start) == (4, 80, 20)

    result = _parse_adaptive_connections_cli("4-20-80")
    assert isinstance(result, AdaptiveConcurrency)
    assert (result.min, result.start, result.max) == (4, 20, 80)


def test_parse_adaptive_connections_cli_invalid_raises_click_error() -> None:
    """Invalid values raise click.BadParameter, not raw pydantic ValidationError.

    This way the CLI surfaces a clean usage message. Without this wrapping,
    users hitting `--adaptive-connections nope` saw a multi-line pydantic
    traceback as the error output.
    """
    import click

    from inspect_ai._cli.eval import _parse_adaptive_connections_cli

    with pytest.raises(click.BadParameter, match="not a valid value"):
        _parse_adaptive_connections_cli("nope")
    with pytest.raises(click.BadParameter, match="not a valid value"):
        _parse_adaptive_connections_cli("1-2-3-4")  # too many parts
    with pytest.raises(click.BadParameter, match="not a valid value"):
        _parse_adaptive_connections_cli("not-a-number")


def test_attempt_timeout_marks_as_retry_in_should_retry() -> None:
    """should_retry(AttemptTimeoutError) must fire report_http_retry.

    Otherwise timeout pressure is invisible to the adaptive controller and
    a request that timed out and then succeeded would be counted as a clean
    success — pushing the controller upward under timeout pressure.
    """
    from inspect_ai.model._model import AttemptTimeoutError
    from inspect_ai.util._concurrency import _request_had_retry, init_concurrency

    init_concurrency()
    # set up a model and use should_retry directly
    model = get_model("mockllm/model")
    # ContextVars need to be in a fresh state. Capture token + reset in finally
    # so we don't leak the changed value across tests.
    token = _request_had_retry.set(False)
    try:
        result = model.should_retry(AttemptTimeoutError(timeout=30))
        assert result is True
        assert _request_had_retry.get() is True
    finally:
        _request_had_retry.reset(token)


@pytest.mark.anyio
async def test_cache_hits_do_not_count_as_adaptive_successes(tmp_path) -> None:
    """Cache-served generates don't fire notify_success on the controller.

    Cache hits don't exercise the rate limit, so they must be neutral —
    otherwise a cached run could slow-start the controller to its max without
    any provider traffic, and uncached calls would then hit the API at
    inflated concurrency.
    """
    from inspect_ai.model._cache import CachePolicy

    # point cache at a temp dir so we don't pollute the user's cache
    monkey_env = pytest.MonkeyPatch()
    monkey_env.setenv("INSPECT_CACHE_DIR", str(tmp_path))
    try:
        init_concurrency()
        model = get_model("mockllm/model")
        cfg = GenerateConfig(
            adaptive_connections=AdaptiveConcurrency(min=1, max=200, start=10),
            cache=CachePolicy(),
        )

        # First call populates the cache (this will count as a real success)
        await model.generate("hello", config=cfg)

        ctrls = adaptive_controllers()
        assert len(ctrls) == 1
        success_count_after_first = ctrls[0]._success_count

        # Many cache hits — none should bump the success counter
        for _ in range(50):
            await model.generate("hello", config=cfg)

        # success counter should be unchanged from the first (real) call
        assert ctrls[0]._success_count == success_count_after_first
        # and limit should not have grown
        assert ctrls[0].concurrency == 10
    finally:
        monkey_env.undo()


# ---------- create_sample_semaphore ----------


def test_sample_semaphore_uses_dynamic_for_adaptive() -> None:
    """When adaptive is set and max_samples is unset, returns DynamicSampleLimiter."""
    import anyio as _anyio

    from inspect_ai._eval.task.run import create_sample_semaphore
    from inspect_ai.log._log import EvalConfig
    from inspect_ai.util._concurrency import DynamicSampleLimiter, init_concurrency

    init_concurrency()
    sem = create_sample_semaphore(
        config=EvalConfig(),  # max_samples unset
        generate_config=GenerateConfig(adaptive_connections=True),
        modelapi=None,
    )
    assert isinstance(sem, DynamicSampleLimiter)
    assert not isinstance(sem, _anyio.Semaphore)


def test_sample_semaphore_explicit_max_samples_wins() -> None:
    """Explicit max_samples returns plain Semaphore even when adaptive is enabled.

    No warning — anticipating adaptive becoming default-on, in which case any
    deliberate max_samples setting would otherwise produce noise.
    """
    import anyio as _anyio

    from inspect_ai._eval.task.run import create_sample_semaphore
    from inspect_ai.log._log import EvalConfig

    sem = create_sample_semaphore(
        config=EvalConfig(max_samples=5),
        generate_config=GenerateConfig(
            adaptive_connections=AdaptiveConcurrency(min=1, max=80, start=10)
        ),
        modelapi=None,
    )
    assert isinstance(sem, _anyio.Semaphore)


def test_sample_semaphore_static_path_unchanged() -> None:
    """Without adaptive, returns Semaphore with the legacy max_connections-derived size."""
    import anyio as _anyio

    from inspect_ai._eval.task.run import create_sample_semaphore
    from inspect_ai.log._log import EvalConfig

    sem = create_sample_semaphore(
        config=EvalConfig(),
        generate_config=GenerateConfig(max_connections=15),
        modelapi=None,
    )
    assert isinstance(sem, _anyio.Semaphore)


def test_sample_semaphore_batch_mode_disables_adaptive() -> None:
    """Batch mode silently overrides adaptive_connections at the sample limiter layer too.

    Without this, a batched eval with adaptive_connections=True would create
    a DynamicSampleLimiter that tracks a controller no one is feeding signals
    to (since Model._connection_concurrency takes the static path in batch
    mode).
    """
    import anyio as _anyio

    from inspect_ai._eval.task.run import create_sample_semaphore
    from inspect_ai.log._log import EvalConfig
    from inspect_ai.model._generate_config import BatchConfig
    from inspect_ai.util._concurrency import DynamicSampleLimiter, init_concurrency

    init_concurrency()
    sem = create_sample_semaphore(
        config=EvalConfig(),
        generate_config=GenerateConfig(
            adaptive_connections=True,
            batch=BatchConfig(),
        ),
        modelapi=None,
    )
    assert isinstance(sem, _anyio.Semaphore)
    assert not isinstance(sem, DynamicSampleLimiter)


# ---------- Rate-limit vs transient classification (end-to-end) ----------


@pytest.mark.anyio
async def test_transient_retries_do_not_scale_controller_down() -> None:
    """5xx / timeout retries during generate must not shrink the adaptive controller.

    Earlier code conflated all retries with rate-limit signals; the fix is for
    transients to pause scale-up only.
    """
    init_concurrency()

    def out(
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        report_http_retry()  # default: kind="transient"
        return ModelOutput.from_content(model="mockllm", content="ok")

    model = get_model("mockllm/model", custom_outputs=out)
    await model.generate("hello", config=GenerateConfig(adaptive_connections=True))

    ctrls = adaptive_controllers()
    assert len(ctrls) == 1
    # transient retry must not have produced any scale-down history
    assert all(entry[4] != "rate_limit" for entry in ctrls[0].history)


@pytest.mark.anyio
async def test_transient_retry_blocks_success_counting() -> None:
    """A transient retry during generate prevents that success from counting toward scale-up."""
    init_concurrency()

    def out(
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        report_http_retry()  # transient
        return ModelOutput.from_content(model="mockllm", content="ok")

    model = get_model("mockllm/model", custom_outputs=out)
    cfg = GenerateConfig(
        adaptive_connections=AdaptiveConcurrency(min=1, max=200, start=4)
    )
    # 4 generates would normally complete a slow-start round (round_size=max(4,4)=4)
    for _ in range(4):
        await model.generate("hello", config=cfg)

    ctrls = adaptive_controllers()
    assert len(ctrls) == 1
    # because each generate had a transient retry, none counted as a clean success
    assert ctrls[0].concurrency == 4
