"""Tests for driving a running task from a `SampleSource`.

The source seeds the task with `initial_samples()`, observes each result via
`sample_complete` (which may return follow-up samples), and produces more from
`next_samples()` until it returns `None` — all within one task / log. Added
samples are live: they start as soon as there is free capacity.
"""

import anyio
import pytest

from inspect_ai import SampleSource, Task, enqueue_sample, eval
from inspect_ai.dataset import Sample
from inspect_ai.log import EvalLog, EvalSample
from inspect_ai.solver import Generate, Solver, TaskState, generate, solver


def _sample_inputs(log: EvalLog) -> list[str]:
    return sorted(str(sample.input) for sample in (log.samples or []))


class _Generations(SampleSource):
    """Produces `count` samples one at a time; each produced after the prior."""

    def __init__(self, count: int) -> None:
        self.count = count
        self.samples_seen: list[str] = []
        self._produced = 1  # s0 is the initial seed

    def initial_samples(self) -> list[Sample]:
        return [Sample(input="s0", target="ok")]

    async def sample_complete(self, sample: EvalSample) -> None:
        self.samples_seen.append(str(sample.input))

    async def next_samples(self) -> list[Sample] | None:
        if self._produced < self.count:
            name = f"s{self._produced}"
            self._produced += 1
            return [Sample(input=name, target="ok")]
        return None


def test_sample_source_runs_generations_in_one_task() -> None:
    source = _Generations(3)
    logs = eval(
        Task(dataset=source, solver=[generate()]),
        model="mockllm/model",
        display="none",
    )

    # all generations ran within a single task/log, observed by the source
    assert len(logs) == 1
    log = logs[0]
    assert log.status == "success"
    assert _sample_inputs(log) == ["s0", "s1", "s2"]
    assert sorted(source.samples_seen) == ["s0", "s1", "s2"]
    # injected samples continue the seed's auto-id numbering
    assert sorted(sample.id for sample in (log.samples or [])) == [1, 2, 3]


def test_sample_source_seed_only_when_next_is_none() -> None:
    # next_samples() returns None immediately -> only the seed runs
    logs = eval(
        Task(dataset=_Generations(1), solver=[generate()]),
        model="mockllm/model",
        display="none",
    )
    assert logs[0].status == "success"
    assert _sample_inputs(logs[0]) == ["s0"]


def test_sample_complete_returning_samples_chains_generations() -> None:
    # the simplest source: return follow-up samples straight from
    # sample_complete, no next_samples(). The task chains until a completion
    # returns nothing.
    class _Chain(SampleSource):
        def __init__(self, count: int) -> None:
            self.count = count
            self._produced = 1  # s0 is the seed

        def initial_samples(self) -> list[Sample]:
            return [Sample(input="s0", target="ok")]

        async def sample_complete(self, sample: EvalSample) -> list[Sample] | None:
            if self._produced < self.count:
                name = f"s{self._produced}"
                self._produced += 1
                return [Sample(input=name, target="ok")]
            return None

    logs = eval(
        Task(dataset=_Chain(3), solver=[generate()]),
        model="mockllm/model",
        display="none",
    )
    assert logs[0].status == "success"
    assert _sample_inputs(logs[0]) == ["s0", "s1", "s2"]


def test_sample_source_factory_seed_and_callbacks() -> None:
    # from_samples() builds a SampleSource from a seed + callbacks (no
    # subclass); next_samples closes over shared state for two more samples
    produced = [1]
    samples_seen: list[str] = []

    async def next_samples() -> list[Sample] | None:
        if produced[0] < 3:
            name = f"s{produced[0]}"
            produced[0] += 1
            return [Sample(input=name, target="ok")]
        return None

    async def on_sample(sample: EvalSample) -> None:
        samples_seen.append(str(sample.input))

    source = SampleSource.from_samples(
        [Sample(input="s0", target="ok")],
        next_samples=next_samples,
        sample_complete=on_sample,
    )
    logs = eval(
        Task(dataset=source, solver=[generate()]),
        model="mockllm/model",
        display="none",
    )
    assert logs[0].status == "success"
    assert _sample_inputs(logs[0]) == ["s0", "s1", "s2"]
    assert sorted(samples_seen) == ["s0", "s1", "s2"]


def test_sample_source_factory_seed_only_runs_once() -> None:
    # omitting next_samples stops after the seed (equivalent to a plain dataset)
    logs = eval(
        Task(
            dataset=SampleSource.from_samples([Sample(input="only", target="ok")]),
            solver=[generate()],
        ),
        model="mockllm/model",
        display="none",
    )
    assert logs[0].status == "success"
    assert _sample_inputs(logs[0]) == ["only"]


def test_sample_source_empty_seed_pulls_from_next_samples() -> None:
    # an empty seed is allowed: the task starts by calling next_samples()
    produced = [False]

    class _EmptySeed(SampleSource):
        async def next_samples(self) -> list[Sample] | None:
            if not produced[0]:
                produced[0] = True
                return [Sample(input="only", target="ok")]
            return None

    logs = eval(
        Task(dataset=_EmptySeed(), solver=[generate()]),
        model="mockllm/model",
        display="none",
    )
    assert logs[0].status == "success"
    assert _sample_inputs(logs[0]) == ["only"]


def test_sample_source_epochs_apply_to_injected_samples() -> None:
    # injected samples run for the task's configured epochs, like the seed
    class _Two(SampleSource):
        def __init__(self) -> None:
            self._done = False

        def initial_samples(self) -> list[Sample]:
            return [Sample(input="seed", target="ok")]

        async def next_samples(self) -> list[Sample] | None:
            if not self._done:
                self._done = True
                return [Sample(input="added", target="ok")]
            return None

    logs = eval(
        Task(dataset=_Two(), solver=[generate()], epochs=2),
        model="mockllm/model",
        display="none",
    )
    log = logs[0]
    assert log.status == "success"
    runs = sorted((str(sample.input), sample.epoch) for sample in (log.samples or []))
    assert runs == [("added", 1), ("added", 2), ("seed", 1), ("seed", 2)]


def test_sample_source_explicit_and_auto_ids() -> None:
    # explicit injected ids are honored; auto-ids skip ids already in use
    class _Ids(SampleSource):
        def __init__(self) -> None:
            self._produced = False

        def initial_samples(self) -> list[Sample]:
            return [Sample(input="seed", target="ok")]

        async def next_samples(self) -> list[Sample] | None:
            if not self._produced:
                self._produced = True
                return [
                    Sample(id=2, input="explicit", target="ok"),
                    Sample(input="auto", target="ok"),
                ]
            return None

    logs = eval(
        Task(dataset=_Ids(), solver=[generate()]),
        model="mockllm/model",
        display="none",
    )
    log = logs[0]
    assert log.status == "success"
    ids = {str(sample.input): sample.id for sample in (log.samples or [])}
    assert ids["seed"] == 1
    assert ids["explicit"] == 2
    assert ids["auto"] == 3  # auto-id skipped the explicit 2


def test_sample_source_duplicate_id_errors() -> None:
    # an injected sample whose id collides with an existing one fails the task
    class _Dup(SampleSource):
        def __init__(self) -> None:
            self._produced = False

        def initial_samples(self) -> list[Sample]:
            return [Sample(id=1, input="seed", target="ok")]

        async def next_samples(self) -> list[Sample] | None:
            if not self._produced:
                self._produced = True
                return [Sample(id=1, input="dup", target="ok")]
            return None

    logs = eval(
        Task(dataset=_Dup(), solver=[generate()]),
        model="mockllm/model",
        display="none",
    )
    assert logs[0].status == "error"
    assert "duplicate" in (logs[0].error.message if logs[0].error else "")


def test_live_injection_runs_concurrently_with_in_flight_sample() -> None:
    # Discriminates live injection from batch-at-a-time: a sample injected
    # mid-run must start while another sample is still in flight. "blocker"
    # parks until "injected" releases it, and "injected" is only enqueued (by
    # "injector") once the task is already underway — so only live injection
    # lets this finish (the fail_after turns a regression into a fast failure
    # instead of a hang).
    released: anyio.Event | None = None
    order: list[str] = []

    @solver
    def router() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            assert released is not None
            if state.input_text == "blocker":
                order.append("blocker-start")
                with anyio.fail_after(10):
                    await released.wait()
                order.append("blocker-end")
            elif state.input_text == "injector":
                enqueue_sample(Sample(input="injected", target="ok"))
            elif state.input_text == "injected":
                order.append("injected")
                released.set()
            return state

        return solve

    class _Src(SampleSource):
        def initial_samples(self) -> list[Sample]:
            return [
                Sample(input="blocker", target="ok"),
                Sample(input="injector", target="ok"),
            ]

        async def next_samples(self) -> list[Sample] | None:
            return None

    released = anyio.Event()
    logs = eval(
        Task(dataset=_Src(), solver=[router()]),
        model="mockllm/model",
        display="none",
    )
    log = logs[0]
    assert log.status == "success"
    # blocker only reaches its end if the injected sample ran while it blocked
    assert "blocker-end" in order
    assert _sample_inputs(log) == ["blocker", "injected", "injector"]


def test_enqueue_sample_rejected_outside_sample_source_task() -> None:
    # enqueue_sample() requires a running SampleSource-driven task: a plain
    # task has a fixed sample set (no loop to run additions)
    @solver
    def bad() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            enqueue_sample(Sample(input="x"))
            return state

        return solve

    logs = eval(
        Task(dataset=[Sample(input="plain")], solver=[bad()]),
        model="mockllm/model",
        display="none",
    )
    assert logs[0].status == "error"
    assert "SampleSource" in (logs[0].error.message if logs[0].error else "")


def test_enqueue_sample_rejected_outside_task() -> None:
    with pytest.raises(RuntimeError, match="SampleSource"):
        enqueue_sample(Sample(input="x"))


class _TrackedGenerations(_Generations):
    """`_Generations` that counts `next_samples()` calls."""

    def __init__(self, count: int) -> None:
        super().__init__(count)
        self.next_calls = 0

    async def next_samples(self) -> list[Sample] | None:
        self.next_calls += 1
        return await super().next_samples()


def test_sample_source_limit_caps_total_samples() -> None:
    # --limit caps the total samples (seed + produced): limit 3 with a
    # 1-sample seed leaves a budget of 2, so a source that would produce 10
    # runs only s0..s2 (and the task still succeeds)
    source = _TrackedGenerations(10)
    logs = eval(
        Task(dataset=source, solver=[generate()]),
        model="mockllm/model",
        display="none",
        limit=3,
    )
    assert logs[0].status == "success"
    assert _sample_inputs(logs[0]) == ["s0", "s1", "s2"]


def test_sample_source_limit_consumed_by_seed_skips_source() -> None:
    # a limit fully consumed by the seed ends the task without consulting
    # the source at all
    source = _TrackedGenerations(10)
    logs = eval(
        Task(dataset=source, solver=[generate()]),
        model="mockllm/model",
        display="none",
        limit=1,
    )
    assert logs[0].status == "success"
    assert _sample_inputs(logs[0]) == ["s0"]
    assert source.next_calls == 0


def test_sample_source_limit_truncates_batch() -> None:
    # a produced batch larger than the remaining budget is truncated
    class _Batch(SampleSource):
        def __init__(self) -> None:
            self._produced = False

        def initial_samples(self) -> list[Sample]:
            return [Sample(input="s0", target="ok")]

        async def next_samples(self) -> list[Sample] | None:
            if not self._produced:
                self._produced = True
                return [Sample(input=f"b{i}", target="ok") for i in range(3)]
            return None

    logs = eval(
        Task(dataset=_Batch(), solver=[generate()]),
        model="mockllm/model",
        display="none",
        limit=2,
    )
    assert logs[0].status == "success"
    assert _sample_inputs(logs[0]) == ["b0", "s0"]


def test_sample_source_limit_counts_samples_not_epoch_runs() -> None:
    # the limit counts samples: each sample within it still runs all epochs
    logs = eval(
        Task(dataset=_TrackedGenerations(10), solver=[generate()], epochs=2),
        model="mockllm/model",
        display="none",
        limit=2,
    )
    log = logs[0]
    assert log.status == "success"
    runs = sorted((str(sample.input), sample.epoch) for sample in (log.samples or []))
    assert runs == [("s0", 1), ("s0", 2), ("s1", 1), ("s1", 2)]


class _IdsSource(SampleSource):
    """Seed ids 1/2; produces ids 3/4 once."""

    def __init__(self) -> None:
        self._produced = False

    def initial_samples(self) -> list[Sample]:
        return [
            Sample(id=1, input="one", target="ok"),
            Sample(id=2, input="two", target="ok"),
        ]

    async def next_samples(self) -> list[Sample] | None:
        if not self._produced:
            self._produced = True
            return [
                Sample(id=3, input="three", target="ok"),
                Sample(id=4, input="four", target="ok"),
            ]
        return None


def test_sample_source_sample_id_filters_produced_samples() -> None:
    # --sample-id filters samples the source produces, not just the seed
    logs = eval(
        Task(dataset=_IdsSource(), solver=[generate()]),
        model="mockllm/model",
        display="none",
        sample_id=[1, 3],
    )
    log = logs[0]
    assert log.status == "success"
    assert sorted(sample.id for sample in (log.samples or [])) == [1, 3]


def test_sample_source_sample_id_missing_from_seed_ok() -> None:
    # a requested id absent from the seed is not an error — the source may
    # produce it while the task runs
    logs = eval(
        Task(dataset=_IdsSource(), solver=[generate()]),
        model="mockllm/model",
        display="none",
        sample_id=4,
    )
    log = logs[0]
    assert log.status == "success"
    assert [sample.id for sample in (log.samples or [])] == [4]


def test_sample_source_enqueue_during_terminal_next_samples() -> None:
    # samples enqueued while next_samples() is returning None still run
    # (the dispatcher drains once more before finishing)
    class _Late(SampleSource):
        def __init__(self) -> None:
            self.calls = 0

        def initial_samples(self) -> list[Sample]:
            return [Sample(input="seed", target="ok")]

        async def next_samples(self) -> list[Sample] | None:
            self.calls += 1
            if self.calls == 1:
                enqueue_sample(Sample(input="late", target="ok"))
            return None

    logs = eval(
        Task(dataset=_Late(), solver=[generate()]),
        model="mockllm/model",
        display="none",
    )
    assert logs[0].status == "success"
    assert _sample_inputs(logs[0]) == ["late", "seed"]
