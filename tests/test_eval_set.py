import shutil
import tempfile
from copy import deepcopy
from pathlib import Path

import pytest
from test_helpers.utils import (
    failing_solver,
    failing_task,
    failing_task_deterministic,
    keyboard_interrupt,
    skip_if_trio,
    sleep_for_solver,
)

from inspect_ai import Task, task
from inspect_ai._eval.evalset import (
    eval_set,
    latest_completed_task_eval_logs,
    list_all_eval_logs,
)
from inspect_ai.dataset import Sample
from inspect_ai.log._file import list_eval_logs, read_eval_log, write_eval_log
from inspect_ai.model import get_model
from inspect_ai.scorer._match import includes
from inspect_ai.solver import generate


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
def test_eval_set_dynamic() -> None:
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
        )
        assert len(logs) == 4
        assert success


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
