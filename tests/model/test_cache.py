from datetime import datetime, timezone

from test_helpers.utils import run_example

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.event._model import ModelEvent
from inspect_ai.log import EvalSample
from inspect_ai.model import get_model
from inspect_ai.solver import Generate, TaskState, generate, solver


def test_cache_examples():
    logs = run_example("cache.py", model="mockllm/model")
    assert all(log.status == "success" for log in logs)


def test_cache():
    # helper to check for cache hit
    def sample_cache_hit(sample: EvalSample) -> bool:
        return (
            sum(
                1
                for event in sample.events
                if (isinstance(event, ModelEvent) and event.cache == "read")
            )
            > 0
        )

    timestamp = str(datetime.now(timezone.utc))

    def check_eval_with_cache(cache_hit: bool):
        log = eval(
            Task(
                dataset=[Sample(input=f"What is the timestamp: {timestamp}")],
                solver=[generate(cache=True)],
            ),
            model="mockllm/model",
        )[0]
        assert log.samples
        assert sample_cache_hit(log.samples[0]) == cache_hit

    # first eval should miss the cache and the second should hit it
    check_eval_with_cache(False)
    check_eval_with_cache(True)


def test_cache_hit_records_model_usage():
    """Cache hits must update per-sample and eval-level model_usage.

    Regression test for a bug where the cache-hit branch of `Model._generate`
    returned early without calling `record_and_check_model_usage`, so cached
    usage was missing from both `sample.model_usage` and `EvalStats.model_usage`
    even though `ModelEvent`s were emitted correctly. The omission showed up
    most visibly with multi-model evals: a per-sample bucket could end up
    empty while the corresponding events were all present.
    """

    @solver
    def two_model_solver():
        sonnet = get_model("mockllm/sonnet")
        opus = get_model("mockllm/opus")

        async def solve(state: TaskState, generate_: Generate) -> TaskState:
            for _ in range(3):
                await sonnet.generate(state.input_text, cache=True)
            await opus.generate(state.input_text, cache=True)
            return state

        return solve

    # use a stable input so the second eval gets cache hits on every call
    timestamp = str(datetime.now(timezone.utc))
    task = Task(
        dataset=[
            Sample(input=f"sample-a {timestamp}"),
            Sample(input=f"sample-b {timestamp}"),
        ],
        solver=two_model_solver(),
    )

    def assert_per_sample_usage_matches_events(log):
        assert log.samples is not None
        for sample in log.samples:
            event_models = {
                ev.model for ev in sample.events if isinstance(ev, ModelEvent)
            }
            usage_models = set((sample.model_usage or {}).keys())
            assert event_models == usage_models, (
                f"sample {sample.id}: events have models {event_models} "
                f"but model_usage has {usage_models}"
            )

    # first run warms the cache; sample 2's repeated input will already hit
    # the cache that sample 1 populated
    log_warm = eval(task, model="mockllm/driver")[0]
    assert_per_sample_usage_matches_events(log_warm)

    # second run: every call is a cache hit
    log_cached = eval(task, model="mockllm/driver")[0]
    assert_per_sample_usage_matches_events(log_cached)

    # eval-level model_usage must include both models even when everything
    # came from cache
    assert set(log_cached.stats.model_usage.keys()) == {
        "mockllm/sonnet",
        "mockllm/opus",
    }
    for model_usage in log_cached.stats.model_usage.values():
        assert model_usage.total_tokens > 0
