"""PROTOTYPE: tamper-evident eval logs, step 1, against moto server.

Runs real evals (mockllm, react agents, parallel and serial tool stages, a
sub-agent used as a tool, two sub-agents at once, streamed output) with the
add-only store on, then validates the store and the .eval files.
See design/prototype-tamper-evident-logs-findings.md.
"""

import json
import uuid
from collections.abc import Iterator, Mapping
from dataclasses import replace
from pathlib import Path
from typing import Any

import anyio
import pytest
from botocore.exceptions import EndpointConnectionError, ReadTimeoutError
from click.testing import CliRunner
from test_helpers.addonly_agents import (
    agent_task,
    run,
    scripted_call,
    scripted_output,
)
from test_helpers.addonly_moto import BUCKET, MotoStore, moto_addonly_store

from inspect_ai import Task, eval
from inspect_ai._cli.validate import validate_command
from inspect_ai._eval.task.log import TaskLogger
from inspect_ai._util.registry import _registry
from inspect_ai.agent import react
from inspect_ai.dataset import Sample
from inspect_ai.event import Event, InfoEvent
from inspect_ai.log import write_eval_log
from inspect_ai.log._addonly import ADDONLY_STORE_ENV
from inspect_ai.log._addonly._records import SampleAttemptRef, SampleRecord
from inspect_ai.log._addonly._store import (
    AddOnlyStore,
    AddOnlyStoreError,
    StoreLocation,
    sample_key_part,
)
from inspect_ai.log._addonly._validate import (
    ValidationReport,
    _event_version_problems,
)
from inspect_ai.log._addonly._writer import EvalRecordWriter
from inspect_ai.log._recorders.buffer.database import SampleBufferDatabase
from inspect_ai.log._recorders.buffer.types import BufferEventRow, BufferRows
from inspect_ai.log._transcript import transcript
from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    GenerateConfig,
    ModelAPI,
    ModelOutput,
    get_model,
    modelapi,
)
from inspect_ai.model._providers.mockllm import MockLLM
from inspect_ai.model._stream import (
    StreamTextEvent,
    model_stream_requested,
    report_model_stream_delta,
    report_model_stream_start,
)
from inspect_ai.scorer import includes
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.tool import Tool, ToolChoice, ToolInfo, tool

# ---------------------------------------------------------------- fixtures


@pytest.fixture(scope="module")
def moto_store() -> Iterator[MotoStore]:
    with moto_addonly_store() as store:
        yield store


@pytest.fixture
def evalhost_env(moto_store: MotoStore, monkeypatch: pytest.MonkeyPatch) -> MotoStore:
    """The eval host's environment, with a store prefix of the test's own."""
    store = replace(moto_store, url=f"s3://{BUCKET}/{uuid.uuid4().hex}")
    for key, value in store.env(store.evalhost).items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv(ADDONLY_STORE_ENV, store.url)
    return store


def validate(store: MotoStore, log_dir: Path) -> ValidationReport:
    return store.validate(log_dir)


# --------------------------------------------------------- end-to-end runs


def test_agent_eval_validates(evalhost_env: MotoStore, tmp_path: Path) -> None:
    """Real eval: validator finds nothing (answers 1-3), and the paths ran."""
    log = run(agent_task(epochs=2, samples=3), tmp_path, max_samples=3)
    assert log.status == "success", log.error

    report = validate(evalhost_env, tmp_path)
    assert report.findings == []
    assert report.samples_compared == 6
    assert log.eval.eval_id in report.evals

    # the run exercised a pending event stored before it completed: the
    # sub-agent tool calls span the sub-agents' own boundaries
    records = _sample_records(evalhost_env, log.eval.eval_id)
    spans = _events_completed_in_later_record(records)
    assert any(kind == "tool" for kind, _, _ in spans), spans


def test_streaming_eval_validates(evalhost_env: MotoStore, tmp_path: Path) -> None:
    """Streamed partial output (pending event versions) validates."""

    @modelapi(name="mockstream")
    def mockstream() -> type[ModelAPI]:
        return StreamingMockLLM

    @solver
    def streaming_generate() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            chunks: list[str] = []

            async def on_stream(event: Any) -> None:
                chunks.append(str(event))

            state.output = await get_model().generate(
                state.messages, on_stream=on_stream
            )
            state.messages.append(state.output.message)
            assert chunks
            return state

        return solve

    try:
        log = eval(
            Task(
                dataset=[Sample(input="hi", target="streamed")],
                solver=streaming_generate(),
                scorer=includes(),
            ),
            model="mockstream/model",
            log_dir=str(tmp_path),
            display="none",
        )[0]
    finally:
        del _registry["modelapi:mockstream"]
    assert log.status == "success", log.error

    report = validate(evalhost_env, tmp_path)
    assert report.findings == []
    assert report.samples_compared == 1

    # partial output reached the buffer as pending versions of the model event
    records = _sample_records(evalhost_env, log.eval.eval_id)
    model_rows = [
        json.loads(row.data)
        for r in records
        for row in r.rows.events
        if json.loads(row.data)["event"] == "model"
    ]
    assert any(e.get("pending") and e["output"]["choices"] for e in model_rows)


class StreamingMockLLM(MockLLM):
    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> Any:
        report_model_stream_start()
        if model_stream_requested():
            for word in ["str", "eam", "ed"]:
                await report_model_stream_delta(StreamTextEvent(text=word))
                await anyio.sleep(0.6)  # partial snapshots are throttled
        return ModelOutput.from_content(model="mockllm", content="streamed")


# --------------------------------------------------------------- tampering


def test_edit_eval_file_detected(evalhost_env: MotoStore, tmp_path: Path) -> None:
    log = run(agent_task(), tmp_path)
    assert log.samples
    tool_event = next(e for e in log.samples[0].events if e.event == "tool")
    tool_event.result = "harmless"
    write_eval_log(log, log.location)

    report = validate(evalhost_env, tmp_path)
    mismatches = [f for f in report.findings if f.kind == "event_mismatch"]
    assert len(mismatches) == 1 and "result" in mismatches[0].message


def test_validate_cli(
    evalhost_env: MotoStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = run(agent_task(samples=1), tmp_path)
    for key, value in evalhost_env.env(evalhost_env.validator).items():
        monkeypatch.setenv(key, value)
    evalhost_env.require_if_none_match_policy()
    try:
        args = [str(tmp_path), "--store", evalhost_env.url]
        passed = CliRunner().invoke(validate_command, args)
        assert passed.exit_code == 0, passed.output
        assert "1 sample(s) compared, 0 finding(s)" in passed.output

        Path(log.location).unlink()
        failed = CliRunner().invoke(validate_command, args)
        assert failed.exit_code != 0
        assert "missing_eval_file" in failed.output
    finally:
        evalhost_env.client(evalhost_env.admin).delete_bucket_policy(Bucket=BUCKET)


def test_overwrite_and_forged_record_detected(
    evalhost_env: MotoStore, tmp_path: Path
) -> None:
    log = run(agent_task(samples=1), tmp_path)
    eval_id = log.eval.eval_id
    sample_prefix = f"{evalhost_env.prefix}/{eval_id}/s0.1/1"
    admin = evalhost_env.client(evalhost_env.admin)
    evalhost = evalhost_env.client(evalhost_env.evalhost)

    # without If-None-Match an overwrite only adds a version (moto does not
    # enforce the bucket policy that would refuse it)
    first = admin.get_object(Bucket=BUCKET, Key=f"{sample_prefix}/1")["Body"].read()
    evalhost.put_object(Bucket=BUCKET, Key=f"{sample_prefix}/1", Body=first)
    # another eval adds a record to this sample; it cannot know the nonce
    forged = SampleRecord(
        eval_id=eval_id,
        nonce="0" * 64,
        sample=SampleAttemptRef(sample_id="s0", epoch=1, attempt=1),
        seq=99,
        rows=BufferRows(),
    )
    evalhost.put_object(
        Bucket=BUCKET,
        Key=f"{sample_prefix}/99",
        Body=forged.model_dump_json(),
        IfNoneMatch="*",
    )

    kinds = {f.kind for f in validate(evalhost_env, tmp_path).findings}
    assert {"overwrite", "nonce", "sequence_gap", "record_count"} <= kinds


def test_deleted_eval_file_detected(evalhost_env: MotoStore, tmp_path: Path) -> None:
    log = run(agent_task(samples=1), tmp_path)
    Path(log.location).unlink()
    report = validate(evalhost_env, tmp_path)
    missing = [f for f in report.findings if f.kind == "missing_eval_file"]
    assert [f.eval_id for f in missing] == [log.eval.eval_id]


def test_prefix_per_log_dir_scopes_validation(
    evalhost_env: MotoStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two log dirs share the bucket, each with its own store prefix."""
    other = replace(evalhost_env, url=f"{evalhost_env.url}x")
    run(agent_task(samples=1), tmp_path / "a")
    monkeypatch.setenv(ADDONLY_STORE_ENV, other.url)
    run(agent_task(samples=1), tmp_path / "b")

    assert validate(evalhost_env, tmp_path / "a").findings == []
    assert validate(other, tmp_path / "b").findings == []
    missing = validate(evalhost_env, tmp_path / "b").findings
    assert [f.kind for f in missing] == ["missing_eval_file"]


def test_sample_key_encoding() -> None:
    assert sample_key_part("a.1", 2) == "a%2E1.2"
    assert sample_key_part("a/1", 2) == "a%2F1.2"
    assert sample_key_part(7, 1) == "7.1"


def test_late_event_version_flagged() -> None:
    def record(seq: int, *events: dict[str, Any]) -> SampleRecord:
        return SampleRecord(
            eval_id="e",
            nonce="n",
            sample=SampleAttemptRef(sample_id=1, epoch=1, attempt=1),
            seq=seq,
            rows=BufferRows(
                events=[
                    BufferEventRow(event_id=e["uuid"], data=json.dumps(e))
                    for e in events
                ]
            ),
        )

    pending = {"uuid": "a", "event": "tool", "pending": True}
    done = {"uuid": "a", "event": "tool"}
    other = {"uuid": "b", "event": "model"}
    # pending in 1, completed in 2: legitimate
    assert list(_event_version_problems([record(1, pending), record(2, done)])) == []
    # several versions inside one record: legitimate
    assert list(_event_version_problems([record(1, pending, done)])) == []
    # a version after a boundary stored it complete: flagged
    problems = list(_event_version_problems([record(1, done), record(2, other, done)]))
    assert [kind for kind, _ in problems] == ["late_event_version"]


# ---------------------------------------------------------------- failures


def test_store_settings_checked_before_samples(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with moto_addonly_store() as store:
        store.client(store.admin).put_object_lock_configuration(
            Bucket=BUCKET,
            ObjectLockConfiguration={
                "ObjectLockEnabled": "Enabled",
                "Rule": {"DefaultRetention": {"Mode": "GOVERNANCE", "Days": 1}},
            },
        )
        for key, value in store.env(store.evalhost).items():
            monkeypatch.setenv(key, value)
        monkeypatch.setenv(ADDONLY_STORE_ENV, store.url)
        log = run(agent_task(samples=1), tmp_path)
        assert log.status == "error"
        assert log.error and "COMPLIANCE" in log.error.message
        assert not log.samples


def test_failed_write_stops_eval(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The store refuses writes mid-sample: the eval stops, no closing record."""
    with moto_addonly_store() as store:
        admin_iam = _iam(store)

        @tool
        def revoke() -> Tool:
            async def execute() -> str:
                """Revoke the eval host's write permission."""
                admin_iam.delete_user_policy(UserName="evalhost", PolicyName="evalhost")
                return "revoked"

            return execute

        def outputs(
            input: list[ChatMessage], tools: list[ToolInfo], *_: Any
        ) -> ModelOutput:
            turn = sum(isinstance(m, ChatMessageAssistant) for m in input)
            if turn == 0:
                return scripted_output("", scripted_call("v1", "revoke"))
            return scripted_output("", scripted_call("s1", "submit", answer="42"))

        for key, value in store.env(store.evalhost).items():
            monkeypatch.setenv(key, value)
        monkeypatch.setenv(ADDONLY_STORE_ENV, store.url)
        log = eval(
            Task(
                dataset=[Sample(input="go", target="42")],
                solver=react(tools=[revoke()]),
                scorer=includes(),
            ),
            model=get_model("mockllm/model", custom_outputs=outputs),
            log_dir=str(tmp_path),
            display="none",
            fail_on_error=False,
            retry_on_error=2,
        )[0]
        assert log.status == "error"
        assert log.error and "AccessDenied" in log.error.message

        kinds = [f.kind for f in validate(store, tmp_path).findings]
        assert "missing_closing" in kinds


class _FlakyPut:
    """An S3 client whose first put fails with a network error.

    With ``stored``, the first put reaches the store and only its response is
    lost.
    """

    def __init__(self, client: Any, stored: bool) -> None:
        self._client = client
        self._stored = stored
        self.puts = 0

    def put_object(self, **kwargs: Any) -> Any:
        self.puts += 1
        if self.puts > 1:
            return self._client.put_object(**kwargs)
        if self._stored:
            self._client.put_object(**kwargs)
            raise ReadTimeoutError(endpoint_url="moto")
        raise EndpointConnectionError(endpoint_url="moto")


@pytest.mark.parametrize("stored", [False, True], ids=["not_stored", "response_lost"])
async def test_put_retries_and_412_after_retry(
    evalhost_env: MotoStore, stored: bool
) -> None:
    """A transient error is retried; a 412 after a retried put fails the write."""
    client = _FlakyPut(evalhost_env.client(evalhost_env.evalhost), stored)
    store = AddOnlyStore(StoreLocation.parse(evalhost_env.url), client)
    if stored:
        with pytest.raises(AddOnlyStoreError, match="PreconditionFailed.*own earlier"):
            await store.put("record", b"{}")
    else:
        await store.put("record", b"{}")
    assert client.puts == 2


def test_put_has_sdk_retries_off(evalhost_env: MotoStore) -> None:
    store = AddOnlyStore(StoreLocation.parse(evalhost_env.url))
    assert store._client.meta.config.retries["total_max_attempts"] == 1


def test_failed_buffer_insert_stops_sample(
    evalhost_env: MotoStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An event the buffer cannot insert stops its sample at the next boundary."""
    log_sample_event = TaskLogger.log_sample_event

    def failing_insert(
        self: TaskLogger,
        id: str | int,
        epoch: int,
        event: Event,
        call_attachments: Mapping[str, str],
    ) -> None:
        if isinstance(event, InfoEvent) and event.data == "fail insert":
            raise RuntimeError("disk full")
        log_sample_event(self, id, epoch, event, call_attachments)

    monkeypatch.setattr(TaskLogger, "log_sample_event", failing_insert)

    @tool
    def unlucky() -> Tool:
        async def execute() -> str:
            """Record an event the sample buffer cannot insert."""
            transcript().info("fail insert")
            return "done"

        return execute

    requests: list[int] = []

    def outputs(
        input: list[ChatMessage], tools: list[ToolInfo], *_: Any
    ) -> ModelOutput:
        turn = sum(isinstance(m, ChatMessageAssistant) for m in input)
        requests.append(turn)
        if turn == 0:
            return scripted_output("", scripted_call("u1", "unlucky"))
        return scripted_output("", scripted_call("s1", "submit", answer="42"))

    log = eval(
        Task(
            dataset=[Sample(input="go", target="42")],
            solver=react(tools=[unlucky()]),
            scorer=includes(),
        ),
        model=get_model("mockllm/model", custom_outputs=outputs),
        log_dir=str(tmp_path),
        display="none",
        fail_on_error=False,
    )[0]
    # the sample stops; the eval goes on (unlike a failed write)
    assert log.status == "success", log.error
    assert log.samples and log.samples[0].error
    assert "sample buffer" in log.samples[0].error.message
    # the boundary before the next request stopped it
    assert requests == [0]

    kinds = [f.kind for f in validate(evalhost_env, tmp_path).findings]
    assert "missing_closing" in kinds


# ------------------------------------------------------------------- writer


class _GatedStore(AddOnlyStore):
    """Records put keys; the put of record 1 waits for ``gate``."""

    def __init__(self, fail: bool) -> None:
        self.gate = anyio.Event()
        self.fail = fail
        self.keys: list[str] = []

    async def put(self, key: str, body: bytes) -> None:
        self.keys.append(key.rsplit("/", 1)[1])
        if key.endswith("/1"):
            await self.gate.wait()
            if self.fail:
                raise AddOnlyStoreError("refused")


@pytest.mark.parametrize("fail", [False, True], ids=["confirmed", "failed"])
async def test_writes_overlap_and_wait_for_earlier_numbers(
    tmp_path: Path, fail: bool
) -> None:
    """A boundary puts without waiting for an earlier put, then waits for it."""
    db = SampleBufferDatabase(location=str(tmp_path / "x.eval"), db_dir=tmp_path)
    store = _GatedStore(fail)
    writer = EvalRecordWriter(store, "e", "n").sample_writer(db, "s", 1, 1)

    def record_event(event_id: str) -> None:
        db.insert_sample_rows(
            "s", 1, BufferRows(events=[BufferEventRow(event_id=event_id, data="{}")])
        )

    finished: list[str] = []

    async def boundary(name: str) -> None:
        try:
            await writer.write()
            finished.append(name)
        except AddOnlyStoreError:
            finished.append(f"{name} raised")

    async with anyio.create_task_group() as tg:
        record_event("a")
        tg.start_soon(boundary, "first")
        await anyio.wait_all_tasks_blocked()
        record_event("b")
        tg.start_soon(boundary, "second")
        # no new rows: puts nothing, but still waits for record 1
        tg.start_soon(boundary, "empty")
        await anyio.wait_all_tasks_blocked()
        assert store.keys == ["1", "2"]
        assert finished == []
        store.gate.set()

    assert sorted(finished) == sorted(
        ["first raised", "second raised", "empty raised"]
        if fail
        else ["first", "second", "empty"]
    )
    db.cleanup()


# ----------------------------------------------------------------- helpers


def _iam(store: MotoStore) -> Any:
    import boto3

    return boto3.client(
        "iam",
        endpoint_url=store.endpoint,
        region_name="us-east-1",
        aws_access_key_id=store.admin.access_key_id,
        aws_secret_access_key=store.admin.secret_access_key,
    )


def _sample_records(store: MotoStore, eval_id: str) -> list[SampleRecord]:
    s3 = store.client(store.validator)
    keys = [
        o["Key"]
        # (no "/" in the prefix: moto's signature check fails on it)
        for o in s3.list_objects_v2(Bucket=BUCKET, Prefix=store.prefix).get(
            "Contents", []
        )
        if o["Key"].startswith(f"{store.prefix}/{eval_id}/")
        and o["Key"].rsplit("/", 1)[1].isdigit()
    ]
    return [
        SampleRecord.model_validate_json(
            s3.get_object(Bucket=BUCKET, Key=key)["Body"].read()
        )
        for key in keys
    ]


def _events_completed_in_later_record(
    records: list[SampleRecord],
) -> list[tuple[str, int, int]]:
    """(event kind, record stored pending, record completed) per event."""
    first_pending: dict[tuple[str, int, str], tuple[str, int]] = {}
    spans: list[tuple[str, int, int]] = []
    for r in sorted(records, key=lambda r: (str(r.sample), r.seq)):
        for row in r.rows.events:
            event = json.loads(row.data)
            key = (str(r.sample), r.sample.epoch, row.event_id)
            if event.get("pending"):
                first_pending.setdefault(key, (event["event"], r.seq))
            elif key in first_pending and first_pending[key][1] < r.seq:
                kind, seq = first_pending.pop(key)
                spans.append((kind, seq, r.seq))
    return spans
