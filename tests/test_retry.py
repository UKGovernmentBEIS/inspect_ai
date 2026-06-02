import os
import tempfile
from pathlib import Path

import pytest
from test_helpers.utils import (
    failing_task,
    failing_task_deterministic,
    skip_if_no_docker,
)

from inspect_ai import Task, eval, eval_retry, task
from inspect_ai.dataset import Sample
from inspect_ai.log import (
    ProvenanceData,
    invalidate_samples,
    list_eval_logs,
    read_eval_log,
    retryable_eval_logs,
    write_eval_log,
)
from inspect_ai.model import GenerateConfig, get_model
from inspect_ai.scorer import exact
from inspect_ai.solver import TaskState, generate, solver


def test_eval_retry():
    # run eval with a solver that fails 2/3 times
    log = eval(failing_task, limit=1, model="mockllm/model")[0]

    # note the task id so we can be certain it remains the same
    task_id = log.eval.task_id

    # retry until we succeed (confirming the task_id is stable)
    while log.status != "success":
        log = eval_retry(log)[0]
        assert log.eval.task_id == task_id


def test_eval_retryable():
    with tempfile.TemporaryDirectory() as log_dir:
        # run eval with a solver that fails 2/3 of the time
        log = eval(tasks=failing_task, limit=1, model="mockllm/model", log_dir=log_dir)[
            0
        ]

        # note the task id so we can be certain it remains the same
        task_id = log.eval.task_id

        # retry until we succeed (confirming the task_id is stable)
        retryable = retryable_eval_logs(list_eval_logs(log_dir))
        while len(retryable) > 0:
            assert len(retryable) == 1
            assert retryable[0].task_id == task_id
            eval_retry(retryable, log_dir=log_dir)
            retryable = retryable_eval_logs(list_eval_logs(log_dir))


@task
def mytask():
    return Task(name="custom-task-name", solver=[])


def test_eval_retry_with_task_name():
    log = eval(mytask())[0]
    log = eval_retry(log)[0]


@task
def hello_world():
    return Task(
        dataset=[
            Sample(
                input="Just reply with Hello World",
                target="Hello World",
            )
        ],
        solver=[generate()],
        scorer=exact(),
    )


def test_eval_retry_with_model_generate_config():
    generate_config = GenerateConfig(
        seed=42,
        temperature=0.7,
        top_p=0.95,
        max_connections=1,
    )
    model = get_model(
        model="mockllm/model",
        config=generate_config,
    )

    log = eval(
        model=model,
        tasks=hello_world(),
    )[0]

    assert log.status == "success"
    assert log.eval.model_generate_config == generate_config

    log = eval_retry(log)[0]
    assert log.status == "success"
    assert log.eval.model_generate_config == generate_config


@solver
def failing_solver():
    async def solve(state: TaskState, generate) -> TaskState:
        raise ValueError("Eval failed!")

    return solve


@skip_if_no_docker
@pytest.mark.slow
def test_eval_retry_resolves_relative_sandbox_paths():
    """Test that eval-retry correctly resolves relative sandbox config paths.

    This test verifies that when a task uses a relative path for its sandbox
    config (e.g., "compose.yaml"), eval-retry resolves it relative to the
    task file's directory, not the current working directory.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        task_dir = Path(tmpdir) / "my_task"
        task_dir.mkdir()

        compose_file = task_dir / "compose.yaml"
        compose_file.write_text(
            """services:
  default:
    image: "python:3.12-slim"
    command: "tail -f /dev/null"
    init: true
    network_mode: none
"""
        )

        task_file = task_dir / "task.py"
        task_file.write_text(
            """from inspect_ai import Task, task
from inspect_ai.dataset import Sample

@task
def my_task():
    return Task(
        dataset=[Sample(input="test")],
        sandbox=("docker", "compose.yaml"),
    )
"""
        )

        # Change to tmpdir (different from task_dir) to ensure CWD != task dir
        eval_wd = os.getcwd()
        try:
            os.chdir(tmpdir)

            # Run eval with a failing solver (limit to 1 sample)
            log = eval(
                f"{task_file}@my_task",
                solver=failing_solver(),
                model="mockllm/model",
                limit=1,
            )[0]

            assert log.status == "error"

            # Verify sandbox config was stored as relative path in log
            assert log.eval.sandbox is not None
            assert log.eval.sandbox.config == "compose.yaml"

            # Now retry from tmpdir (not task_dir)
            # This should work because eval-retry resolves relative to task file
            # eval_retry uses model and solver from the log
            log = eval_retry(log)[0]

            # If we get here without Docker errors, the path was resolved correctly
            # (The eval will still fail due to our failing_solver, but that's expected)
            assert log.status == "error"
            if log.error:
                assert "Error reading docker config" not in log.error.message

        finally:
            os.chdir(eval_wd)


def test_invalidation(tmp_path: Path):
    @task
    def task_for_invalidation():
        return Task(
            dataset=[
                Sample(input=f"Just reply with {idx_sample}", target="Hello World")
                for idx_sample in range(10)
            ],
            solver=[generate()],
            scorer=exact(),
        )

    model = get_model(model="mockllm/model")
    (log,) = eval(tasks=[task_for_invalidation()], model=model, log_dir=str(tmp_path))

    assert log.status == "success"
    log = read_eval_log(log.location)
    assert log.samples is not None
    invalid_sample_uuid = str(log.samples[0].uuid)
    log = invalidate_samples(
        log,
        sample_uuids=[invalid_sample_uuid],
        provenance=ProvenanceData(author="test_person", reason="test_reason"),
    )
    write_eval_log(log, location=log.location)

    (log_retried,) = eval_retry(log.location)
    assert log_retried.status == "success"
    assert log_retried.eval.eval_id != log.eval.eval_id
    assert log_retried.samples is not None
    assert len(log_retried.samples) == 10
    new_uuids = {sample.uuid for sample in log_retried.samples}
    old_uuids = {sample.uuid for sample in log.samples or []}
    assert len(new_uuids) == len(old_uuids)
    assert new_uuids != old_uuids
    reused_uuids = old_uuids.intersection(new_uuids)
    assert reused_uuids == old_uuids - {invalid_sample_uuid}


def test_eval_retry_preserves_scorer_attribution(monkeypatch) -> None:
    # Restored (cached) samples must carry the same SampleScore.scorer
    # attribution as freshly executed samples. Regression: the cached path
    # previously omitted `scorer=` so restored scores had scorer=None and
    # were indistinguishable from solver-set scores in results aggregation.
    import inspect_ai._eval.task.run as run_mod

    captured: list[list[dict]] = []
    orig = getattr(run_mod, "eval_results")

    def spy(*args, **kwargs):
        scores = kwargs.get("scores", args[1] if len(args) > 1 else None)
        captured.append(list(scores))
        return orig(*args, **kwargs)

    monkeypatch.setattr(run_mod, "eval_results", spy)

    # 2 samples: first passes, second fails -> retry restores first from
    # cache and reruns second fresh
    log1 = eval(
        failing_task_deterministic([False, True]),
        model="mockllm/model",
        fail_on_error=False,
    )[0]
    assert log1.status == "success"
    captured.clear()

    log2 = eval_retry(log1)[0]
    assert log2.status == "success"

    by_id: dict[int, str | None] = {}
    for call_scores in captured:
        for d in call_scores:
            for ss in d.values():
                by_id[ss.sample_id] = ss.scorer

    assert 1 in by_id and 2 in by_id
    assert by_id[2] == "match", f"fresh sample scorer={by_id[2]!r}"
    assert by_id[1] == "match", f"restored sample scorer={by_id[1]!r}"


def test_eval_retry_preserves_stats():
    # 10 samples: first 8 pass, last 2 fail
    # On retry: fresh iterator, 2 samples read [False, False] -> both pass
    log1 = eval(
        failing_task_deterministic([False] * 8 + [True] * 2),
        model="mockllm/model",
    )[0]

    assert log1.status == "error"
    assert log1.stats.model_usage
    model_name = list(log1.stats.model_usage.keys())[0]
    tokens1 = log1.stats.model_usage[model_name].total_tokens
    assert tokens1 > 0

    # Retry - fresh iterator reads [False, False] for the 2 failed samples
    log2 = eval_retry(log1)[0]

    assert log2.status == "success"
    tokens2 = log2.stats.model_usage[model_name].total_tokens
    assert tokens2 > tokens1
    assert log2.stats.started_at == log1.stats.started_at


def test_eval_retry_token_usage_multi_retry():
    # 4 samples with pattern: [False, True, False, True]
    # First run: samples 0,2 pass; samples 1,3 fail
    # Retry 1: 2 samples read [False, True] -> sample 1 passes, sample 3 fails
    # Retry 2: 1 sample reads [False] -> sample 3 passes
    log1 = eval(
        failing_task_deterministic([False, True, False, True]),
        model="mockllm/model",
    )[0]

    def get_tokens(log):
        model_name = list(log.stats.model_usage.keys())[0]
        return log.stats.model_usage[model_name].total_tokens

    assert log1.status == "error"
    tokens1 = get_tokens(log1)
    assert tokens1 > 0

    # First retry
    log2 = eval_retry(log1)[0]
    assert log2.status == "error"
    tokens2 = get_tokens(log2)
    assert tokens2 > tokens1
    assert log2.stats.started_at == log1.stats.started_at

    # Second retry
    log3 = eval_retry(log2)[0]
    assert log3.status == "success"
    tokens3 = get_tokens(log3)
    assert tokens3 > tokens2
    assert log3.stats.started_at == log2.stats.started_at
