"""End-to-end tests for the recovery API."""

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from unittest.mock import MagicMock
from zipfile import ZipFile

import anyio
import pytest
from pydantic_core import to_jsonable_python
from test_helpers.buffer import simulate_crashed_buffer_db

from inspect_ai._util.asyncfiles import AsyncFilesystem
from inspect_ai._util.constants import LOG_SCHEMA_VERSION
from inspect_ai.event._model import ModelEvent
from inspect_ai.log._file import read_eval_log, read_eval_log_async
from inspect_ai.log._log import (
    EvalConfig,
    EvalDataset,
    EvalLog,
    EvalPlan,
    EvalSample,
    EvalSampleSummary,
    EvalSpec,
)
from inspect_ai.log._recorders.buffer.database import SampleBufferDatabase
from inspect_ai.log._recorders.eval import HEADER_JSON, LogStart
from inspect_ai.log._recorders.types import SampleEvent
from inspect_ai.log._recover import (
    RecoveryNotAvailable,
    recover_eval_log_async,
    recoverable_eval_logs,
)
from inspect_ai.log._recover._api import _recoverable_eval_logs_async
from inspect_ai.model._chat_message import ChatMessageUser
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.scorer._metric import Score


def _make_eval_spec(task: str = "test_task") -> EvalSpec:
    return EvalSpec(
        created=datetime.now(timezone.utc).isoformat(),
        task=task,
        model="mockllm/model",
        dataset=EvalDataset(name="test", samples=4),
        config=EvalConfig(),
    )


def _make_sample(id: int, epoch: int = 1) -> EvalSample:
    return EvalSample(
        id=id,
        epoch=epoch,
        input=f"input {id}",
        target=f"target {id}",
        output=ModelOutput.from_content(model="mockllm/model", content=f"output {id}"),
        messages=[],
        scores={"accuracy": Score(value="C", answer="C")},
        started_at=datetime.now(timezone.utc).isoformat(),
        completed_at=datetime.now(timezone.utc).isoformat(),
    )


def _to_json(obj: object) -> str:
    return json.dumps(to_jsonable_python(obj, exclude_none=True))


def _make_model_event(content: str) -> ModelEvent:
    return ModelEvent(
        model="mockllm/model",
        input=[ChatMessageUser(content="test input")],
        tools=[],
        tool_choice="auto",
        config=GenerateConfig(),
        output=ModelOutput.from_content(model="mockllm/model", content=content),
    )


def _write_crashed_eval(
    path: str,
    samples: list[EvalSample] | None = None,
    task: str = "test_task",
) -> LogStart:
    """Write a synthetic crashed .eval ZIP file (no header.json)."""
    eval_spec = _make_eval_spec(task)
    plan = EvalPlan()
    log_start = LogStart(version=LOG_SCHEMA_VERSION, eval=eval_spec, plan=plan)

    with ZipFile(path, "w") as zf:
        zf.writestr("_journal/start.json", _to_json(log_start))
        if samples:
            summaries = []
            for sample in samples:
                zf.writestr(
                    f"samples/{sample.id}_epoch_{sample.epoch}.json",
                    _to_json(sample),
                )
                summaries.append(sample.summary())
            zf.writestr("_journal/summaries/1.json", _to_json(summaries))

    return log_start


def _create_buffer_db(
    location: str,
    completed_ids: list[int],
    in_progress_ids: list[int],
    db_dir: str | None = None,
) -> SampleBufferDatabase:
    """Create a buffer DB with a dead PID (simulating crashed process)."""
    db_path = Path(db_dir) if db_dir else None
    buffer = SampleBufferDatabase(location, create=True, db_dir=db_path)

    for id in completed_ids:
        started = EvalSampleSummary(
            id=id,
            epoch=1,
            input=f"input {id}",
            target=f"target {id}",
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        buffer.start_sample(started)
        buffer.log_events(
            [SampleEvent(id=id, epoch=1, event=_make_model_event(f"output {id}"))]
        )
        completed = EvalSampleSummary(
            id=id,
            epoch=1,
            input=f"input {id}",
            target=f"target {id}",
            scores={"accuracy": Score(value="C", answer="C")},
            started_at=datetime.now(timezone.utc).isoformat(),
            completed_at=datetime.now(timezone.utc).isoformat(),
        )
        buffer.complete_sample(completed)

    for id in in_progress_ids:
        started = EvalSampleSummary(
            id=id,
            epoch=1,
            input=f"input {id}",
            target=f"target {id}",
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        buffer.start_sample(started)
        buffer.log_events(
            [SampleEvent(id=id, epoch=1, event=_make_model_event(f"partial {id}"))]
        )

    # simulate a crashed process: snapshot the DB (incl. hot WAL) under a dead PID
    simulate_crashed_buffer_db(buffer)

    return buffer


async def test_recover_eval_log_end_to_end() -> None:
    """Full recovery: crashed .eval + buffer DB with mixed samples."""
    async with AsyncFilesystem():
        with tempfile.TemporaryDirectory() as temp_dir:
            eval_path = os.path.join(temp_dir, "test.eval")
            db_dir = os.path.join(temp_dir, "bufferdb")
            output_path = os.path.join(temp_dir, "test-recovered.eval")

            flushed = [_make_sample(1), _make_sample(2)]
            _write_crashed_eval(eval_path, samples=flushed)
            _create_buffer_db(
                eval_path, completed_ids=[3], in_progress_ids=[4], db_dir=db_dir
            )

            log = await recover_eval_log_async(
                eval_path, output=output_path, cleanup=False, _db_dir=db_dir
            )

            assert log.status == "error"
            assert log.error is not None
            assert log.samples is not None
            assert len(log.samples) == 4

            read_log = read_eval_log(output_path)
            assert read_log.status == "error"
            assert read_log.samples is not None
            assert len(read_log.samples) == 4


async def test_recover_eval_log_no_buffer_db() -> None:
    """Recovery with no buffer DB raises RecoveryNotAvailable."""
    async with AsyncFilesystem():
        with tempfile.TemporaryDirectory() as temp_dir:
            eval_path = os.path.join(temp_dir, "test.eval")
            db_dir = os.path.join(temp_dir, "bufferdb")
            output_path = os.path.join(temp_dir, "test-recovered.eval")

            flushed = [_make_sample(1), _make_sample(2)]
            _write_crashed_eval(eval_path, samples=flushed)

            with pytest.raises(RecoveryNotAvailable):
                await recover_eval_log_async(
                    eval_path, output=output_path, _db_dir=db_dir
                )


async def test_recover_eval_log_cleanup() -> None:
    """Verify buffer DB is cleaned up after recovery and content is preserved."""
    async with AsyncFilesystem():
        with tempfile.TemporaryDirectory() as temp_dir:
            eval_path = os.path.join(temp_dir, "test.eval")
            db_dir = os.path.join(temp_dir, "bufferdb")
            output_path = os.path.join(temp_dir, "test-recovered.eval")

            _write_crashed_eval(eval_path)
            buffer = _create_buffer_db(
                eval_path, completed_ids=[1], in_progress_ids=[], db_dir=db_dir
            )
            db_path = buffer.db_path

            assert db_path.exists()

            log = await recover_eval_log_async(
                eval_path, output=output_path, cleanup=True, _db_dir=db_dir
            )

            assert not db_path.exists()
            assert log.samples is not None
            assert len(log.samples) >= 1


async def test_recover_eval_log_no_cleanup() -> None:
    """Verify buffer DB is preserved when cleanup=False."""
    async with AsyncFilesystem():
        with tempfile.TemporaryDirectory() as temp_dir:
            eval_path = os.path.join(temp_dir, "test.eval")
            db_dir = os.path.join(temp_dir, "bufferdb")
            output_path = os.path.join(temp_dir, "test-recovered.eval")

            _write_crashed_eval(eval_path)
            _create_buffer_db(
                eval_path, completed_ids=[1], in_progress_ids=[], db_dir=db_dir
            )

            await recover_eval_log_async(
                eval_path, output=output_path, cleanup=False, _db_dir=db_dir
            )

            # Buffer DB dir should still have files
            assert any(Path(db_dir).rglob("*.db"))


async def test_recover_eval_log_default_output_path() -> None:
    """Verify default output path is <name>-recovered.eval."""
    async with AsyncFilesystem():
        with tempfile.TemporaryDirectory() as temp_dir:
            eval_path = os.path.join(temp_dir, "mylog.eval")
            db_dir = os.path.join(temp_dir, "bufferdb")

            _write_crashed_eval(eval_path)
            _create_buffer_db(
                eval_path, completed_ids=[1], in_progress_ids=[], db_dir=db_dir
            )

            await recover_eval_log_async(eval_path, _db_dir=db_dir)

            expected = os.path.join(temp_dir, "mylog-recovered.eval")
            assert os.path.exists(expected)


def test_recoverable_eval_logs() -> None:
    """Test discovery of recoverable logs."""
    with tempfile.TemporaryDirectory() as temp_dir:
        db_dir = os.path.join(temp_dir, "bufferdb")

        crashed_path = os.path.join(temp_dir, "crashed.eval")
        _write_crashed_eval(crashed_path)
        _create_buffer_db(
            crashed_path, completed_ids=[1], in_progress_ids=[2], db_dir=db_dir
        )

        # Create a complete log (should be excluded)
        complete_path = os.path.join(temp_dir, "complete.eval")
        eval_spec = _make_eval_spec("complete_task")
        plan = EvalPlan()
        log_start = LogStart(version=LOG_SCHEMA_VERSION, eval=eval_spec, plan=plan)
        with ZipFile(complete_path, "w") as zf:
            zf.writestr("_journal/start.json", _to_json(log_start))
            header = EvalLog(
                version=LOG_SCHEMA_VERSION,
                eval=eval_spec,
                plan=plan,
                status="success",
            )
            zf.writestr(HEADER_JSON, _to_json(header))

        result = recoverable_eval_logs(log_dir=temp_dir, _db_dir=db_dir)

        assert len(result) == 1
        assert "crashed.eval" in result[0].log.name
        assert result[0].completed_samples == 1
        assert result[0].in_progress_samples == 1


def test_recoverable_eval_logs_excludes_already_recovered() -> None:
    """Test that already-recovered logs are excluded."""
    with tempfile.TemporaryDirectory() as temp_dir:
        db_dir = os.path.join(temp_dir, "bufferdb")

        crashed_path = os.path.join(temp_dir, "test.eval")
        _write_crashed_eval(crashed_path)
        _create_buffer_db(
            crashed_path, completed_ids=[1], in_progress_ids=[], db_dir=db_dir
        )

        # Create the recovered file (simulating prior recovery)
        recovered_path = os.path.join(temp_dir, "test-recovered.eval")
        eval_spec = _make_eval_spec()
        plan = EvalPlan()
        log_start = LogStart(version=LOG_SCHEMA_VERSION, eval=eval_spec, plan=plan)
        with ZipFile(recovered_path, "w") as zf:
            zf.writestr("_journal/start.json", _to_json(log_start))
            header = EvalLog(
                version=LOG_SCHEMA_VERSION,
                eval=eval_spec,
                plan=plan,
                status="error",
            )
            zf.writestr(HEADER_JSON, _to_json(header))

        result = recoverable_eval_logs(log_dir=temp_dir, _db_dir=db_dir)
        assert len(result) == 0


def _write_header_eval(
    path: str,
    *,
    task: str = "test_task",
    status: Literal["started", "success", "cancelled", "error"] = "started",
) -> None:
    """Write a complete .eval with header.json (for listing/filter tests)."""
    eval_spec = _make_eval_spec(task)
    plan = EvalPlan()
    log_start = LogStart(version=LOG_SCHEMA_VERSION, eval=eval_spec, plan=plan)
    with ZipFile(path, "w") as zf:
        zf.writestr("_journal/start.json", _to_json(log_start))
        header = EvalLog(
            version=LOG_SCHEMA_VERSION,
            eval=eval_spec,
            plan=plan,
            status=status,
        )
        zf.writestr(HEADER_JSON, _to_json(header))


def _run_recover_async_paths(backend: str) -> None:
    """Exercise async recovery + discovery under the given anyio backend.

    Uses the non-canonical ``test.eval`` name so metadata resolution must
    fall through to the async header reader (not the sync filename parser
    alone). Sample count is taken from an async re-read so LazyList
    materialization cannot re-enter sync ``read_eval_log`` under trio.
    """

    async def main() -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            eval_path = os.path.join(temp_dir, "test.eval")
            db_dir = os.path.join(temp_dir, "bufferdb")
            output_path = os.path.join(temp_dir, "test-recovered.eval")

            flushed = [_make_sample(1), _make_sample(2)]
            _write_crashed_eval(eval_path, samples=flushed)
            _create_buffer_db(
                eval_path, completed_ids=[3], in_progress_ids=[4], db_dir=db_dir
            )

            recoverable = await _recoverable_eval_logs_async(
                log_dir=temp_dir, _db_dir=db_dir
            )
            assert len(recoverable) == 1
            assert "test.eval" in recoverable[0].log.name

            # No caller-provided AsyncFilesystem: recover must be self-contained.
            log = await recover_eval_log_async(
                eval_path, output=output_path, cleanup=False, _db_dir=db_dir
            )
            assert log.status == "error"
            assert os.path.exists(output_path)
            assert any(Path(db_dir).rglob("*.db"))

            async with AsyncFilesystem():
                reread = await read_eval_log_async(output_path)
            assert reread.samples is not None
            assert len(reread.samples) == 4

    anyio.run(main, backend=backend)


def test_recover_async_paths_under_trio_backend() -> None:
    """Regression: async recovery paths must work under a trio backend.

    Ordinary CI runs this sync harness via ``anyio.run(..., backend="trio")``
    without needing ``--runtrio``. Sync ``recoverable_eval_logs()`` remains
    out of scope here — it still raises under trio via ``run_coroutine()``.
    """
    _run_recover_async_paths("trio")


def test_recover_async_paths_under_asyncio_backend() -> None:
    """Asyncio parity for the same recovery/discovery body as the trio harness."""
    _run_recover_async_paths("asyncio")


def test_sync_recoverable_eval_logs_raises_under_trio() -> None:
    """Document unchanged scope: sync discovery still Trio-prohibited."""
    import warnings

    async def main() -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            with warnings.catch_warnings():
                # run_coroutine raises before awaiting the coroutine it was given.
                warnings.simplefilter("ignore", RuntimeWarning)
                with pytest.raises(RuntimeError, match="run_coroutine"):
                    recoverable_eval_logs(log_dir=temp_dir)

    anyio.run(main, backend="trio")


async def test_list_eval_logs_filtered_missing_directory() -> None:
    from inspect_ai.log._recover._api import _list_eval_logs_filtered_async

    missing = os.path.join(tempfile.gettempdir(), "inspect-missing-logs-dir-xyz")
    assert not os.path.exists(missing)
    result = await _list_eval_logs_filtered_async(missing, lambda _: True)
    assert result == []


async def test_list_eval_logs_filtered_canonical_filename() -> None:
    from inspect_ai.log._recover._api import _list_eval_logs_filtered_async

    with tempfile.TemporaryDirectory() as temp_dir:
        name = "2024-01-15T10-30-00_mytask_abcd1234.eval"
        path = os.path.join(temp_dir, name)
        _write_crashed_eval(path)

        logs = await _list_eval_logs_filtered_async(
            temp_dir, lambda log: log.status == "started"
        )
        assert len(logs) == 1
        assert name in logs[0].name
        assert logs[0].task == "mytask"
        assert logs[0].task_id == "abcd1234"


async def test_list_eval_logs_filtered_noncanonical_header_fallback() -> None:
    """Non-canonical ``test.eval`` forces async header metadata fallback."""
    from inspect_ai.log._recover._api import _list_eval_logs_filtered_async

    with tempfile.TemporaryDirectory() as temp_dir:
        path = os.path.join(temp_dir, "test.eval")
        _write_crashed_eval(path, task="fallback_task")

        logs = await _list_eval_logs_filtered_async(
            temp_dir, lambda log: log.status == "started"
        )
        assert len(logs) == 1
        assert "test.eval" in logs[0].name
        assert logs[0].task == "fallback_task"


async def test_list_eval_logs_filtered_recursive_false() -> None:
    from inspect_ai.log._recover._api import _list_eval_logs_filtered_async

    with tempfile.TemporaryDirectory() as temp_dir:
        nested = os.path.join(temp_dir, "nested")
        os.makedirs(nested)
        _write_crashed_eval(os.path.join(temp_dir, "top.eval"))
        _write_crashed_eval(os.path.join(nested, "nested.eval"))

        logs = await _list_eval_logs_filtered_async(
            temp_dir, lambda log: log.status == "started", recursive=False
        )
        assert len(logs) == 1
        assert "top.eval" in logs[0].name
        assert "nested.eval" not in logs[0].name


async def test_list_eval_logs_filtered_preserves_order() -> None:
    from inspect_ai.log._recover._api import _list_eval_logs_filtered_async

    with tempfile.TemporaryDirectory() as temp_dir:
        older = os.path.join(temp_dir, "older.eval")
        newer = os.path.join(temp_dir, "newer.eval")
        _write_header_eval(older, task="older_task", status="started")
        _write_header_eval(newer, task="newer_task", status="started")
        os.utime(older, (1_700_000_000, 1_700_000_000))
        os.utime(newer, (1_800_000_000, 1_800_000_000))

        logs = await _list_eval_logs_filtered_async(
            temp_dir, lambda log: log.status == "started"
        )
        assert [log.task for log in logs] == ["newer_task", "older_task"]


async def test_list_eval_logs_filtered_predicate_subset() -> None:
    from inspect_ai.log._recover._api import _list_eval_logs_filtered_async

    with tempfile.TemporaryDirectory() as temp_dir:
        _write_header_eval(
            os.path.join(temp_dir, "ok.eval"), task="ok", status="success"
        )
        _write_header_eval(
            os.path.join(temp_dir, "bad.eval"), task="bad", status="error"
        )
        _write_crashed_eval(os.path.join(temp_dir, "live.eval"), task="live")

        success = await _list_eval_logs_filtered_async(
            temp_dir, lambda log: log.status == "success"
        )
        assert len(success) == 1
        assert "ok.eval" in success[0].name

        none = await _list_eval_logs_filtered_async(
            temp_dir, lambda log: log.status == "cancelled"
        )
        assert none == []


async def test_list_eval_logs_filtered_listing_failure_propagates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import inspect_ai.log._recover._api as api
    from inspect_ai.log._recover._api import _list_eval_logs_filtered_async

    boom_fs = MagicMock()
    boom_fs.exists.return_value = True
    boom_fs.ls.side_effect = OSError("listing failed")
    monkeypatch.setattr(api, "filesystem", lambda _path: boom_fs)

    with tempfile.TemporaryDirectory() as temp_dir:
        with pytest.raises(OSError, match="listing failed"):
            await _list_eval_logs_filtered_async(temp_dir, lambda _: True)


def test_list_eval_logs_filtered_cancellation_propagates() -> None:
    async def main() -> None:
        import inspect_ai.log._recover._api as api
        from inspect_ai.log._recover._api import _list_eval_logs_filtered_async

        real_run_sync = anyio.to_thread.run_sync

        async def slow_run_sync(func, *args, **kwargs):  # type: ignore[no-untyped-def]
            await anyio.sleep(60)
            return await real_run_sync(func, *args, **kwargs)

        original = api.anyio.to_thread.run_sync
        api.anyio.to_thread.run_sync = slow_run_sync  # type: ignore[method-assign]
        try:
            with anyio.move_on_after(0.1) as scope:
                await _list_eval_logs_filtered_async(
                    tempfile.gettempdir(), lambda _: True
                )
            assert scope.cancel_called
        finally:
            api.anyio.to_thread.run_sync = original  # type: ignore[method-assign]

    anyio.run(main)


async def test_recover_eval_log_async_without_caller_async_filesystem() -> None:
    """Public recover path must enter AsyncFilesystem itself when listing."""
    with tempfile.TemporaryDirectory() as temp_dir:
        eval_path = os.path.join(temp_dir, "test.eval")
        db_dir = os.path.join(temp_dir, "bufferdb")
        output_path = os.path.join(temp_dir, "test-recovered.eval")

        _write_crashed_eval(eval_path, samples=[_make_sample(1)])
        _create_buffer_db(
            eval_path, completed_ids=[2], in_progress_ids=[], db_dir=db_dir
        )

        log = await recover_eval_log_async(
            eval_path, output=output_path, cleanup=False, _db_dir=db_dir
        )
        assert log.status == "error"
        assert os.path.exists(output_path)
