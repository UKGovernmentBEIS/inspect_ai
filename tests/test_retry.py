import tempfile

import pytest
from test_helpers.utils import failing_task

from inspect_ai import Task, eval, eval_retry, task
from inspect_ai._util.error import PrerequisiteError
from inspect_ai.dataset import Sample
from inspect_ai.log import list_eval_logs, retryable_eval_logs
from inspect_ai.model import GenerateConfig, get_model
from inspect_ai.scorer import exact
from inspect_ai.solver import generate


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


# Tests for eval_retry with sample_id argument


def test_eval_retry_sample_id_single_integer():
    """Test retry with single integer sample_id reruns that specific sample."""
    from test_helpers.utils import failing_solver_deterministic

    @task
    def sample_id_test_task():
        return Task(
            dataset=[
                Sample(id=i, input=f"Input {i}", target=f"target {i}") for i in range(5)
            ],
            solver=[
                failing_solver_deterministic([False, False, True, False, False]),
                generate(),
            ],
            scorer=exact(),
        )

    # Initial eval
    log = eval(sample_id_test_task(), model="mockllm/model")[0]
    assert log.samples is not None
    assert len(log.samples) == 5
    failed_samples = [s for s in log.samples if s.error is not None]
    assert len(failed_samples) == 1
    assert failed_samples[0].id == 2

    # Retry with sample_id=1 (a successful sample)
    retry_log = eval_retry(log, sample_id=1)[0]

    # Verify only sample 1 was rerun
    assert retry_log.samples is not None
    assert len(retry_log.samples) == 1
    assert retry_log.samples[0].id == 1
    assert retry_log.samples[0].error is None


def test_eval_retry_sample_id_multiple_integers():
    """Test retry with multiple integer sample_ids."""
    from test_helpers.utils import failing_solver_deterministic

    @task
    def multiple_samples_task():
        should_fail = [i in [3, 7] for i in range(10)]
        return Task(
            dataset=[
                Sample(id=i, input=f"Input {i}", target=f"target {i}") for i in range(10)
            ],
            solver=[failing_solver_deterministic(should_fail), generate()],
            scorer=exact(),
        )

    # Initial eval
    log = eval(multiple_samples_task(), model="mockllm/model")[0]
    assert log.samples is not None
    assert len(log.samples) == 10

    # Retry with sample_id=[1, 3, 5] (mix of successful and failed)
    retry_log = eval_retry(log, sample_id=[1, 3, 5])[0]

    # Verify exactly 3 samples were rerun
    assert retry_log.samples is not None
    assert len(retry_log.samples) == 3
    sample_ids = {s.id for s in retry_log.samples}
    assert sample_ids == {1, 3, 5}


def test_eval_retry_sample_id_string_ids():
    """Test retry with single string sample_id."""
    from test_helpers.utils import failing_solver_deterministic

    @task
    def string_ids_task():
        sample_ids = ["sample-a", "sample-b", "sample-c"]
        return Task(
            dataset=[
                Sample(id=sid, input=f"Input {sid}", target=f"target {sid}")
                for sid in sample_ids
            ],
            solver=[failing_solver_deterministic([False, True, False]), generate()],
            scorer=exact(),
        )

    # Initial eval where "sample-b" fails
    log = eval(string_ids_task(), model="mockllm/model")[0]
    assert log.samples is not None
    assert len(log.samples) == 3
    failed_samples = [s for s in log.samples if s.error is not None]
    assert len(failed_samples) == 1
    assert failed_samples[0].id == "sample-b"

    # Retry with sample_id="sample-a" (a successful sample)
    retry_log = eval_retry(log, sample_id="sample-a")[0]

    # Verify only "sample-a" was rerun
    assert retry_log.samples is not None
    assert len(retry_log.samples) == 1
    assert retry_log.samples[0].id == "sample-a"


def test_eval_retry_sample_id_string_list():
    """Test retry with list of string sample_ids."""

    @task
    def string_list_task():
        sample_ids = ["sample-a", "sample-b", "sample-c", "sample-d"]
        return Task(
            dataset=[
                Sample(id=sid, input=f"Input {sid}", target=f"target {sid}")
                for sid in sample_ids
            ],
            solver=[generate()],
            scorer=exact(),
        )

    # Initial eval
    log = eval(string_list_task(), model="mockllm/model")[0]
    assert log.samples is not None
    assert len(log.samples) == 4

    # Retry with sample_id=["sample-a", "sample-c"]
    retry_log = eval_retry(log, sample_id=["sample-a", "sample-c"])[0]

    # Verify both samples were rerun
    assert retry_log.samples is not None
    assert len(retry_log.samples) == 2
    sample_ids_result = {s.id for s in retry_log.samples}
    assert sample_ids_result == {"sample-a", "sample-c"}


def test_eval_retry_sample_id_pattern_brackets():
    """Test retry with bracket pattern matching."""
    from test_helpers.utils import failing_solver_deterministic

    @task
    def pattern_brackets_task():
        sample_ids = [f"sample-{i}" for i in range(10)]
        should_fail = [i in [3, 7] for i in range(10)]
        return Task(
            dataset=[
                Sample(id=sid, input=f"Input {sid}", target=f"target {sid}")
                for sid in sample_ids
            ],
            solver=[failing_solver_deterministic(should_fail), generate()],
            scorer=exact(),
        )

    # Initial eval where samples 3 and 7 fail
    log = eval(pattern_brackets_task(), model="mockllm/model")[0]
    assert log.samples is not None
    assert len(log.samples) == 10

    # Retry with sample_id=["sample-[56]"] (should match sample-5 and sample-6)
    retry_log = eval_retry(log, sample_id=["sample-[56]"])[0]

    # Verify samples 5 and 6 were rerun (even though they didn't fail)
    assert retry_log.samples is not None
    assert len(retry_log.samples) == 2
    sample_ids_result = {s.id for s in retry_log.samples}
    assert sample_ids_result == {"sample-5", "sample-6"}


def test_eval_retry_sample_id_wildcard():
    """Test retry with wildcard pattern matching."""
    from test_helpers.utils import failing_solver_deterministic

    @task
    def wildcard_task():
        sample_ids = ["a-1", "a-2", "b-1", "b-2"]
        should_fail = [False, True, False, False]
        return Task(
            dataset=[
                Sample(id=sid, input=f"Input {sid}", target=f"target {sid}")
                for sid in sample_ids
            ],
            solver=[failing_solver_deterministic(should_fail), generate()],
            scorer=exact(),
        )

    # Initial eval where "a-2" fails
    log = eval(wildcard_task(), model="mockllm/model")[0]
    assert log.samples is not None
    assert len(log.samples) == 4

    # Retry with sample_id=["a-*"] (should match a-1 and a-2)
    retry_log = eval_retry(log, sample_id=["a-*"])[0]

    # Verify both a-1 and a-2 were rerun
    assert retry_log.samples is not None
    assert len(retry_log.samples) == 2
    sample_ids_result = {s.id for s in retry_log.samples}
    assert sample_ids_result == {"a-1", "a-2"}


def test_eval_retry_reruns_completed_samples_with_sample_id():
    """Test that completed samples ARE rerun when sample_id is provided."""

    @task
    def completed_samples_task():
        return Task(
            dataset=[
                Sample(id=i, input=f"Input {i}", target=f"target {i}") for i in range(3)
            ],
            solver=[generate()],
            scorer=exact(),
        )

    # Initial eval - all succeed
    log = eval(completed_samples_task(), model="mockllm/model")[0]
    assert log.samples is not None
    assert len(log.samples) == 3
    assert all(s.error is None for s in log.samples)

    # Retry with sample_id=1 (a successful sample)
    retry_log = eval_retry(log, sample_id=1)[0]

    # Verify sample 1 was RERUN (not reused)
    assert retry_log.samples is not None
    assert len(retry_log.samples) == 1
    retry_sample_1 = retry_log.samples[0]
    assert retry_sample_1.id == 1

    # The sample should have new events (indicating it was rerun, not reused)
    assert len(retry_sample_1.events) > 0


def test_eval_retry_preserves_completed_without_sample_id():
    """Test that completed samples are NOT rerun when sample_id is NOT provided."""
    from test_helpers.utils import failing_solver_deterministic

    @task
    def preserve_completed_task():
        should_fail = [False, False, True, False, False]
        return Task(
            dataset=[
                Sample(id=i, input=f"Input {i}", target=f"target {i}") for i in range(5)
            ],
            solver=[failing_solver_deterministic(should_fail), generate()],
            scorer=exact(),
        )

    # Initial eval
    log = eval(preserve_completed_task(), model="mockllm/model")[0]
    assert log.samples is not None
    assert len(log.samples) == 5
    failed_samples = [s for s in log.samples if s.error is not None]
    assert len(failed_samples) == 1
    assert failed_samples[0].id == 2

    # Retry WITHOUT sample_id parameter
    retry_log = eval_retry(log)[0]

    # Verify only the failed sample (2) was rerun
    # The successful samples should be reused from the previous log
    assert retry_log.samples is not None
    # In a retry without sample_id, successful samples are preserved
    # so we should only see sample 2 being rerun
    rerun_sample_ids = {s.id for s in retry_log.samples}
    assert 2 in rerun_sample_ids


def test_eval_retry_sample_id_overrides_failures():
    """Test that sample_id overrides default retry behavior (which is to retry failures)."""
    from test_helpers.utils import failing_solver_deterministic

    @task
    def override_failures_task():
        should_fail = [False, True, False, True, False]
        return Task(
            dataset=[
                Sample(id=i, input=f"Input {i}", target=f"target {i}") for i in range(5)
            ],
            solver=[failing_solver_deterministic(should_fail), generate()],
            scorer=exact(),
        )

    # Initial eval where samples 1 and 3 fail
    log = eval(override_failures_task(), model="mockllm/model")[0]
    assert log.samples is not None
    assert len(log.samples) == 5
    failed_samples = [s for s in log.samples if s.error is not None]
    assert len(failed_samples) == 2
    assert {s.id for s in failed_samples} == {1, 3}

    # Retry with sample_id=2 (a successful sample, NOT the failures)
    retry_log = eval_retry(log, sample_id=2)[0]

    # Verify only sample 2 is in retry log
    # Failed samples 1 and 3 are NOT retried
    assert retry_log.samples is not None
    assert len(retry_log.samples) == 1
    assert retry_log.samples[0].id == 2


def test_eval_retry_sample_id_nonexistent():
    """Test that retry with nonexistent sample_id raises an error."""

    @task
    def nonexistent_id_task():
        return Task(
            dataset=[
                Sample(id=i, input=f"Input {i}", target=f"target {i}") for i in range(5)
            ],
            solver=[generate()],
            scorer=exact(),
        )

    # Initial eval
    log = eval(nonexistent_id_task(), model="mockllm/model")[0]
    assert log.samples is not None
    assert len(log.samples) == 5

    # Retry with sample_id=99 (doesn't exist)
    with pytest.raises(PrerequisiteError):
        eval_retry(log, sample_id=99)


def test_eval_retry_sample_id_mixed_success_and_failure():
    """Test retry with mixed successful and failed samples."""
    from test_helpers.utils import failing_solver_deterministic

    @task
    def mixed_samples_task():
        should_fail = [i in [2, 5, 8] for i in range(10)]
        return Task(
            dataset=[
                Sample(id=i, input=f"Input {i}", target=f"target {i}") for i in range(10)
            ],
            solver=[failing_solver_deterministic(should_fail), generate()],
            scorer=exact(),
        )

    # Initial eval
    log = eval(mixed_samples_task(), model="mockllm/model")[0]
    assert log.samples is not None
    assert len(log.samples) == 10
    failed_samples = [s for s in log.samples if s.error is not None]
    assert len(failed_samples) == 3
    assert {s.id for s in failed_samples} == {2, 5, 8}

    # Retry with sample_id=[1, 2, 5, 9] (2 successful, 2 failed)
    retry_log = eval_retry(log, sample_id=[1, 2, 5, 9])[0]

    # Verify all 4 samples were rerun
    assert retry_log.samples is not None
    assert len(retry_log.samples) == 4
    sample_ids_result = {s.id for s in retry_log.samples}
    assert sample_ids_result == {1, 2, 5, 9}
