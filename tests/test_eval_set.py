import shutil
import tempfile
from copy import deepcopy
from pathlib import Path

import pytest
from test_helpers.utils import (
    failing_solver,
    failing_task,
    failing_task_deterministic,
    identity_solver,
    keyboard_interrupt,
    skip_if_trio,
    sleep_for_solver,
)

from inspect_ai import Task, task
from inspect_ai._eval.evalset import (
    eval_set,
    latest_completed_task_eval_logs,
    list_all_eval_logs,
    task_identifier,
    validate_eval_set_prerequisites,
)
from inspect_ai._eval.loader import resolve_tasks
from inspect_ai._eval.task.resolved import ResolvedTask
from inspect_ai._eval.task.task import task_with
from inspect_ai._util.error import PrerequisiteError
from inspect_ai.dataset import Sample
from inspect_ai.log._edit import ProvenanceData, invalidate_samples
from inspect_ai.log._file import list_eval_logs, read_eval_log, write_eval_log
from inspect_ai.model import get_model
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.scorer import exact
from inspect_ai.scorer._match import includes
from inspect_ai.solver import Solver, generate


def test_eval_set() -> None:
    # run eval with a solver that fails 10% of the time
    with tempfile.TemporaryDirectory() as log_dir:
        success, logs = eval_set(
            tasks=failing_task(rate=0.1, samples=10),
            log_dir=log_dir,
            retry_attempts=1000,
            retry_wait=0.1,
            model="mockllm/model",
        )
        assert success
        assert logs[0].status == "success"

        # read and write logs based on location
        for log in logs:
            log = read_eval_log(log.location)
            log.eval.metadata = {"foo": "bar"}
            write_eval_log(log)
            log = read_eval_log(log.location)
            assert log.eval.metadata
            log.eval.metadata["foo"] = "bar"

    # run eval that is guaranteed to fail
    with tempfile.TemporaryDirectory() as log_dir:
        success, logs = eval_set(
            tasks=failing_task(rate=1, samples=10),
            log_dir=log_dir,
            retry_attempts=1,
            retry_wait=0.1,
            model="mockllm/model",
        )
        assert not success
        assert logs[0].status == "error"


@pytest.mark.slow
@pytest.mark.parametrize("eval_set_id", [None, "test-eval-set-id"])
def test_eval_set_dynamic(eval_set_id: str | None) -> None:
    with tempfile.TemporaryDirectory() as log_dir:
        dataset: list[Sample] = []
        for _ in range(0, 10):
            dataset.append(Sample(input="Say hello", target="hello"))
        task1 = Task(
            name="task1",
            dataset=deepcopy(dataset),
            solver=[failing_solver(0.05), generate()],
            scorer=includes(),
        )
        task2 = Task(
            name="task2",
            dataset=deepcopy(dataset),
            solver=[failing_solver(0.05), generate()],
            scorer=includes(),
        )
        success, logs = eval_set(
            tasks=[task1, task2],
            log_dir=log_dir,
            model=[get_model("mockllm/model"), get_model("mockllm/model2")],
            retry_attempts=10000,
            retry_wait=0.001,
            eval_set_id=eval_set_id,
        )
        assert len(logs) == 4
        assert success
        eval_set_ids = [log.eval.eval_set_id for log in logs]
        assert eval_set_ids[0] is not None
        assert len(set(eval_set_ids)) == 1
        if eval_set_id:
            assert eval_set_ids[0] == eval_set_id
        else:
            assert eval_set_ids[0] is not None


def test_eval_set_identifiers() -> None:
    dataset: list[Sample] = []
    for _ in range(0, 10):
        dataset.append(Sample(input="Say hello", target="hello"))

    @task
    def make_task(param="param"):
        return Task(
            dataset=deepcopy(dataset),
            solver=[failing_solver(0.2), generate()],
            scorer=includes(),
        )

    def eval_tasks(tasks: list[Task]):
        with tempfile.TemporaryDirectory() as log_dir:
            success, logs = eval_set(
                tasks=tasks,
                log_dir=log_dir,
                model=[get_model("mockllm/model")],
                retry_attempts=100,
                retry_wait=0.1,
            )
            assert success

    # test that task parameters create unique identfiers
    try:
        eval_tasks([make_task("a"), make_task("b")])
    except Exception:
        assert False

    # test that using identical params results in an error
    try:
        eval_tasks([make_task("a"), make_task("a")])
        assert False
    except Exception:
        pass


def test_latest_completed_task_eval_logs() -> None:
    # cleanup previous tests
    TEST_EVAL_SET_PATH = Path("tests/test_eval_set")
    clean_dir = TEST_EVAL_SET_PATH / "clean"
    if clean_dir.exists():
        shutil.rmtree(clean_dir.as_posix())

    # verify we correctly select only the most recent log
    all_logs = list_all_eval_logs(TEST_EVAL_SET_PATH.as_posix())
    assert len(all_logs) == 2
    latest = latest_completed_task_eval_logs(all_logs, False)
    assert len(latest) == 1

    # verify that we correctly clean when requested
    clean_dir.mkdir(exist_ok=True)
    try:
        for filename in TEST_EVAL_SET_PATH.glob("*.json"):
            destination = clean_dir / filename.name
            shutil.copy2(filename, destination)
        all_logs = list_all_eval_logs(clean_dir.as_posix())
        latest = latest_completed_task_eval_logs(all_logs, True)
        assert len(list_eval_logs(clean_dir.as_posix())) == 1
    finally:
        shutil.rmtree(clean_dir, ignore_errors=True)


def test_validate_eval_set_prerequisites_ok() -> None:
    # cleanup previous tests
    TEST_EVAL_SET_PATH = Path("tests/test_eval_set")

    # verify we correctly select only the most recent log
    all_logs = list_all_eval_logs(TEST_EVAL_SET_PATH.as_posix())
    resolved_tasks = resolve_tasks(
        "examples/popularity.py", {}, get_model("mockllm/model"), None, None, None
    )
    task_with(resolved_tasks[0].task, config=GenerateConfig(temperature=1.0))

    all_logs = validate_eval_set_prerequisites(
        resolved_tasks=resolved_tasks,
        all_logs=all_logs,
        log_dir_allow_dirty=False,
        config=GenerateConfig(),
        eval_set_solver=None,
    )
    assert len(all_logs) == 2


def test_validate_eval_set_prerequisites_mismatch() -> None:
    # cleanup previous tests
    TEST_EVAL_SET_PATH = Path("tests/test_eval_set")

    # verify we correctly select only the most recent log
    all_logs = list_all_eval_logs(TEST_EVAL_SET_PATH.as_posix())
    resolved_tasks = resolve_tasks(
        "examples/hello_world.py", {}, get_model("mockllm/model"), None, None, None
    )

    with pytest.raises(PrerequisiteError):
        validate_eval_set_prerequisites(
            resolved_tasks=resolved_tasks,
            all_logs=all_logs,
            log_dir_allow_dirty=False,
            config=GenerateConfig(),
            eval_set_solver=None,
        )


def test_validate_eval_set_prerequisites_mismatch_log_dir_allow_dirty() -> None:
    # cleanup previous tests
    TEST_EVAL_SET_PATH = Path("tests/test_eval_set")

    # verify we correctly select only the most recent log
    all_logs = list_all_eval_logs(TEST_EVAL_SET_PATH.as_posix())
    resolved_tasks = resolve_tasks(
        "examples/hello_world.py", {}, get_model("mockllm/model"), None, None, None
    )

    all_logs = validate_eval_set_prerequisites(
        resolved_tasks=resolved_tasks,
        all_logs=all_logs,
        log_dir_allow_dirty=True,
        config=GenerateConfig(),
        eval_set_solver=None,
    )
    assert len(all_logs) == 0


@pytest.mark.slow
@skip_if_trio
def test_eval_set_s3(mock_s3) -> None:
    success, logs = eval_set(
        tasks=failing_task(rate=0, samples=1),
        log_dir="s3://test-bucket",
        retry_attempts=1,
        retry_wait=0.1,
        model="mockllm/model",
    )
    assert success
    assert logs[0].status == "success"


def test_eval_zero_retries() -> None:
    with tempfile.TemporaryDirectory() as log_dir:
        success, logs = eval_set(
            tasks=failing_task_deterministic([True, False]),
            log_dir=log_dir,
            retry_attempts=0,
            retry_wait=0.1,
            model="mockllm/model",
        )
        assert not success


@skip_if_trio  # throwing the keyboardinterrupt corrupts trio's internals
def test_eval_set_previous_task_args():
    with tempfile.TemporaryDirectory() as log_dir:

        def run_eval_set():
            eval_set(
                tasks=[sleep_for_3_task("foo"), sleep_for_1_task("bar")],
                log_dir=log_dir,
                max_tasks=2,
                model="mockllm/model",
            )

        # initial pass
        try:
            with keyboard_interrupt(2):
                run_eval_set()
        except KeyboardInterrupt:
            pass

        # second pass (no keyboard interrupt so runs to completion)
        run_eval_set()

        # re-run the eval-set again (it should complete without errors b/c
        # the logs in the directory are successfully matched against the
        # task args of the tasks passed to eval_set)
        run_eval_set()


def test_eval_set_retry_started():
    with tempfile.TemporaryDirectory() as log_dir:

        def run_eval_set():
            eval_set(
                tasks=[sleep_for_1_task("bar")],
                log_dir=log_dir,
                model="mockllm/model",
            )

        def eval_log_status():
            log_file = list_eval_logs(log_dir)[0].name
            log = read_eval_log(log_file)
            return log.status

        # run a first pass
        run_eval_set()

        # modify the log to be 'started' and save it
        log_file = list_eval_logs(log_dir)[0].name
        log = read_eval_log(log_file)
        log.status = "started"
        write_eval_log(log)
        assert eval_log_status() == "started"

        # re-run the eval set and confirm status 'succes'
        run_eval_set()
        assert eval_log_status() == "success"


def test_eval_set_header_only() -> None:
    dataset: list[Sample] = []
    for _ in range(0, 10):
        dataset.append(Sample(input="Say hello", target="hello"))
    task1 = Task(
        name="task1",
        dataset=dataset,
        solver=[generate()],
        scorer=includes(),
    )

    with tempfile.TemporaryDirectory() as log_dir:
        success, logs = eval_set(task1, model="mockllm/model", log_dir=log_dir)
        assert logs[0].samples is None


@task
def sleep_for_1_task(task_arg: str):
    return Task(
        solver=[sleep_for_solver(1)],
    )


@task
def sleep_for_3_task(task_arg: str):
    return Task(
        solver=[sleep_for_solver(3)],
    )


def run_eval_set(
    resolved_tasks: list[ResolvedTask],
    solver: Solver | None = None,
    config: GenerateConfig = GenerateConfig(temperature=0.7),
) -> None:
    tasks = [task.task for task in resolved_tasks]
    with tempfile.TemporaryDirectory() as log_dir:
        eval_set(
            tasks=tasks,
            log_dir=log_dir,
            solver=solver,
            **config.model_dump(),
        )

        all_logs = list_all_eval_logs(log_dir)

        all_logs = validate_eval_set_prerequisites(
            resolved_tasks=resolved_tasks,
            all_logs=all_logs,
            log_dir_allow_dirty=False,
            config=config,
            eval_set_solver=solver,
        )
        assert len(all_logs) == len(resolved_tasks)

        eval_set(
            tasks=tasks,
            log_dir=log_dir,
            solver=solver,
            **config.model_dump(),
        )


@task
def hello_world(arg: str = "arg"):
    return Task(
        dataset=[
            Sample(
                input="Just reply with Hello World",
                target="Hello World",
            )
        ],
        solver=[
            generate(),
        ],
        scorer=exact(),
    )


def test_task_identifier_with_model_configs():
    model1 = get_model("mockllm/model", config=GenerateConfig(temperature=0.7))
    model2 = get_model("mockllm/model", config=GenerateConfig(temperature=0))
    task1 = hello_world()
    task2 = hello_world()
    task_with(
        task1,
        model=model1,
    )
    task_with(
        task2,
        model=model2,
    )
    resolved_tasks = resolve_tasks([task1, task2], {}, model1, None, None, None)

    assert task_identifier(
        resolved_tasks[0], GenerateConfig(), eval_set_solver=None
    ) != task_identifier(resolved_tasks[1], GenerateConfig(), eval_set_solver=None)
    run_eval_set(resolved_tasks)


def test_task_identifier_with_model_roles_model_configs():
    # ensure that model roles with different configs produce different task identifiers
    model1 = get_model("mockllm/model")
    model2 = get_model("mockllm/model", config=GenerateConfig(temperature=0))
    task1 = hello_world()
    task2 = hello_world()
    task_with(
        task1,
        model=model1,
        model_roles={"scorer": model1},
    )
    task_with(
        task2,
        model=model1,
        model_roles={"scorer": model2},
    )
    resolved_tasks = resolve_tasks([task1, task2], {}, model1, None, None, None)

    assert task_identifier(
        resolved_tasks[0], GenerateConfig(), eval_set_solver=None
    ) != task_identifier(resolved_tasks[1], GenerateConfig(), eval_set_solver=None)
    run_eval_set(resolved_tasks)


def test_task_identifier_with_task_generate_configs():
    model1 = get_model("mockllm/model")
    task1 = hello_world()
    task2 = hello_world()
    task_with(
        task1,
        model=model1,
        config=GenerateConfig(temperature=0.0),
        model_roles={"scorer": model1},
    )
    task_with(
        task2,
        model=model1,
        config=GenerateConfig(temperature=0.5),
        model_roles={"scorer": model1},
    )
    resolved_tasks = resolve_tasks([task1, task2], {}, model1, None, None, None)
    assert task_identifier(
        resolved_tasks[0], GenerateConfig(), eval_set_solver=None
    ) != task_identifier(resolved_tasks[1], GenerateConfig(), eval_set_solver=None)

    with tempfile.TemporaryDirectory() as log_dir:
        config = GenerateConfig(temperature=0.7)
        # Since eval_set config overrides the task config, both tasks will be the same and this should raise an error
        with pytest.raises(PrerequisiteError):
            eval_set(
                tasks=[task1, task2],
                log_dir=log_dir,
                model="mockllm/model",
                **config.model_dump(),
            )

    # system_message will not override the value set in the task config, so these tasks will still be unique
    run_eval_set(
        resolved_tasks, config=GenerateConfig(system_message="Test System Message")
    )


def test_task_identifier_with_solvers():
    # test that tasks with different solvers produce different task identifiers
    model1 = get_model("mockllm/model")
    task1 = hello_world()
    task2 = hello_world()
    task_with(
        task1,
        model=model1,
    )
    task_with(
        task2,
        model=model1,
        solver=[identity_solver(2)],
    )
    resolved_tasks = resolve_tasks([task1, task2], {}, model1, None, None, None)
    assert task_identifier(
        resolved_tasks[0], GenerateConfig(), eval_set_solver=None
    ) != task_identifier(resolved_tasks[1], GenerateConfig(), eval_set_solver=None)
    run_eval_set(resolved_tasks)


def test_task_identifier_with_solver_arg():
    # test that tasks with different solvers produce different task identifiers
    model1 = get_model("mockllm/model")
    task1 = hello_world()
    task_with(
        task1,
        model=model1,
    )
    id5 = identity_solver(5)
    resolved_tasks = resolve_tasks([task1], {}, model1, None, None, None)
    run_eval_set(resolved_tasks, solver=id5)


def test_task_identifier_with_model_args():
    model1 = get_model("mockllm/model", max_tokens=100)
    model2 = get_model("mockllm/model", max_tokens=200)
    task1 = hello_world()
    task2 = hello_world()
    task_with(
        task1,
        model=model1,
    )
    task_with(
        task2,
        model=model2,
    )
    resolved_tasks = resolve_tasks([task1, task2], {}, model1, None, None, None)

    assert task_identifier(
        resolved_tasks[0], GenerateConfig(), eval_set_solver=None
    ) != task_identifier(resolved_tasks[1], GenerateConfig(), eval_set_solver=None)
    run_eval_set(resolved_tasks)


def test_task_identifier_with_model_args_arg():
    model1 = get_model("mockllm/model", max_tokens=100)
    task1 = hello_world()
    task2 = hello_world()
    task_with(
        task1,
        model=model1,
    )

    with tempfile.TemporaryDirectory() as log_dir:
        eval_set(
            tasks=[task1, task2],
            log_dir=log_dir,
            model="mockllm/model",
            model_args={"max_tokens": 200},
        )

        all_logs = list_all_eval_logs(log_dir)
        assert len(all_logs) == 2

        eval_set(
            tasks=[task1, task2],
            log_dir=log_dir,
            model="mockllm/model",
            model_args={"max_tokens": 200},
        )

        all_logs = list_all_eval_logs(log_dir)
        assert len(all_logs) == 2


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

    task1 = task_for_invalidation()
    task2 = task_with(task_for_invalidation(), model=get_model("mockllm/model2"))

    def run_eval_set():
        return eval_set(
            tasks=[task1, task2],
            log_dir=str(tmp_path),
            retry_attempts=0,
            retry_cleanup=False,
            model="mockllm/model",
        )

    success, (eval1, eval2) = run_eval_set()
    assert success
    assert eval1.status == "success"
    assert eval2.status == "success"
    assert len(list(tmp_path.glob("*.eval"))) == 2

    eval1 = read_eval_log(eval1.location)
    samples = eval1.samples
    assert samples is not None
    sample = samples[0]
    assert sample.uuid is not None
    invalidated_sample = sample.uuid
    eval1 = invalidate_samples(
        eval1,
        sample_uuids=[invalidated_sample],
        provenance=ProvenanceData(author="test_person", reason="test_reason"),
    )
    write_eval_log(eval1, location=eval1.location)

    success2, evals_retried = run_eval_set()
    assert success2
    eval1_retried = next(
        eval for eval in evals_retried if eval.eval.task_id == eval1.eval.task_id
    )
    assert eval1_retried.status == "success"
    assert eval1_retried.eval.eval_id != eval1.eval.eval_id
    eval1_retried = read_eval_log(eval1_retried.location)

    new_sample_uuids = {sample.uuid for sample in eval1_retried.samples or []}
    old_sample_uuids = {sample.uuid for sample in eval1.samples or []}
    assert len(new_sample_uuids) == len(old_sample_uuids)
    assert new_sample_uuids != old_sample_uuids
    reused_sample_uuids = old_sample_uuids.intersection(new_sample_uuids)
    assert reused_sample_uuids == old_sample_uuids - {invalidated_sample}
