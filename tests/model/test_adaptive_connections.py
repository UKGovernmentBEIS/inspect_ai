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
async def test_adaptive_on_by_default() -> None:
    """`adaptive_connections` defaults to enabled — a controller is active.

    `None` (the field default) resolves to `AdaptiveConcurrency()` defaults
    via `resolve_adaptive`. To opt out, the user passes `False` explicitly.
    """
    init_concurrency()
    fn = _capture_controller_during_generate()
    model = get_model("mockllm/model", custom_outputs=fn)
    await model.generate("hello")
    captures = fn.captures  # type: ignore[attr-defined]
    assert len(captures) == 1
    controller, had_retry = captures[0]
    assert controller is not None
    assert had_retry is False
    assert len(adaptive_controllers()) == 1


@pytest.mark.anyio
async def test_adaptive_explicit_false_disables() -> None:
    """`adaptive_connections=False` is the explicit opt-out, no controller."""
    init_concurrency()
    fn = _capture_controller_during_generate()
    model = get_model("mockllm/model", custom_outputs=fn)
    await model.generate(
        "hello",
        config=GenerateConfig(adaptive_connections=False),
    )
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


async def test_manual_connection_limit_change_excluded_from_eval_stats() -> None:
    """A control-channel `set_max` retune (reason='manual') doesn't crash capture.

    Regression: `set_max` records a `manual` history entry. collect_eval_data
    maps controller history into `ConnectionLimitChange`, whose `reason` enum has
    only adaptive reasons — so a `manual` entry must be skipped, not passed
    through (which would raise a ValidationError and fail the whole eval).
    """
    from inspect_ai._eval.task.log import collect_eval_data
    from inspect_ai.log._log import EvalStats
    from inspect_ai.util._concurrency import (
        AdaptiveConcurrency,
        AdaptiveConcurrencyController,
        get_or_create_semaphore,
    )

    init_concurrency()
    ctrl = await get_or_create_semaphore(
        "mockllm/model", 10, None, True, AdaptiveConcurrency(min=1, max=100, start=50)
    )
    assert isinstance(ctrl, AdaptiveConcurrencyController)
    ctrl.set_max(20)  # records a 50 -> 20 "manual" change in controller history

    stats = EvalStats()
    collect_eval_data(stats)  # must not raise on the "manual" reason
    # the manual retune (the only recorded change) is excluded from the
    # log's adaptive-scaling history
    assert stats.connection_limit_history == []


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
    assert _parse_adaptive_connections_cli("yes") is True
    assert _parse_adaptive_connections_cli("false") is False
    assert _parse_adaptive_connections_cli("no") is False

    # bare integer → max shorthand (int form, resolved later by resolve_adaptive)
    assert _parse_adaptive_connections_cli("200") == 200
    assert _parse_adaptive_connections_cli("50") == 50
    # `1` and `0` are the integer shorthand, not bool aliases — users who want
    # explicit bool should pass `true`/`false`
    assert _parse_adaptive_connections_cli("1") == 1
    assert _parse_adaptive_connections_cli("0") == 0

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
    """Explicit max_samples returns a static ResizableLimiter, not the adaptive path.

    No warning — anticipating adaptive becoming default-on, in which case any
    deliberate max_samples setting would otherwise produce noise. The limiter is
    resizable (the control channel can retune max_samples mid-eval) but still the
    non-adaptive path — its limit starts at the requested value.
    """
    from inspect_ai._eval.task.run import create_sample_semaphore
    from inspect_ai.log._log import EvalConfig
    from inspect_ai.util._concurrency import DynamicSampleLimiter, ResizableLimiter

    sem = create_sample_semaphore(
        config=EvalConfig(max_samples=5),
        generate_config=GenerateConfig(
            adaptive_connections=AdaptiveConcurrency(min=1, max=80, start=10)
        ),
        modelapi=None,
    )
    assert isinstance(sem, ResizableLimiter)
    assert not isinstance(sem, DynamicSampleLimiter)
    assert sem.limit == 5


async def test_ensure_model_controller_eager_creation() -> None:
    """Run startup pre-creates the model's adaptive controller.

    Controllers are normally created lazily on the first generate; the eager
    call closes the startup window where `ctl limits --max-connections` found
    no controllers and dropped the retune with a misleading "not using
    adaptive connections" warning. Also verifies the eager key matches the
    generate-path key (registry coalescing) and the task's sample limiter
    adopts the eagerly created controller.
    """
    from inspect_ai._eval.task.run import create_sample_semaphore
    from inspect_ai.log._log import EvalConfig
    from inspect_ai.model._model import ensure_model_controller
    from inspect_ai.util._concurrency import DynamicSampleLimiter, init_concurrency

    init_concurrency()
    model = get_model("mockllm/model")

    # eager creation at run startup (before any generate)
    await ensure_model_controller(model, GenerateConfig(adaptive_connections=True))
    ctrls = adaptive_controllers()
    assert len(ctrls) == 1

    # a generate reuses the same controller (keys coalesce)
    await model.generate("hello", config=GenerateConfig(adaptive_connections=True))
    assert adaptive_controllers() == ctrls

    # the task's sample limiter adopts the eagerly created controller
    sem = create_sample_semaphore(
        EvalConfig(),
        GenerateConfig(adaptive_connections=True),
        model.api,
        task_id="t-eager",
    )
    assert isinstance(sem, DynamicSampleLimiter)
    assert sem.controller is ctrls[0]

    # no-op when adaptive isn't active
    init_concurrency()
    await ensure_model_controller(
        model, GenerateConfig(adaptive_connections=True, max_connections=10)
    )
    assert adaptive_controllers() == []


def test_sample_semaphore_shared_across_retry_attempts() -> None:
    """The same task_id reuses its semaphore, preserving a mid-flight retune.

    Sample semaphores are task-scoped: an in-process task retry calls
    create_sample_semaphore again (fresh attempt), and must get back the same
    limiter so a `ctl limits --max-samples` retune survives the retry instead
    of silently reverting to the config value.
    """
    from inspect_ai._eval.task.run import create_sample_semaphore
    from inspect_ai.log._log import EvalConfig
    from inspect_ai.util._concurrency import ResizableLimiter, init_concurrency

    init_concurrency()
    sem = create_sample_semaphore(
        config=EvalConfig(max_samples=20),
        generate_config=GenerateConfig(),
        task_id="task-1",
    )
    assert isinstance(sem, ResizableLimiter)
    sem.limit = 2  # mid-flight control-channel retune

    # retry attempt: same task_id → same limiter, runtime setpoint intact
    again = create_sample_semaphore(
        config=EvalConfig(max_samples=20),
        generate_config=GenerateConfig(),
        task_id="task-1",
    )
    assert again is sem
    assert sem.limit == 2

    # a different task gets its own limiter
    other = create_sample_semaphore(
        config=EvalConfig(max_samples=20),
        generate_config=GenerateConfig(),
        task_id="task-2",
    )
    assert other is not sem

    # a new run (init_concurrency) starts fresh
    init_concurrency()
    fresh = create_sample_semaphore(
        config=EvalConfig(max_samples=20),
        generate_config=GenerateConfig(),
        task_id="task-1",
    )
    assert fresh is not sem
    assert isinstance(fresh, ResizableLimiter)
    assert fresh.limit == 20


def test_sample_semaphore_static_path_unchanged() -> None:
    """Without adaptive, returns a ResizableLimiter sized from max_connections."""
    from inspect_ai._eval.task.run import create_sample_semaphore
    from inspect_ai.log._log import EvalConfig
    from inspect_ai.util._concurrency import ResizableLimiter

    sem = create_sample_semaphore(
        config=EvalConfig(),
        generate_config=GenerateConfig(max_connections=15),
        modelapi=None,
    )
    assert isinstance(sem, ResizableLimiter)
    assert sem.limit == 15


def test_sample_semaphore_batch_mode_disables_adaptive() -> None:
    """Batch mode silently overrides adaptive_connections at the sample limiter layer too.

    Without this, a batched eval with adaptive_connections=True would create
    a DynamicSampleLimiter that tracks a controller no one is feeding signals
    to (since Model._connection_concurrency takes the static path in batch
    mode).
    """
    from inspect_ai._eval.task.run import create_sample_semaphore
    from inspect_ai.log._log import EvalConfig
    from inspect_ai.model._generate_config import BatchConfig
    from inspect_ai.util._concurrency import (
        DynamicSampleLimiter,
        ResizableLimiter,
        init_concurrency,
    )

    init_concurrency()
    sem = create_sample_semaphore(
        config=EvalConfig(),
        generate_config=GenerateConfig(
            adaptive_connections=True,
            batch=BatchConfig(),
        ),
        modelapi=None,
    )
    assert isinstance(sem, ResizableLimiter)
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


# ---------- count_tokens has no per-model concurrency cap ----------


@pytest.mark.anyio
async def test_count_tokens_no_concurrency_cap(monkeypatch) -> None:
    """`Model.count_tokens` is not capped — concurrent calls all run in parallel.

    Historically there was a per-model `concurrency(...)` semaphore at limit
    10 around `count_tokens`. It was removed because (a) the cost is O(delta)
    via compaction's baseline mechanism, (b) `max_samples` already provides a
    structural ceiling, (c) retries handle 429s symmetrically with generate,
    and (d) provider count_tokens envelopes are wider than generate envelopes.

    This guards against re-introducing such a cap. We monkey-patch the model
    API's `count_tokens` to track peak in-flight calls; without a cap the
    peak should reach (or near) the launched-task count, well above 10.
    """
    import anyio

    from inspect_ai._util._async import tg_collect

    init_concurrency()
    model = get_model("mockllm/model")

    in_flight = 0
    peak_in_flight = 0

    async def counting_count_tokens(self, input, config=None):
        nonlocal in_flight, peak_in_flight
        in_flight += 1
        peak_in_flight = max(peak_in_flight, in_flight)
        try:
            await anyio.sleep(0.05)
            return 1
        finally:
            in_flight -= 1

    monkeypatch.setattr(type(model.api), "count_tokens", counting_count_tokens)

    # Launch 50 concurrent count_tokens calls. With the old 10-cap, peak
    # in-flight would max at 10. Without the cap, peak should be ~50.
    await tg_collect([lambda: model.count_tokens("hello") for _ in range(50)])

    assert peak_in_flight > 10, (
        f"count_tokens appears capped at <=10 concurrent: peak in-flight = {peak_in_flight}"
    )


# ---------- adaptive_active / resolve_adaptive helpers ----------


def test_adaptive_active_predicate() -> None:
    """Predicate matches precedence rules used by all three call sites.

    `Model._connection_concurrency`, `create_sample_semaphore`, and
    `eval_set`'s adaptive-active check should all behave identically.
    """
    from inspect_ai.util._concurrency import adaptive_active

    # default-on (None resolves to adaptive)
    assert adaptive_active(None, None, None) is True
    assert adaptive_active(True, None, None) is True
    assert adaptive_active(200, None, None) is True
    assert adaptive_active(AdaptiveConcurrency(max=50), None, None) is True

    # explicit False opts out
    assert adaptive_active(False, None, None) is False

    # explicit max_connections takes precedence
    assert adaptive_active(True, 100, None) is False
    assert adaptive_active(None, 100, None) is False

    # batch=True (or any truthy batch config) takes precedence
    assert adaptive_active(True, None, True) is False
    assert adaptive_active(None, None, "any-truthy-batch-config") is False


def test_resolve_adaptive_returns_concrete_AdaptiveConcurrency() -> None:
    from inspect_ai.util._concurrency import resolve_adaptive

    # None and True both produce default AdaptiveConcurrency
    a = resolve_adaptive(None)
    b = resolve_adaptive(True)
    assert isinstance(a, AdaptiveConcurrency)
    assert isinstance(b, AdaptiveConcurrency)
    assert (a.min, a.start, a.max) == (b.min, b.start, b.max)

    # int → max shorthand, with default min/start
    c = resolve_adaptive(200)
    assert isinstance(c, AdaptiveConcurrency)
    assert c.max == 200

    # explicit AdaptiveConcurrency passes through
    custom = AdaptiveConcurrency(min=2, start=10, max=50)
    d = resolve_adaptive(custom)
    assert d is custom


def test_default_max_is_100() -> None:
    """`AdaptiveConcurrency()` defaults `max` to 100 (lowered from 200)."""
    a = AdaptiveConcurrency()
    assert a.max == 100


@pytest.mark.anyio
async def test_adaptive_int_shorthand_at_field_level() -> None:
    """`GenerateConfig(adaptive_connections=N)` resolves to `max=N` adaptive."""
    init_concurrency()
    fn = _make_output_fn()
    model = get_model("mockllm/model", custom_outputs=fn)
    await model.generate(
        "hello",
        config=GenerateConfig(adaptive_connections=50),
    )
    ctrls = adaptive_controllers()
    assert len(ctrls) == 1
    # Controller's adaptive bound max should be 50 — the int shorthand.
    # We can't easily inspect the bound directly, but starting concurrency
    # should be the AdaptiveConcurrency() default `start=20` clamped to max=50.
    # Easier: verify the controller exists at all (smoke test). The
    # `resolve_adaptive` unit test above covers the value-level mapping.
    assert ctrls[0].concurrency <= 50
