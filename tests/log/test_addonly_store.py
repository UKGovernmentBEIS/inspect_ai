"""Tamper-evident logs, against moto server.

Runs real evals (mockllm, react agents, parallel and serial tool stages, a
sub-agent used as a tool, two sub-agents at once, streamed output) with the
add-only store on, then validates the store and the .eval files. The
tampering tests change a clean run's .eval file or store, then run the
`inspect validate` command and check its findings. See
design/tamper-evident-logs-findings.md.
"""

import json
import os
import shutil
import subprocess
import sys
import threading
import uuid
import zipfile
from collections.abc import Callable, Iterator
from dataclasses import replace
from functools import reduce
from pathlib import Path
from typing import Any, NamedTuple

import anyio
import pytest
from botocore.exceptions import ClientError, EndpointConnectionError, ReadTimeoutError
from test_helpers.addonly_agents import (
    agent_task,
    run,
    scripted_call,
    scripted_output,
)
from test_helpers.addonly_gates import cancel_gates
from test_helpers.addonly_moto import (
    BUCKET,
    CliResult,
    MotoStore,
    moto_addonly_store,
)

from inspect_ai import SampleSource, Task, eval, eval_retry, eval_set, score, task
from inspect_ai._control.cancel import cancel_task
from inspect_ai._control.eval_state import get_eval_states
from inspect_ai._eval.score import (
    ScoreAction,
    _get_updated_events,
    _get_updated_scores,
)
from inspect_ai._util.registry import _registry
from inspect_ai.agent import react
from inspect_ai.dataset import Sample
from inspect_ai.event import InfoEvent, ScoreEvent, ToolEvent
from inspect_ai.hooks import (
    Hooks,
    SampleAttemptEnd,
    SampleEnd,
    SampleEvent,
    SampleInit,
    SampleScoring,
    hooks,
)
from inspect_ai.log import EvalLog, EvalSample, EvalSpec, read_eval_log, write_eval_log
from inspect_ai.log._addonly._records import (
    CLOSING,
    RESCORE_MARKER_SOURCE,
    START,
    EvalClosingRecord,
    RescoreMarker,
    RescoreSampleRecord,
    SampleAttemptRef,
    SampleClosingRecord,
    SampleRecord,
    StartRecord,
)
from inspect_ai.log._addonly._store import (
    AddOnlyStore,
    AddOnlyStoreError,
    StoreLocation,
    sample_key_part,
)
from inspect_ai.log._addonly._validate import (
    FindingKind,
    ValidationReport,
    _event_version_problems,
    _read_eval,
    _rebuild_rows,
    read_eval_nonce,
    validate_store,
)
from inspect_ai.log._addonly._writer import (
    RESCORE_NONCE_ENV,
    EvalRecordWriter,
    store_boundary,
)
from inspect_ai.log._recorders.buffer.database import SampleBufferDatabase
from inspect_ai.log._recorders.buffer.types import (
    BufferAttachmentRow,
    BufferEventRow,
    BufferPoolRow,
    BufferRows,
)
from inspect_ai.log._recorders.eval import EvalRecorder
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
from inspect_ai.scorer import Score, Scorer, Target, includes, mean, scorer
from inspect_ai.scorer._scorer import unique_scorer_name
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.tool import Tool, ToolChoice, ToolInfo, tool

# ---------------------------------------------------------------- fixtures


@pytest.fixture(scope="module")
def moto_store() -> Iterator[MotoStore]:
    with moto_addonly_store() as store:
        yield store


@pytest.fixture
def evalhost_env(moto_store: MotoStore, monkeypatch: pytest.MonkeyPatch) -> MotoStore:
    """The eval host's environment, with a store prefix of the test's own.

    Evals write to the store when given ``tamper_evident_store=store.url``.
    """
    store = replace(moto_store, url=f"s3://{BUCKET}/{uuid.uuid4().hex}")
    for key, value in store.env(store.evalhost).items():
        monkeypatch.setenv(key, value)
    return store


def validate(store: MotoStore, log_dir: Path) -> ValidationReport:
    return store.validate(log_dir)


def logged_samples(store: MotoStore, eval_id: str) -> list[str]:
    """The samples the eval closing record lists as in the .eval file."""
    body = (
        store.client(store.admin)
        .get_object(Bucket=BUCKET, Key=f"{store.prefix}/{eval_id}/{CLOSING}")["Body"]
        .read()
    )
    return EvalClosingRecord.model_validate_json(body).logged


ValidateCli = Callable[..., CliResult]


@pytest.fixture
def validate_cli() -> ValidateCli:
    """Runs `inspect validate` (a subprocess)."""
    return MotoStore.validate_cli


class CleanRun(NamedTuple):
    """An agent eval with one sample, run with the store on, that validates clean."""

    store: MotoStore
    log_dir: Path
    log: EvalLog

    @property
    def eval_id(self) -> str:
        return self.log.eval.eval_id

    @property
    def location(self) -> Path:
        return Path(self.log.location)

    def sample_key(self, last: str | int, attempt: int = 1) -> str:
        """Key (under the store prefix) of a record of sample s0, epoch 1."""
        return f"{self.eval_id}/s0.1/{attempt}/{last}"

    def records(self) -> int:
        """Number of sample records of s0, from its closing record."""
        return SampleClosingRecord.model_validate_json(
            self.read(self.sample_key(CLOSING))
        ).records

    def read(self, key: str) -> bytes:
        s3 = self.store.client(self.store.admin)
        body: bytes = s3.get_object(Bucket=BUCKET, Key=f"{self.store.prefix}/{key}")[
            "Body"
        ].read()
        return body

    def put(self, key: str, body: str | bytes, if_none_match: bool = True) -> None:
        """Put as the eval host: it can add keys, never read or delete them."""
        self.store.client(self.store.evalhost).put_object(
            Bucket=BUCKET,
            Key=f"{self.store.prefix}/{key}",
            Body=body,
            **({"IfNoneMatch": "*"} if if_none_match else {}),
        )

    def forged_record(self, seq: int, *events: dict[str, Any], attempt: int = 1) -> str:
        """A sample record of s0 from someone without the eval's nonce."""
        return SampleRecord(
            eval_id=self.eval_id,
            nonce=FORGED_NONCE,
            sample=SampleAttemptRef(sample_id="s0", epoch=1, attempt=attempt),
            seq=seq,
            rows=BufferRows(
                events=[
                    BufferEventRow(event_id=e["uuid"], data=json.dumps(e))
                    for e in events
                ]
            ),
        ).model_dump_json()

    def stored_events(self, seq: int) -> list[dict[str, Any]]:
        record = SampleRecord.model_validate_json(self.read(self.sample_key(seq)))
        return [json.loads(row.data) for row in record.rows.events]


FORGED_NONCE = "0" * 64


@pytest.fixture
def clean_run(evalhost_env: MotoStore, tmp_path: Path) -> CleanRun:
    log = run(agent_task(samples=1), tmp_path, tamper_evident_store=evalhost_env.url)
    assert log.status == "success", log.error
    assert validate(evalhost_env, tmp_path).findings == []
    return CleanRun(evalhost_env, tmp_path, log)


def edit_sample(clean: CleanRun, edit: Callable[[EvalSample], None]) -> None:
    """Edit sample s0 of the .eval file with inspect's own log API."""
    log = read_eval_log(clean.location)
    assert log.samples
    edit(log.samples[0])
    write_eval_log(log, clean.location)


def edit_zip_entry(path: Path, name: str, edit: Callable[[Any], Any]) -> None:
    """Edit one JSON entry of a .eval file's zip in place, as a person with a zip tool could."""
    with zipfile.ZipFile(path) as zf:
        entries = {info.filename: zf.read(info) for info in zf.infolist()}
    entries[name] = json.dumps(edit(json.loads(entries[name]))).encode()
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for entry, data in entries.items():
            zf.writestr(entry, data)


def assert_fails_with(result: CliResult, *kinds: str) -> None:
    """The validator failed, with exactly these finding kinds."""
    assert result.exit_code != 0, result.output
    assert result.kinds() == set(kinds), result.output
    assert f"{len(result.findings())} finding(s)." in result.output


# --------------------------------------------------------- end-to-end runs


def test_plain_eval_validates(
    evalhost_env: MotoStore, tmp_path: Path, validate_cli: ValidateCli
) -> None:
    """One generate, no tools."""
    log = eval(
        Task(dataset=[Sample(input="hi", target="Default")], scorer=includes()),
        model="mockllm/model",
        log_dir=str(tmp_path),
        display="none",
        tamper_evident_store=evalhost_env.url,
    )[0]
    assert log.status == "success", log.error

    result = validate_cli(evalhost_env, tmp_path, "--verbose")
    assert result.exit_code == 0, result.output
    assert result.findings() == []
    assert result.output.endswith(
        "1 eval(s), 1 sample(s) compared, 0 finding(s).\n"
        "Checked against the add-only store: each sample's events and scores, "
        "which samples the .eval files have, and each eval's status, stats and "
        "results. Each sample summary is checked against its sample's scores.\n"
        "Not checked: everything else, including the eval spec and plan, each "
        "sample's messages, output and error, the sample summaries' other "
        "fields, invalidation and log_updates.\n"
        "A pass does not show that the run was honest.\n"
    ), result.output
    # --verbose lists the start record, the sample's records and both closings
    assert log.samples
    sample = sample_key_part(log.samples[0].id, 1)
    for key in ["start", f"{sample}/1/1", f"{sample}/1/closing", "closing"]:
        assert f"{evalhost_env.prefix}/{log.eval.eval_id}/{key}\n" in result.output


def test_eval_without_store_writes_nothing(
    evalhost_env: MotoStore, tmp_path: Path
) -> None:
    """Without tamper_evident_store, an eval writes nothing to the store."""
    log = run(agent_task(samples=1), tmp_path)
    assert log.status == "success", log.error
    listing = evalhost_env.client(evalhost_env.admin).list_object_versions(
        Bucket=BUCKET, Prefix=evalhost_env.prefix
    )
    assert "Versions" not in listing and "DeleteMarkers" not in listing


def test_agent_eval_validates(
    evalhost_env: MotoStore, tmp_path: Path, validate_cli: ValidateCli
) -> None:
    """An agent with tool calls and sub-agents; the paths ran."""
    log = run(agent_task(samples=1), tmp_path, tamper_evident_store=evalhost_env.url)
    assert log.status == "success", log.error
    assert log.samples
    tools = {e.function for e in log.samples[0].events if isinstance(e, ToolEvent)}
    assert tools == {"add", "researcher", "lookup", "note", "submit"}

    result = validate_cli(evalhost_env, tmp_path)
    assert result.exit_code == 0, result.output
    assert "1 eval(s), 1 sample(s) compared, 0 finding(s)." in result.output

    # the run exercised a pending event stored before it completed: the
    # sub-agent tool calls span the sub-agents' own boundaries
    records = _sample_records(evalhost_env, log.eval.eval_id)
    spans = _events_completed_in_later_record(records)
    assert any(kind == "tool" for kind, _, _ in spans), spans


def test_samples_at_once_validate(
    evalhost_env: MotoStore, tmp_path: Path, validate_cli: ValidateCli
) -> None:
    """3 samples x 2 epochs, all at once."""
    log = run(
        agent_task(epochs=2, samples=3),
        tmp_path,
        max_samples=6,
        tamper_evident_store=evalhost_env.url,
    )
    assert log.status == "success", log.error

    result = validate_cli(evalhost_env, tmp_path)
    assert result.exit_code == 0, result.output
    assert "1 eval(s), 6 sample(s) compared, 0 finding(s)." in result.output


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
            tamper_evident_store=evalhost_env.url,
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


@scorer(metrics=[mean()])
def nan_score() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        return Score(value=float("nan"))

    return score


@scorer(metrics=[mean()])
def one_score() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        return Score(value=1)

    return score


def numeric_score_run(store: MotoStore, log_dir: Path) -> EvalLog:
    log = eval(
        Task(dataset=[Sample(input="hi")], scorer=[nan_score(), one_score()]),
        model="mockllm/model",
        log_dir=str(log_dir),
        display="none",
        tamper_evident_store=store.url,
    )[0]
    assert log.status == "success", log.error
    return log


def test_nan_score_validates(
    evalhost_env: MotoStore, tmp_path: Path, validate_cli: ValidateCli
) -> None:
    """A NaN score and metric match the store (NaN equals NaN in JSON text)."""
    log = numeric_score_run(evalhost_env, tmp_path)
    assert log.results
    assert any(m.value != m.value for m in log.results.scores[0].metrics.values())

    result = validate_cli(evalhost_env, tmp_path)
    assert result.exit_code == 0, result.output
    assert result.findings() == []


@solver
def fail_attempts(failures: dict[str, int]) -> Solver:
    """Generate, then raise while ``failures`` has attempts left for the sample id."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        state = await generate(state)
        key = str(state.sample_id)
        if failures.get(key, 0) > 0:
            failures[key] -= 1
            raise RuntimeError("attempt fails")
        return state

    return solve


def test_retry_on_error_validates(
    evalhost_env: MotoStore, tmp_path: Path, validate_cli: ValidateCli
) -> None:
    """Attempt 1 errors and is retried: it has no closing record, so it is listed as stopped."""
    log = eval(
        Task(
            dataset=[Sample(id="s0", input="hi", target="Default")],
            solver=fail_attempts({"s0": 1}),
            scorer=includes(),
        ),
        model="mockllm/model",
        log_dir=str(tmp_path),
        display="none",
        retry_on_error=1,
        tamper_evident_store=evalhost_env.url,
    )[0]
    assert log.status == "success", log.error

    result = validate_cli(evalhost_env, tmp_path)
    assert result.exit_code == 0, result.output
    assert result.findings() == []
    assert result.stopped() == [f"{log.eval.eval_id}/s0.1/1"], result.output


@solver
def fail_attempts_in_file(path: str) -> Solver:
    """As `fail_attempts`, with the counts in a JSON file.

    A count is by sample id, or by `<sample-id>.<epoch>` for one epoch.
    eval_retry imports the task file again, so module state does not carry
    over to the retry; the file and its path (a task arg) do.

    An attempt fails only once s1 is logged in its epoch and each earlier one
    (the `failures` fixture's hook lists them in the file), so its error
    cannot cancel s1, whichever sample starts first.
    """

    def read() -> dict[str, Any]:
        return json.loads(Path(path).read_text())

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        state = await generate(state)
        failures = read()
        key = next(
            (
                k
                for k in [f"{state.sample_id}.{state.epoch}", str(state.sample_id)]
                if k in failures
            ),
            "",
        )
        if failures.get(key, 0) > 0:
            s1 = {f"s1.{epoch}" for epoch in range(1, state.epoch + 1)}
            with anyio.fail_after(30):
                while not s1 <= set(read().get("logged", [])):
                    await anyio.sleep(0.01)
            failures = read()
            failures[key] -= 1
            Path(path).write_text(json.dumps(failures))
            raise RuntimeError("attempt fails")
        return state

    return solve


@task
def retried_task(failures: str) -> Task:
    return Task(
        dataset=[
            Sample(id="s1", input="hi", target="Default"),
            Sample(id="s0", input="hi", target="Default"),
        ],
        solver=fail_attempts_in_file(failures),
        scorer=includes(),
    )


@pytest.fixture
def failures(tmp_path: Path) -> Iterator[Path]:
    """`retried_task`'s failures file, with a hook that lists each logged sample in it."""
    path = tmp_path / "failures.json"

    class ListLogged(Hooks):
        async def on_sample_end(self, data: SampleEnd) -> None:
            failures = json.loads(path.read_text())
            failures["logged"] = [
                *failures.get("logged", []),
                f"{data.sample.id}.{data.sample.epoch}",
            ]
            path.write_text(json.dumps(failures))

    hooks("list_logged", "Lists each logged sample in the failures file.")(ListLogged)
    yield path
    del _registry["hooks:list_logged"]


def retried_task_run(
    store: MotoStore, log_dir: Path, failures: Path, s0_failures: int
) -> EvalLog:
    """First eval of `retried_task`: s1 succeeds, then s0 fails and stops the eval."""
    failures.write_text(json.dumps({"s0": s0_failures}))
    log = eval(
        retried_task(str(failures)),
        model="mockllm/model",
        log_dir=str(log_dir),
        display="none",
        max_samples=2,
        tamper_evident_store=store.url,
    )[0]
    assert log.status == "error"
    return log


def test_eval_retry_validates(
    evalhost_env: MotoStore,
    tmp_path: Path,
    validate_cli: ValidateCli,
    failures: Path,
) -> None:
    """eval_retry twice: s0 fails twice, s1 is reused from the first eval each time.

    s1 has no records under either retry. Each retry's start record names
    the eval it reused samples from; the second retry's names the first
    retry, whose own names the first eval, where the records are.
    """
    log = retried_task_run(evalhost_env, tmp_path, failures, s0_failures=2)
    assert logged_samples(evalhost_env, log.eval.eval_id) == ["s0.1", "s1.1"]
    for status in ["error", "success"]:
        log = eval_retry(
            log,
            log_dir=str(tmp_path),
            display="none",
            tamper_evident_store=evalhost_env.url,
        )[0]
        assert log.status == status, log.error
        assert logged_samples(evalhost_env, log.eval.eval_id) == ["s0.1", "s1.1"]

    result = validate_cli(evalhost_env, tmp_path)
    assert result.exit_code == 0, result.output
    assert result.findings() == []
    assert "3 eval(s), 6 sample(s) compared, 0 finding(s)." in result.output


@solver
def fail_while_s0_closes(path: str) -> Solver:
    """While the file holds true, s1 raises once s0 starts the put the test gates.

    s2 waits until the eval's failure cancels it; s1 raises only once s2 waits.
    """

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        state = await generate(state)
        if json.loads(Path(path).read_text()):
            if state.sample_id == "s1":
                assert await anyio.to_thread.run_sync(
                    cancel_gates["s0_closing"].wait, 30
                )
                assert await anyio.to_thread.run_sync(
                    cancel_gates["s2_waiting"].wait, 30
                )
                raise RuntimeError("attempt fails")
            if state.sample_id == "s2":
                try:
                    cancel_gates["s2_waiting"].set()
                    await anyio.sleep_forever()
                finally:
                    cancel_gates["cancelled"].set()
        return state

    return solve


@task
def cancel_in_close_task(fail: str) -> Task:
    return Task(
        dataset=[Sample(id=f"s{i}", input="hi", target="Default") for i in range(3)],
        solver=fail_while_s0_closes(fail),
        scorer=includes(),
    )


@pytest.mark.parametrize("gated", ["2", CLOSING])
def test_eval_retry_after_cancel_in_close_validates(
    evalhost_env: MotoStore,
    tmp_path: Path,
    validate_cli: ValidateCli,
    monkeypatch: pytest.MonkeyPatch,
    gated: str,
) -> None:
    """s1 fails while s0, scored, writes its last record or its closing record.

    That put finishes only after the eval's failure has cancelled s2, so the
    cancellation reaches s0 after it, as when S3 is slow: before s0's closing
    record, or before s0 is logged. It still cancels s0's sample end hook,
    once s0 is logged. Then eval_retry.
    """
    monkeypatch.setitem(cancel_gates, "s0_closing", threading.Event())
    monkeypatch.setitem(cancel_gates, "s2_waiting", threading.Event())
    monkeypatch.setitem(cancel_gates, "cancelled", threading.Event())
    monkeypatch.setitem(cancel_gates, "s0_hook", threading.Event())
    monkeypatch.setitem(cancel_gates, "hook_timed_out", threading.Event())
    put = AddOnlyStore._put

    def gated_put(self: AddOnlyStore, key: str, body: bytes) -> None:
        if key.endswith(f"/s0.1/1/{gated}"):
            cancel_gates["s0_closing"].set()
            assert cancel_gates["cancelled"].wait(timeout=30)
        put(self, key, body)

    monkeypatch.setattr(AddOnlyStore, "_put", gated_put)
    fail = tmp_path / "fail.json"
    fail.write_text("true")
    hooks("stuck_sample_end", "Waits in s0's sample end hook.")(StuckSampleEndHook)
    try:
        log = eval(
            cancel_in_close_task(str(fail)),
            model="mockllm/model",
            log_dir=str(tmp_path),
            display="none",
            max_samples=3,
            tamper_evident_store=evalhost_env.url,
        )[0]
    finally:
        del _registry["hooks:stuck_sample_end"]
    assert log.status == "error"
    assert not cancel_gates["hook_timed_out"].is_set()

    fail.write_text("false")
    log = eval_retry(
        log,
        log_dir=str(tmp_path),
        display="none",
        tamper_evident_store=evalhost_env.url,
    )[0]
    assert log.status == "success", log.error

    result = validate_cli(evalhost_env, tmp_path)
    assert result.exit_code == 0, result.output
    assert result.findings() == []
    assert "2 eval(s), 6 sample(s) compared, 0 finding(s)." in result.output


@solver
def fail_while_s0_hook_waits(path: str) -> Solver:
    """While the file holds true, s1 raises once s0's sample end hook starts."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        state = await generate(state)
        if json.loads(Path(path).read_text()) and state.sample_id == "s1":
            assert await anyio.to_thread.run_sync(cancel_gates["s0_hook"].wait, 30)
            raise RuntimeError("attempt fails")
        return state

    return solve


class StuckSampleEndHook(Hooks):
    """s0's sample end hook waits on an event that is never set, for up to 30 s."""

    async def on_sample_end(self, data: SampleEnd) -> None:
        if data.sample.id == "s0":
            cancel_gates["s0_hook"].set()
            with anyio.move_on_after(30):
                await anyio.Event().wait()
            cancel_gates["hook_timed_out"].set()


@task
def stuck_hook_task(fail: str) -> Task:
    return Task(
        dataset=[Sample(id=f"s{i}", input="hi", target="Default") for i in range(2)],
        solver=fail_while_s0_hook_waits(fail),
        scorer=includes(),
    )


def test_eval_retry_after_cancel_in_sample_end_hook_validates(
    evalhost_env: MotoStore,
    tmp_path: Path,
    validate_cli: ValidateCli,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """s1 fails while s0, scored and logged, waits in its sample end hook.

    The eval's failure cancels the hook, as without the store. Then eval_retry.
    """
    monkeypatch.setitem(cancel_gates, "s0_hook", threading.Event())
    monkeypatch.setitem(cancel_gates, "hook_timed_out", threading.Event())
    fail = tmp_path / "fail.json"
    fail.write_text("true")
    hooks("stuck_sample_end", "Waits in s0's sample end hook.")(StuckSampleEndHook)
    try:
        log = eval(
            stuck_hook_task(str(fail)),
            model="mockllm/model",
            log_dir=str(tmp_path),
            display="none",
            max_samples=2,
            tamper_evident_store=evalhost_env.url,
        )[0]
    finally:
        del _registry["hooks:stuck_sample_end"]
    assert log.status == "error"
    assert not cancel_gates["hook_timed_out"].is_set()

    fail.write_text("false")
    log = eval_retry(
        log,
        log_dir=str(tmp_path),
        display="none",
        tamper_evident_store=evalhost_env.url,
    )[0]
    assert log.status == "success", log.error

    result = validate_cli(evalhost_env, tmp_path)
    assert result.exit_code == 0, result.output
    assert result.findings() == []
    assert "2 eval(s), 4 sample(s) compared, 0 finding(s)." in result.output


class StuckScoreEventHook(Hooks):
    """The sample event hook waits at the first score event (s0's), for up to 4 s.

    Less than the 5 s the sample end waits for the hook before it goes on.
    """

    async def on_sample_event(self, data: SampleEvent) -> None:
        if isinstance(data.event, ScoreEvent) and not cancel_gates["s0_hook"].is_set():
            cancel_gates["s0_hook"].set()
            with anyio.move_on_after(4):
                await anyio.Event().wait()
            cancel_gates["hook_timed_out"].set()


def test_eval_retry_after_cancel_in_sample_event_hook_validates(
    evalhost_env: MotoStore,
    tmp_path: Path,
    validate_cli: ValidateCli,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """s1 fails while s0, scored, waits for its sample event hook.

    The eval's failure cancels the hook, as without the store. s0 stops
    before its closing record. Then eval_retry.
    """
    monkeypatch.setitem(cancel_gates, "s0_hook", threading.Event())
    monkeypatch.setitem(cancel_gates, "hook_timed_out", threading.Event())
    fail = tmp_path / "fail.json"
    fail.write_text("true")
    hooks("stuck_score_event", "Waits at s0's score event.")(StuckScoreEventHook)
    try:
        log = eval(
            stuck_hook_task(str(fail)),
            model="mockllm/model",
            log_dir=str(tmp_path),
            display="none",
            max_samples=2,
            tamper_evident_store=evalhost_env.url,
        )[0]
    finally:
        del _registry["hooks:stuck_score_event"]
    assert log.status == "error"
    assert not cancel_gates["hook_timed_out"].is_set()

    fail.write_text("false")
    log = eval_retry(
        log,
        log_dir=str(tmp_path),
        display="none",
        tamper_evident_store=evalhost_env.url,
    )[0]
    assert log.status == "success", log.error

    result = validate_cli(evalhost_env, tmp_path)
    assert result.exit_code == 0, result.output
    assert result.findings() == []


class ModelCallSampleEndHook(Hooks):
    async def on_sample_end(self, data: SampleEnd) -> None:
        await get_model("mockllm/model").generate("Summarize the sample.")


def test_model_call_in_sample_end_hook_validates(
    evalhost_env: MotoStore, tmp_path: Path, validate_cli: ValidateCli
) -> None:
    """A sample end hook calls a model after the sample closing record."""
    hooks("model_call_sample_end", "Calls a model.")(ModelCallSampleEndHook)
    try:
        log = eval(
            Task(
                dataset=[Sample(id="s0", input="hi", target="Default")],
                scorer=includes(),
            ),
            model="mockllm/model",
            log_dir=str(tmp_path),
            display="none",
            tamper_evident_store=evalhost_env.url,
        )[0]
    finally:
        del _registry["hooks:model_call_sample_end"]
    assert log.status == "success", log.error

    result = validate_cli(evalhost_env, tmp_path)
    assert result.exit_code == 0, result.output
    assert result.findings() == []


@solver
def boundary_after_cancel(path: str, first: bool) -> Solver:
    """While the file holds true, s0 writes at a boundary with a cancel pending.

    s0 waits in a worker thread until the eval's failure (s1) has cancelled
    s2 (s1 raises only once s2 waits), then writes before (`first`) or after
    its generate. The cancel reaches s0 at its next checkpoint, which is in
    that write.
    """

    async def s0_boundary_after_cancel() -> None:
        cancel_gates["s0_waiting"].set()
        assert await anyio.to_thread.run_sync(cancel_gates["cancelled"].wait, 30)
        await store_boundary()

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        failing = json.loads(Path(path).read_text())
        if failing and first and state.sample_id == "s0":
            await s0_boundary_after_cancel()
        state = await generate(state)
        if failing:
            if state.sample_id == "s0":
                await s0_boundary_after_cancel()
            if state.sample_id == "s1":
                assert await anyio.to_thread.run_sync(
                    cancel_gates["s0_waiting"].wait, 30
                )
                assert await anyio.to_thread.run_sync(
                    cancel_gates["s2_waiting"].wait, 30
                )
                raise RuntimeError("attempt fails")
            if state.sample_id == "s2":
                try:
                    cancel_gates["s2_waiting"].set()
                    await anyio.sleep_forever()
                finally:
                    cancel_gates["cancelled"].set()
        return state

    return solve


@task
def boundary_after_cancel_task(fail: str, first: bool) -> Task:
    return Task(
        dataset=[Sample(id=f"s{i}", input="hi", target="Default") for i in range(3)],
        solver=boundary_after_cancel(fail, first),
        scorer=includes(),
    )


@pytest.mark.parametrize("first", [True, False])
def test_eval_retry_after_cancel_at_boundary_validates(
    evalhost_env: MotoStore,
    tmp_path: Path,
    validate_cli: ValidateCli,
    monkeypatch: pytest.MonkeyPatch,
    first: bool,
) -> None:
    """s1 fails, and s0 starts its first or a later record with the cancel pending.

    The record is still written, so s0, cancelled, writes its closing record.
    Then eval_retry.
    """
    monkeypatch.setitem(cancel_gates, "s0_waiting", threading.Event())
    monkeypatch.setitem(cancel_gates, "s2_waiting", threading.Event())
    monkeypatch.setitem(cancel_gates, "cancelled", threading.Event())
    fail = tmp_path / "fail.json"
    fail.write_text("true")
    log = eval(
        boundary_after_cancel_task(str(fail), first),
        model="mockllm/model",
        log_dir=str(tmp_path),
        display="none",
        max_samples=3,
        tamper_evident_store=evalhost_env.url,
    )[0]
    assert log.status == "error"
    assert log.error and "attempt fails" in log.error.message, log.error

    fail.write_text("false")
    log = eval_retry(
        log,
        log_dir=str(tmp_path),
        display="none",
        tamper_evident_store=evalhost_env.url,
    )[0]
    assert log.status == "success", log.error

    result = validate_cli(evalhost_env, tmp_path)
    assert result.exit_code == 0, result.output
    assert result.findings() == []
    assert "2 eval(s), 6 sample(s) compared, 0 finding(s)." in result.output


class StuckScoringHook(Hooks):
    """The first sample scoring hook (s0's: s1 waits for it) waits as `StuckSampleEndHook` does."""

    async def on_sample_scoring(self, data: SampleScoring) -> None:
        if not cancel_gates["s0_hook"].is_set():
            cancel_gates["s0_hook"].set()
            with anyio.move_on_after(30):
                await anyio.Event().wait()
            cancel_gates["hook_timed_out"].set()


class StuckInitHook(Hooks):
    """s0's sample init hook, before its first record, waits as `StuckSampleEndHook` does."""

    async def on_sample_init(self, data: SampleInit) -> None:
        if data.summary.id == "s0":
            cancel_gates["s0_hook"].set()
            with anyio.move_on_after(30):
                await anyio.Event().wait()
            cancel_gates["hook_timed_out"].set()


class StuckRetryHook(Hooks):
    """s0's attempt end hook before its retry waits as `StuckSampleEndHook` does."""

    async def on_sample_attempt_end(self, data: SampleAttemptEnd) -> None:
        if data.summary.id == "s0" and data.will_retry:
            cancel_gates["s0_hook"].set()
            with anyio.move_on_after(30):
                await anyio.Event().wait()
            cancel_gates["hook_timed_out"].set()


@solver
def fail_once_s0_hook_waits(s0_fails: bool) -> Solver:
    """s1 raises once s0 waits in a hook. With ``s0_fails``, s0 raises too."""

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        state = await generate(state)
        if state.sample_id == "s1":
            assert await anyio.to_thread.run_sync(cancel_gates["s0_hook"].wait, 30)
            raise RuntimeError("attempt fails")
        if s0_fails:
            raise RuntimeError("attempt fails")
        return state

    return solve


@pytest.mark.parametrize("hook", ["init", "scoring", "attempt_end"])
def test_eval_stopped_while_hook_waits_lists_stopped(
    evalhost_env: MotoStore,
    tmp_path: Path,
    validate_cli: ValidateCli,
    monkeypatch: pytest.MonkeyPatch,
    hook: str,
) -> None:
    """s1 fails the eval while s0 waits in a hook, before its closing record.

    In its sample init hook (s0 has no records), in its sample scoring hook,
    or (with retry_on_error) in its attempt end hook before the retry. The
    eval's failure cancels the hook, so s0 is not logged, and its attempt is
    listed as stopped.
    """
    monkeypatch.setitem(cancel_gates, "s0_hook", threading.Event())
    monkeypatch.setitem(cancel_gates, "hook_timed_out", threading.Event())
    hooks("stuck_hook", "Waits in a hook of s0.")(
        {
            "init": StuckInitHook,
            "scoring": StuckScoringHook,
            "attempt_end": StuckRetryHook,
        }[hook]
    )
    try:
        log = eval(
            Task(
                dataset=[
                    Sample(id=f"s{i}", input="hi", target="Default") for i in range(2)
                ],
                solver=fail_once_s0_hook_waits(s0_fails=hook == "attempt_end"),
                scorer=includes(),
            ),
            model="mockllm/model",
            log_dir=str(tmp_path),
            display="none",
            max_samples=2,
            retry_on_error=1 if hook == "attempt_end" else None,
            tamper_evident_store=evalhost_env.url,
        )[0]
    finally:
        del _registry["hooks:stuck_hook"]
    assert log.status == "error"
    assert not cancel_gates["hook_timed_out"].is_set()
    assert [s.id for s in log.samples or []] == ["s1"]

    result = validate_cli(evalhost_env, tmp_path)
    assert result.exit_code == 0, result.output
    assert result.findings() == []
    # with retry_on_error, s1's first attempt is stopped too (its retry closed)
    assert result.stopped() == [
        f"{log.eval.eval_id}/s{i}.1/1"
        for i in ([0, 1] if hook == "attempt_end" else [0])
    ], result.output


@solver
def fail_then_once_s0_hook_waits(phase: str) -> Solver:
    """While the file holds "first", each sample raises; then as `fail_once_s0_hook_waits`."""
    then = fail_once_s0_hook_waits(s0_fails=False)

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        if Path(phase).read_text() == "first":
            await generate(state)
            raise RuntimeError("attempt fails")
        return await then(state, generate)

    return solve


@task
def stopped_retry_task(phase: str) -> Task:
    return Task(
        dataset=[Sample(id=f"s{i}", input="hi", target="Default") for i in range(2)],
        solver=fail_then_once_s0_hook_waits(phase),
        scorer=includes(),
    )


@pytest.mark.parametrize("retries", [1, 2])
@pytest.mark.parametrize("hook", ["init", "scoring"])
def test_retry_stopped_while_hook_waits_validates(
    evalhost_env: MotoStore,
    tmp_path: Path,
    validate_cli: ValidateCli,
    monkeypatch: pytest.MonkeyPatch,
    hook: str,
    retries: int,
) -> None:
    """eval_retry of an eval that closed s0 and s1 with errors stops while s0 waits.

    s1 fails the retry while s0 waits in its sample init hook (no records)
    or its sample scoring hook; with two retries, the second retries the
    first and stops the same way. Each retry's .eval keeps the first eval's
    copy of s0, which is compared with the first eval's records, and each
    retry's s0 attempt is listed as stopped. That copy, deleted, is
    `missing_sample`: the retry's eval closing record lists it.
    """
    phase = tmp_path / "phase"
    phase.write_text("first")
    log_dir = tmp_path / "logs"
    log = eval(
        stopped_retry_task(str(phase)),
        model="mockllm/model",
        log_dir=str(log_dir),
        display="none",
        max_samples=2,
        fail_on_error=False,
        tamper_evident_store=evalhost_env.url,
    )[0]
    assert [bool(s.error) for s in log.samples or []] == [True, True]
    s0_uuid = next(s.uuid for s in log.samples or [] if s.id == "s0")

    phase.write_text("retry")
    retry_ids: list[str] = []
    for _ in range(retries):
        monkeypatch.setitem(cancel_gates, "s0_hook", threading.Event())
        monkeypatch.setitem(cancel_gates, "hook_timed_out", threading.Event())
        hooks("stuck_hook", "Waits in a hook of s0.")(
            {"init": StuckInitHook, "scoring": StuckScoringHook}[hook]
        )
        try:
            log = eval_retry(
                log,
                log_dir=str(log_dir),
                display="none",
                fail_on_error=True,
                tamper_evident_store=evalhost_env.url,
            )[0]
        finally:
            del _registry["hooks:stuck_hook"]
        assert log.status == "error"
        assert log.error and "attempt fails" in log.error.message, log.error
        assert not cancel_gates["hook_timed_out"].is_set()
        logged = read_eval_log(log.location).samples or []
        assert {str(s.id): s.uuid for s in logged}["s0"] == s0_uuid
        retry_ids.append(log.eval.eval_id)

    result = validate_cli(evalhost_env, log_dir)
    assert result.exit_code == 0, result.output
    assert result.findings() == []
    assert sorted(result.stopped()) == sorted(
        f"{eval_id}/s0.1/1" for eval_id in retry_ids
    ), result.output
    assert (
        f"{retries + 1} eval(s), {2 * retries + 2} sample(s) compared, 0 finding(s)."
        in result.output
    )

    # the retry copied the errored s0 and stopped before it ran it again:
    # deleting that copy from the retry's .eval is a finding
    assert logged_samples(evalhost_env, retry_ids[-1]) == ["s0.1", "s1.1"]
    retry = read_eval_log(log.location)
    retry.samples = [s for s in retry.samples or [] if s.id != "s0"]
    write_eval_log(retry, retry.location)
    result = validate_cli(evalhost_env, log_dir)
    assert_fails_with(result, "missing_sample")
    assert f"missing_sample {retry_ids[-1]}/s0.1:" in result.output


def test_eval_stopped_while_retry_waits_lists_stopped(
    evalhost_env: MotoStore, tmp_path: Path, validate_cli: ValidateCli
) -> None:
    """The eval fails while a retry waits for a free sample slot.

    One slot, every attempt fails, and a retry goes to the back of the queue.
    The first retry fails the eval. The second retry takes the slot and is
    cancelled. The third retry never starts, so its sample is not logged.
    Each first attempt is listed as stopped.
    """
    samples = [f"s{i}" for i in range(3)]
    log = eval(
        Task(
            dataset=[Sample(id=id, input="hi", target="Default") for id in samples],
            solver=fail_attempts({id: 2 for id in samples}),
            scorer=includes(),
        ),
        model="mockllm/model",
        log_dir=str(tmp_path),
        display="none",
        max_samples=1,
        retry_on_error=1,
        tamper_evident_store=evalhost_env.url,
    )[0]
    assert log.status == "error"
    assert len(log.samples or []) == 2

    result = validate_cli(evalhost_env, tmp_path)
    assert result.exit_code == 0, result.output
    assert result.findings() == []
    assert result.stopped() == [f"{log.eval.eval_id}/{id}.1/1" for id in samples], (
        result.output
    )


CRASH_PROGRAM = """
import os
import sys

from inspect_ai import Task, eval
from inspect_ai._eval.task.log import TaskLogger
from inspect_ai.dataset import Sample
from inspect_ai.scorer import includes
from inspect_ai.solver import solver

log_dir, store, crash = sys.argv[1:]

if crash == "before_first_flush":
    start_addonly = TaskLogger._start_addonly

    async def exit_after_start(self, *args, **kwargs):
        await start_addonly(self, *args, **kwargs)
        os._exit(17)

    TaskLogger._start_addonly = exit_after_start


started = []


@solver
def exit_in_second_sample():
    async def solve(state, generate):
        started.append(state.sample_id)
        if len(started) == 2:
            os._exit(17)
        return await generate(state)

    return solve


eval(
    Task(
        dataset=[Sample(id=f"s{i}", input="hi", target="Default") for i in range(6)],
        solver=exit_in_second_sample(),
        scorer=includes(),
    ),
    model="mockllm/model",
    log_dir=log_dir,
    display="none",
    max_samples=1,
    tamper_evident_store=store,
)
"""
"""An eval whose process exits partway (the `crash` argument says where)."""


@pytest.mark.parametrize("crash", ["before_first_flush", "sample_not_logged"])
def test_eval_host_crash_lists_stopped(
    evalhost_env: MotoStore, tmp_path: Path, validate_cli: ValidateCli, crash: str
) -> None:
    """The eval's process exits partway, as when its host dies.

    After the start record and before the first .eval file write: there is
    no .eval file, and the eval is listed as stopped. Or in the second
    sample, after the first closed: the log buffer (default size: 2 samples
    for 6) still holds the first, so the .eval file is "started" with no
    samples, and the first is listed as not logged.
    """
    exited = subprocess.run(
        [sys.executable, "-c", CRASH_PROGRAM, str(tmp_path), evalhost_env.url, crash],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert exited.returncode == 17, exited.stderr
    eval_files = list(tmp_path.glob("*.eval"))
    if crash == "before_first_flush":
        assert eval_files == []
    else:
        (eval_file,) = eval_files
        log = read_eval_log(eval_file)
        assert log.status == "started" and not log.samples

    (eval_id,) = validate(evalhost_env, tmp_path).evals
    result = validate_cli(evalhost_env, tmp_path)
    assert result.exit_code == 0, result.output
    assert result.findings() == []
    assert result.stopped() == [eval_id], result.output
    not_logged = result.not_logged()
    assert len(not_logged) == (0 if crash == "before_first_flush" else 1)
    assert all(key.startswith(f"{eval_id}/") for key in not_logged), result.output
    assert "1 eval(s), 0 sample(s) compared, 0 finding(s)." in result.output


def test_eval_host_crash_eval_file_deleted(
    evalhost_env: MotoStore, tmp_path: Path, validate_cli: ValidateCli
) -> None:
    """The eval's process exits after a sample closed, and its .eval file is deleted.

    An honest eval writes its first .eval file before any sample runs, so an
    eval with a closed attempt and no .eval file is a finding.
    """
    exited = subprocess.run(
        [
            sys.executable,
            "-c",
            CRASH_PROGRAM,
            str(tmp_path),
            evalhost_env.url,
            "sample_not_logged",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert exited.returncode == 17, exited.stderr
    (eval_file,) = tmp_path.glob("*.eval")
    eval_file.unlink()

    (eval_id,) = validate(evalhost_env, tmp_path).evals
    result = validate_cli(evalhost_env, tmp_path)
    assert_fails_with(result, "missing_eval_file")
    assert f"missing_eval_file {eval_id}:" in result.output
    assert result.stopped() == [eval_id], result.output


def test_task_retry_attempts_validates(
    evalhost_env: MotoStore,
    tmp_path: Path,
    validate_cli: ValidateCli,
    failures: Path,
) -> None:
    """task_retry_attempts: the second eval reuses s1 from the first."""
    failures.write_text(json.dumps({"s0": 1}))
    log_dir = tmp_path / "logs"
    log = eval(
        retried_task(str(failures)),
        model="mockllm/model",
        log_dir=str(log_dir),
        display="none",
        max_samples=2,
        task_retry_attempts=1,
        tamper_evident_store=evalhost_env.url,
    )[0]
    assert log.status == "success", log.error
    assert logged_samples(evalhost_env, log.eval.eval_id) == ["s0.1", "s1.1"]

    result = validate_cli(evalhost_env, log_dir)
    assert result.exit_code == 0, result.output
    assert "2 eval(s), 4 sample(s) compared, 0 finding(s)." in result.output


@pytest.mark.parametrize("retry_cleanup", [True, False])
def test_eval_set_retry_validates(
    evalhost_env: MotoStore,
    tmp_path: Path,
    validate_cli: ValidateCli,
    failures: Path,
    retry_cleanup: bool,
) -> None:
    """eval_set retry: the second eval reuses s1 from the first.

    retry_cleanup (the default) deletes the failed attempt's .eval file. The
    second eval's start record names the first eval, so the missing file is
    not a finding, and s1 is still compared with the first eval's records.
    """
    failures.write_text(json.dumps({"s0": 1}))
    log_dir = tmp_path / "logs"
    success, logs = eval_set(
        retried_task(str(failures)),
        log_dir=str(log_dir),
        model="mockllm/model",
        display="none",
        max_samples=2,
        retry_attempts=1,
        retry_cleanup=retry_cleanup,
        tamper_evident_store=evalhost_env.url,
    )
    assert success, logs[0].error
    assert len(list(log_dir.glob("*.eval"))) == (1 if retry_cleanup else 2)
    assert logged_samples(evalhost_env, logs[0].eval.eval_id) == ["s0.1", "s1.1"]

    result = validate_cli(evalhost_env, log_dir)
    assert result.exit_code == 0, result.output
    compared = 2 if retry_cleanup else 4
    assert f"2 eval(s), {compared} sample(s) compared, 0 finding(s)." in result.output
    assert ("prior_without_file " in result.output) == retry_cleanup


@pytest.mark.parametrize(
    "first,retry",
    [({}, {"sample_id": ["s0"]}), ({"epochs": 2}, {"epochs": 1})],
    ids=["sample_id", "epochs"],
)
def test_eval_set_narrower_retry_validates(
    evalhost_env: MotoStore,
    tmp_path: Path,
    validate_cli: ValidateCli,
    failures: Path,
    first: dict[str, Any],
    retry: dict[str, Any],
) -> None:
    """A later eval_set retries the failed eval with fewer samples or epochs.

    The retry copies only the samples it selects into its .eval, so the
    samples it does not select are not missing.
    """
    failures.write_text(json.dumps({"s0" if "sample_id" in retry else "s0.2": 1}))
    log_dir = tmp_path / "logs"
    options: dict[str, Any] = dict(
        log_dir=str(log_dir),
        model="mockllm/model",
        display="none",
        max_samples=2,
        retry_attempts=0,
        tamper_evident_store=evalhost_env.url,
    )
    success, logs = eval_set(retried_task(str(failures)), **first, **options)
    assert not success
    # the first eval closed s1 without an error in every epoch
    first_samples = read_eval_log(logs[0].location).samples or []
    assert {(s.id, s.epoch) for s in first_samples if s.error is None} >= {
        ("s1", epoch) for epoch in range(1, first.get("epochs", 1) + 1)
    }
    success, logs = eval_set(retried_task(str(failures)), **retry, **options)
    assert success, logs[0].error
    assert logged_samples(evalhost_env, logs[0].eval.eval_id) == (
        ["s0.1"] if "sample_id" in retry else ["s0.1", "s1.1"]
    )

    result = validate_cli(evalhost_env, log_dir)
    assert result.exit_code == 0, result.output
    assert result.findings() == []


def test_add_prior_sample_to_narrower_retry(
    evalhost_env: MotoStore,
    tmp_path: Path,
    validate_cli: ValidateCli,
    failures: Path,
) -> None:
    """The earlier eval's s1 added to a retry that selected only s0.

    s1 matches the earlier eval's records, but the retry's eval closing
    record does not list it.
    """
    failures.write_text(json.dumps({"s0": 1}))
    log_dir = tmp_path / "logs"
    options: dict[str, Any] = dict(
        log_dir=str(log_dir),
        model="mockllm/model",
        display="none",
        max_samples=2,
        retry_attempts=0,
        retry_cleanup=False,
        tamper_evident_store=evalhost_env.url,
    )
    success, logs = eval_set(retried_task(str(failures)), **options)
    assert not success
    first = read_eval_log(logs[0].location)
    success, logs = eval_set(retried_task(str(failures)), sample_id=["s0"], **options)
    assert success, logs[0].error
    retry = read_eval_log(logs[0].location)
    assert retry.samples
    retry.samples.append(next(s for s in first.samples or [] if s.id == "s1"))
    write_eval_log(retry, retry.location)

    result = validate_cli(evalhost_env, log_dir)
    assert_fails_with(result, "unstored_sample")
    assert f"unstored_sample {retry.eval.eval_id}/s1.1:" in result.output
    assert "eval closing record" in result.output


def limited_feed_task(failing: dict[str, bool]) -> Task:
    """A dynamic feed of samples 1-3; sample 3 fails while ``failing["3"]``."""

    class Feed(SampleSource):
        def __init__(self) -> None:
            self.next_id = 2

        def initial_samples(self) -> list[Sample]:
            return [Sample(id=1, input="q", target="Default")]

        async def next_samples(self) -> list[Sample] | None:
            if self.next_id > 3:
                return None
            self.next_id += 1
            return [Sample(id=self.next_id - 1, input="q", target="Default")]

    @solver
    def fail_3() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            if state.sample_id == 3 and failing["3"]:
                raise RuntimeError("first run fails")
            return await generate(state)

        return solve

    @task
    def limited_feed() -> Task:
        return Task(dataset=Feed(), solver=fail_3(), scorer=includes())

    return limited_feed()


def failed_limited_feed(store: MotoStore, log_dir: Path) -> dict[str, Any]:
    """Runs a limited feed whose sample 3 fails; returns eval_set options to retry it."""
    options: dict[str, Any] = dict(
        log_dir=str(log_dir),
        model="mockllm/model",
        display="none",
        max_samples=1,
        retry_attempts=0,
        retry_on_error=0,
        tamper_evident_store=store.url,
    )
    success, _ = eval_set(limited_feed_task({"3": True}), **options)
    assert not success
    return options


@pytest.mark.parametrize("limit", [2, 3])
def test_eval_set_limited_feed_retry_validates(
    evalhost_env: MotoStore, tmp_path: Path, limit: int
) -> None:
    """A limited dynamic feed's retry lists the samples it admitted.

    With limit 3, sample 3 is copied with its error, then runs again.
    """
    options = failed_limited_feed(evalhost_env, tmp_path)
    success, logs = eval_set(limited_feed_task({"3": False}), limit=limit, **options)
    assert success, logs[0].error
    assert logged_samples(evalhost_env, logs[0].eval.eval_id) == [
        f"{id}.1" for id in range(1, limit + 1)
    ]
    assert validate(evalhost_env, tmp_path).findings == []


@pytest.mark.parametrize("interrupt", ["error", "cancel"])
def test_eval_set_limited_feed_retry_interrupted_copy_validates(
    evalhost_env: MotoStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    interrupt: str,
) -> None:
    """A limited feed's retry stops while copying admitted sample 2 into its .eval.

    The copy fails (disk full) or a task cancel lands in it. The .eval does
    not have sample 2, so the eval closing record does not list it.
    """
    options = failed_limited_feed(evalhost_env, tmp_path)
    log_sample = EvalRecorder.log_sample

    async def interrupt_copy(
        self: EvalRecorder,
        eval: EvalSpec,
        sample: EvalSample,
        *,
        write_through: bool = False,
    ) -> None:
        if write_through and sample.id == 2:
            if interrupt == "cancel":
                receipt = cancel_task(get_eval_states()[0].task_id, action="cancel")
                assert receipt is not None and receipt["ok"]
                with anyio.fail_after(30):
                    await anyio.sleep_forever()
            raise OSError("disk full")
        await log_sample(self, eval, sample, write_through=write_through)

    monkeypatch.setattr(EvalRecorder, "log_sample", interrupt_copy)
    success, logs = eval_set(limited_feed_task({"3": False}), limit=2, **options)
    assert not success
    assert logs[0].status == "error" and logs[0].error
    assert ("cancelled by user" in logs[0].error.message) == (interrupt == "cancel")
    final = read_eval_log(logs[0].location)
    assert [s.id for s in final.samples or []] == [1]
    assert logged_samples(evalhost_env, final.eval.eval_id) == ["1.1"]
    assert validate(evalhost_env, tmp_path).findings == []


def shrinking_feed_task(failing: dict[str, bool]) -> Task:
    """Sample 1 adds samples 2 and 3 on its first completion, then only 2."""
    completions = 0

    class Feed(SampleSource):
        def initial_samples(self) -> list[Sample]:
            return [Sample(id=1, input="q", target="Default")]

        async def sample_complete(self, sample: EvalSample) -> list[Sample] | None:
            nonlocal completions
            if sample.id != 1:
                return None
            completions += 1
            ids = [2, 3] if completions == 1 else [2]
            return [Sample(id=id, input="q", target="Default") for id in ids]

    @solver
    def fail_3() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            if state.sample_id == 3 and failing["3"]:
                failing["3"] = False
                raise RuntimeError("first run fails")
            return await generate(state)

        return solve

    @task
    def shrinking_feed() -> Task:
        return Task(dataset=Feed(), solver=fail_3(), scorer=includes())

    return shrinking_feed()


@pytest.mark.parametrize("retry_cleanup", [True, False])
def test_eval_set_retry_pruned_sample_not_copied(
    evalhost_env: MotoStore, tmp_path: Path, retry_cleanup: bool
) -> None:
    """A dynamic feed's retry drops prior sample 3, which it did not produce again.

    The eval closing record lists only the samples its .eval keeps.
    """
    success, logs = eval_set(
        shrinking_feed_task({"3": True}),
        log_dir=str(tmp_path),
        model="mockllm/model",
        display="none",
        max_samples=1,
        retry_attempts=1,
        retry_on_error=0,
        retry_cleanup=retry_cleanup,
        tamper_evident_store=evalhost_env.url,
    )
    assert success, logs[0].error
    final = read_eval_log(logs[0].location)
    assert sorted(s.id for s in final.samples or []) == [1, 2]
    assert logged_samples(evalhost_env, final.eval.eval_id) == ["1.1", "2.1"]
    assert validate(evalhost_env, tmp_path).findings == []


def test_edit_reused_sample(
    evalhost_env: MotoStore,
    tmp_path: Path,
    validate_cli: ValidateCli,
    failures: Path,
) -> None:
    """A retry's reused sample edited: compared with the earlier eval's records."""
    log = retried_task_run(evalhost_env, tmp_path, failures, s0_failures=1)
    retry = eval_retry(
        log,
        log_dir=str(tmp_path),
        display="none",
        tamper_evident_store=evalhost_env.url,
    )[0]
    assert retry.status == "success", retry.error
    assert validate(evalhost_env, tmp_path).findings == []

    retry = read_eval_log(retry.location)
    assert retry.samples
    sample = next(s for s in retry.samples if s.id == "s1")
    score_event = next(e for e in sample.events if isinstance(e, ScoreEvent))
    score_event.score.value = "I"
    write_eval_log(retry, retry.location)

    result = validate_cli(evalhost_env, tmp_path)
    assert_fails_with(result, "event_mismatch")
    assert f"event_mismatch {retry.eval.eval_id}/s1.1:" in result.output
    assert f"reused from {log.eval.eval_id}" in result.output


def test_add_sample_to_retry(
    evalhost_env: MotoStore,
    tmp_path: Path,
    validate_cli: ValidateCli,
    failures: Path,
) -> None:
    """A sample added to a retry's .eval: no eval in the chain ran it."""
    log = retried_task_run(evalhost_env, tmp_path, failures, s0_failures=1)
    retry = eval_retry(
        log,
        log_dir=str(tmp_path),
        display="none",
        tamper_evident_store=evalhost_env.url,
    )[0]
    assert retry.status == "success", retry.error

    retry = read_eval_log(retry.location)
    assert retry.samples
    added = next(s for s in retry.samples if s.id == "s1").model_copy(
        update={"id": "s2"}
    )
    retry.samples.append(added)
    write_eval_log(retry, retry.location)

    result = validate_cli(evalhost_env, tmp_path)
    assert_fails_with(result, "unstored_sample")
    assert f"unstored_sample {retry.eval.eval_id}/s2.1:" in result.output
    assert f"prior eval {log.eval.eval_id}" in result.output


def test_delete_reused_sample(
    evalhost_env: MotoStore,
    tmp_path: Path,
    validate_cli: ValidateCli,
    failures: Path,
) -> None:
    """s1 deleted from a retry of a retry: the first eval closed it without an error."""
    log = retried_task_run(evalhost_env, tmp_path, failures, s0_failures=2)
    for status in ["error", "success"]:
        log = eval_retry(
            log,
            log_dir=str(tmp_path),
            display="none",
            tamper_evident_store=evalhost_env.url,
        )[0]
        assert log.status == status, log.error

    log = read_eval_log(log.location)
    assert log.samples
    log.samples = [s for s in log.samples if s.id != "s1"]
    write_eval_log(log, log.location)

    result = validate_cli(evalhost_env, tmp_path)
    assert_fails_with(result, "missing_sample")
    assert f"missing_sample {log.eval.eval_id}/s1.1:" in result.output


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


# -------------------------------------------------- tampering, .eval file
#
# Each test tampers with a clean run (`clean_run` validates it first), then
# runs `inspect validate` and checks it fails with the finding for that
# tamper. Anyone who can write the log directory can make these changes.


def test_edit_event(clean_run: CleanRun, validate_cli: ValidateCli) -> None:
    """A tool result changed with inspect's own log API."""

    def edit(sample: EvalSample) -> None:
        tool_event = next(e for e in sample.events if isinstance(e, ToolEvent))
        tool_event.result = "harmless"

    edit_sample(clean_run, edit)
    result = validate_cli(clean_run.store, clean_run.log_dir)
    assert_fails_with(result, "event_mismatch")
    assert "differs in ['result']" in result.output


def test_edit_event_in_zip(clean_run: CleanRun, validate_cli: ValidateCli) -> None:
    """The model's answer changed in the sample JSON inside the .eval zip."""

    def edit(sample: dict[str, Any]) -> dict[str, Any]:
        model = next(e for e in sample["events"] if e["event"] == "model")
        model["output"]["choices"][0]["message"]["content"] = "a different answer"
        return sample

    edit_zip_entry(clean_run.location, "samples/s0_epoch_1.json", edit)
    result = validate_cli(clean_run.store, clean_run.log_dir)
    assert_fails_with(result, "event_mismatch")
    assert "(model " in result.output and "differs in ['output']" in result.output


def test_edit_model_input_in_pool(
    clean_run: CleanRun, validate_cli: ValidateCli
) -> None:
    """A model input message changed in the sample's message pool (not in an event)."""

    def edit(sample: dict[str, Any]) -> dict[str, Any]:
        sample["events_data"]["messages"][0]["content"] = "a different prompt"
        return sample

    edit_zip_entry(clean_run.location, "samples/s0_epoch_1.json", edit)
    result = validate_cli(clean_run.store, clean_run.log_dir)
    assert_fails_with(result, "event_mismatch")
    assert "(model " in result.output and "differs in ['input']" in result.output


def test_delete_event(clean_run: CleanRun, validate_cli: ValidateCli) -> None:
    """The first tool event removed."""
    deleted: list[str] = []

    def edit(sample: EvalSample) -> None:
        index = next(i for i, e in enumerate(sample.events) if isinstance(e, ToolEvent))
        deleted.append(str(sample.events.pop(index).uuid))

    edit_sample(clean_run, edit)
    result = validate_cli(clean_run.store, clean_run.log_dir)
    assert_fails_with(result, "event_mismatch")
    # the first difference is where the stored event is missing from the copy
    assert f"(tool {deleted[0]})" in result.output


def test_reorder_events(clean_run: CleanRun, validate_cli: ValidateCli) -> None:
    """Two tool events swapped."""

    def edit(sample: EvalSample) -> None:
        first, second = [
            i for i, e in enumerate(sample.events) if isinstance(e, ToolEvent)
        ][:2]
        sample.events[first], sample.events[second] = (
            sample.events[second],
            sample.events[first],
        )

    edit_sample(clean_run, edit)
    result = validate_cli(clean_run.store, clean_run.log_dir)
    assert_fails_with(result, "event_mismatch")


def test_truncate_events(clean_run: CleanRun, validate_cli: ValidateCli) -> None:
    """The tail of the events cut off, from the score event on."""
    counts: list[int] = []

    def edit(sample: EvalSample) -> None:
        counts.append(len(sample.events))
        score = next(i for i, e in enumerate(sample.events) if e.event == "score")
        del sample.events[score:]
        counts.append(len(sample.events))

    edit_sample(clean_run, edit)
    result = validate_cli(clean_run.store, clean_run.log_dir)
    assert_fails_with(result, "event_mismatch")
    assert f".eval has {counts[1]} events, the store has {counts[0]}." in result.output


def test_delete_eval_file(clean_run: CleanRun, validate_cli: ValidateCli) -> None:
    clean_run.location.unlink()
    result = validate_cli(clean_run.store, clean_run.log_dir)
    assert_fails_with(result, "missing_eval_file")
    assert f"missing_eval_file {clean_run.eval_id}:" in result.output


def test_delete_sample(clean_run: CleanRun, validate_cli: ValidateCli) -> None:
    """The sample removed from the .eval zip, and from its summaries."""
    with zipfile.ZipFile(clean_run.location) as zf:
        entries = {
            info.filename: zf.read(info)
            for info in zf.infolist()
            if info.filename != "samples/s0_epoch_1.json"
        }
    with zipfile.ZipFile(clean_run.location, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, data in entries.items():
            zf.writestr(name, b"[]" if name == "summaries.json" else data)
    result = validate_cli(clean_run.store, clean_run.log_dir)
    assert_fails_with(result, "missing_sample")
    assert "Sample s0 epoch 1 is not in" in result.output


def test_swap_eval_file(
    clean_run: CleanRun,
    validate_cli: ValidateCli,
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """The .eval file replaced by the file of another run of the same task."""
    other = run(
        agent_task(samples=1),
        tmp_path_factory.mktemp("other"),
        tamper_evident_store=clean_run.store.url,
    )
    shutil.copyfile(other.location, clean_run.location)
    result = validate_cli(clean_run.store, clean_run.log_dir)
    assert_fails_with(result, "missing_eval_file")
    assert f"missing_eval_file {clean_run.eval_id}:" in result.output


def test_swap_eval_file_keep_eval_id(
    clean_run: CleanRun,
    validate_cli: ValidateCli,
    tmp_path_factory: pytest.TempPathFactory,
) -> None:
    """As above, with the other run's eval id changed to this run's."""
    other = run(agent_task(samples=1), tmp_path_factory.mktemp("other"))
    other.eval.eval_id = clean_run.eval_id
    write_eval_log(other, clean_run.location)
    result = validate_cli(clean_run.store, clean_run.log_dir)
    # the other run's events; its stats differ too (start and end times, in
    # whole seconds) unless both runs fell in the same seconds
    assert result.exit_code != 0, result.output
    assert result.kinds() - {"eval_mismatch"} == {"event_mismatch"}, result.output


def test_extra_eval_file(clean_run: CleanRun, validate_cli: ValidateCli) -> None:
    """A .eval file from a run without the store, put in the log dir."""
    extra = run(agent_task(samples=1), clean_run.log_dir)
    result = validate_cli(clean_run.store, clean_run.log_dir)
    assert_fails_with(result, "unstored_eval")
    assert f"unstored_eval {extra.eval.eval_id}:" in result.output


def test_duplicate_eval_id(clean_run: CleanRun, validate_cli: ValidateCli) -> None:
    """An edited copy of the .eval file next to the original, with its eval id: each is compared."""
    log = read_eval_log(clean_run.location)
    assert log.samples
    tool_event = next(e for e in log.samples[0].events if isinstance(e, ToolEvent))
    tool_event.result = "harmless"
    write_eval_log(log, clean_run.log_dir / "copy.eval")
    result = validate_cli(clean_run.store, clean_run.log_dir)
    assert_fails_with(result, "event_mismatch")
    assert "2 sample(s) compared, 1 finding(s)." in result.output


@pytest.mark.parametrize("how", ["log_api", "zip_entry_only"])
def test_add_sample(clean_run: CleanRun, validate_cli: ValidateCli, how: str) -> None:
    """A sample added to the .eval file: a copy of s0 as s1.

    With inspect's log API (in the summaries too), or as a zip entry only,
    which a full read of the log returns but the summaries do not list.
    """
    if how == "log_api":
        log = read_eval_log(clean_run.location)
        assert log.samples
        log.samples.append(log.samples[0].model_copy(update={"id": "s1"}))
        write_eval_log(log, clean_run.location)
    else:
        with zipfile.ZipFile(clean_run.location, "a") as zf:
            sample = json.loads(zf.read("samples/s0_epoch_1.json"))
            zf.writestr("samples/s1_epoch_1.json", json.dumps({**sample, "id": "s1"}))
    result = validate_cli(clean_run.store, clean_run.log_dir)
    assert_fails_with(result, "unstored_sample")
    assert f"unstored_sample {clean_run.eval_id}/s1.1:" in result.output


def test_add_sample_member_same_id(
    clean_run: CleanRun, validate_cli: ValidateCli
) -> None:
    """A zip member `samples/extra_epoch_1.json` added: s0's sample, edited.

    Its sample JSON says id s0, so only the member name shows that it is
    not the s0 the store has.
    """
    with zipfile.ZipFile(clean_run.location, "a") as zf:
        sample = json.loads(zf.read("samples/s0_epoch_1.json"))
        tool_event = next(e for e in sample["events"] if e["event"] == "tool")
        tool_event["result"] = "harmless"
        sample["scores"]["includes"]["value"] = "I"
        zf.writestr("samples/extra_epoch_1.json", json.dumps(sample))
    result = validate_cli(clean_run.store, clean_run.log_dir)
    assert_fails_with(result, "unstored_sample")
    assert f"unstored_sample {clean_run.eval_id}/extra.1:" in result.output


def test_edit_score(clean_run: CleanRun, validate_cli: ValidateCli) -> None:
    """The sample's score changed; its score event left as it was."""

    def edit(sample: EvalSample) -> None:
        assert sample.scores
        sample.scores["includes"].value = "I"

    edit_sample(clean_run, edit)
    result = validate_cli(clean_run.store, clean_run.log_dir)
    assert_fails_with(result, "score_mismatch")
    assert "score_mismatch " in result.output and "'includes'" in result.output


@pytest.mark.parametrize("edit", ["score", "removed"])
def test_edit_sample_summaries(
    clean_run: CleanRun, validate_cli: ValidateCli, edit: str
) -> None:
    """summaries.json edited, which the viewer's sample list and samples_df read.

    The summary's score changed, or every summary removed.
    """

    def edit_score(summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for summary in summaries:
            for value in summary["scores"].values():
                value["value"] = "I"
        return summaries

    edit_zip_entry(
        clean_run.location,
        "summaries.json",
        edit_score if edit == "score" else lambda _: [],
    )
    result = validate_cli(clean_run.store, clean_run.log_dir)
    assert_fails_with(result, "summary_mismatch")
    assert f"summary_mismatch {clean_run.eval_id}/s0.1" in result.output
    assert ("'includes'" in result.output) == (edit == "score")


def test_edit_score_one_to_true(
    evalhost_env: MotoStore, tmp_path: Path, validate_cli: ValidateCli
) -> None:
    """A score value 1 changed to true, in the sample scores and the score event.

    1 == True in Python; in JSON they differ.
    """
    log = numeric_score_run(evalhost_env, tmp_path)
    assert validate(evalhost_env, tmp_path).findings == []
    log = read_eval_log(log.location)
    assert log.samples
    sample = log.samples[0]
    assert sample.scores
    sample.scores["one_score"].value = True
    score_event = next(
        e
        for e in sample.events
        if isinstance(e, ScoreEvent)
        and e.score.value == 1
        and e.score.value is not True
    )
    score_event.score.value = True
    write_eval_log(log, log.location)

    result = validate_cli(evalhost_env, tmp_path)
    assert_fails_with(result, "score_mismatch", "event_mismatch")
    assert "Scores ['one_score'] differ" in result.output
    assert "differs in ['score']" in result.output


def eval_nonce(store: MotoStore, eval_id: str) -> str:
    """`inspect validate --nonce` (a subprocess), with the validator's keys."""
    result = subprocess.run(
        [
            *[sys.executable, "-m", "inspect_ai", "validate"],
            *["--nonce", eval_id, "--store", store.url],
        ],
        env={**os.environ, **store.env(store.validator)},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def score_command(
    log_file: Path,
    action: str,
    *options: str,
    store: str | None,
    nonce: str | None,
    scorer: str = "match",
) -> subprocess.CompletedProcess[str]:
    """`inspect score --scorer <scorer>` (a subprocess), with the environment's keys.

    Writes to ``log_file`` unless ``options`` name an output file.
    """
    env = {k: v for k, v in os.environ.items() if k != RESCORE_NONCE_ENV}
    return subprocess.run(
        [
            *[sys.executable, "-m", "inspect_ai", "score", str(log_file)],
            *["--scorer", scorer, "--overwrite", "--action", action],
            *(["--tamper-evident-store", store] if store else []),
            *options,
        ],
        env={**env, **({RESCORE_NONCE_ENV: nonce} if nonce else {})},
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
    )


def rescore(
    log_file: Path,
    action: str,
    *options: str,
    store: MotoStore | None,
    nonce: str | None = None,
    scorer: str = "match",
) -> None:
    """Rescore with the store, if given, and the eval's nonce, as `inspect validate --nonce` prints it.

    ``nonce`` replaces the eval's.
    """
    eval_id = read_eval_log(str(log_file), header_only=True).eval.eval_id
    result = score_command(
        log_file,
        action,
        *options,
        store=store.url if store else None,
        nonce=nonce or (eval_nonce(store, eval_id) if store else None),
        scorer=scorer,
    )
    assert result.returncode == 0, result.stderr


def rescored_lines(result: CliResult) -> list[str]:
    return [line for line in result.output.splitlines() if line.startswith("rescored ")]


@pytest.mark.parametrize(
    "actions",
    [
        ["overwrite"],
        ["append"],
        ["append", "append"],
        ["append", "overwrite"],
        ["append", "overwrite", "overwrite"],
        ["append", "overwrite", "overwrite", "append"],
    ],
)
@pytest.mark.parametrize("stream", [False, True])
def test_rescore_validates(
    clean_run: CleanRun,
    validate_cli: ValidateCli,
    actions: list[str],
    stream: bool,
) -> None:
    """`inspect score --tamper-evident-store`, one or more times: no findings.

    Each pass lists each rescore and the original results. After append,
    overwrite, overwrite, the append's marker is left and the first
    overwrite's is not, so nothing names the append's.
    """
    for action in actions:
        rescore(
            clean_run.location,
            action,
            *(["--stream"] if stream else []),
            store=clean_run.store,
        )
    log = read_eval_log(clean_run.location)
    assert log.samples and log.samples[0].scores
    expected_scores = reduce(
        lambda names, action: (
            {"match"}
            if action == "overwrite"
            else names | {unique_scorer_name("match", list(names))}
        ),
        actions,
        {"includes"},
    )
    assert set(log.samples[0].scores) == expected_scores

    result = validate_cli(clean_run.store, clean_run.log_dir)
    assert result.exit_code == 0, result.output
    assert result.findings() == []
    assert result.stopped() == []
    rescored = rescored_lines(result)
    assert sorted(line.rpartition(" ")[2] for line in rescored) == sorted(
        f"({action})" for action in actions
    )
    assert all(
        line.startswith(f"rescored {clean_run.eval_id} by ") for line in rescored
    )
    assert f"original_results {clean_run.eval_id}: includes accuracy=1.0" in (
        result.output
    )


def test_rescored_copy_validates(
    clean_run: CleanRun, validate_cli: ValidateCli
) -> None:
    """The original and a rescored copy, with the same eval id, in one log dir: both compared."""
    rescore(
        clean_run.location,
        "overwrite",
        "--output-file",
        str(clean_run.log_dir / "rescored.eval"),
        store=clean_run.store,
    )
    result = validate_cli(clean_run.store, clean_run.log_dir)
    assert result.exit_code == 0, result.output
    assert "1 eval(s), 2 sample(s) compared, 0 finding(s)." in result.output


@pytest.mark.parametrize(
    "scorer,kinds",
    [
        ("match", {"score_mismatch", "eval_mismatch", "event_mismatch"}),
        ("includes", {"event_mismatch"}),
    ],
)
def test_rescore_without_store_fails_validation(
    clean_run: CleanRun, validate_cli: ValidateCli, scorer: str, kinds: set[str]
) -> None:
    """`inspect score` without the store option: the rescore is not stored.

    `inspect score` writes the sample's events again in span order, with the
    new scorers span in place of the old one, so the events differ. The
    eval's own scorer (`includes`) gives the same scores and results.
    """
    rescore(clean_run.location, "overwrite", store=None, scorer=scorer)
    log = read_eval_log(clean_run.location)
    assert log.eval.eval_id == clean_run.eval_id
    assert log.samples and log.samples[0].scores
    assert set(log.samples[0].scores) == {scorer}

    result = validate_cli(clean_run.store, clean_run.log_dir)
    assert_fails_with(result, *kinds)


def test_edit_score_after_rescore(
    clean_run: CleanRun, validate_cli: ValidateCli
) -> None:
    """A rescored score changed with inspect's own log API."""
    rescore(clean_run.location, "append", store=clean_run.store)

    def edit(sample: EvalSample) -> None:
        assert sample.scores
        sample.scores["match"].value = "I"

    edit_sample(clean_run, edit)
    result = validate_cli(clean_run.store, clean_run.log_dir)
    assert_fails_with(result, "score_mismatch")
    assert (
        "Scores ['match'] differ from the sample closing record's (after rescores"
        in (result.output)
    )


def rescore_marker(sample: EvalSample) -> InfoEvent:
    (marker,) = [
        e
        for e in sample.events
        if isinstance(e, InfoEvent) and e.source == RESCORE_MARKER_SOURCE
    ]
    return marker


def test_forged_rescore_marker(clean_run: CleanRun, validate_cli: ValidateCli) -> None:
    """A rescore marker changed to name a rescore the store does not have."""
    rescore(clean_run.location, "overwrite", store=clean_run.store)

    def edit(sample: EvalSample) -> None:
        marker = rescore_marker(sample)
        assert isinstance(marker.data, dict)
        marker.data = {
            **marker.data,
            "rescore": {"eval_id": clean_run.eval_id, "rescore_id": "forged"},
        }

    edit_sample(clean_run, edit)
    result = validate_cli(clean_run.store, clean_run.log_dir)
    assert_fails_with(result, "missing_rescore")
    assert f"rescores/{clean_run.eval_id}/forged, which is not in the store" in (
        result.output
    )


def test_unrescored_sample_in_rescored_file(
    evalhost_env: MotoStore, tmp_path: Path, validate_cli: ValidateCli
) -> None:
    """One sample of a rescored file put back as it was before the rescore.

    Its scores and events match the original run, so only the other
    samples' markers show that the file was rescored.
    """
    log = run(agent_task(samples=2), tmp_path, tamper_evident_store=evalhost_env.url)
    original = read_eval_log(log.location)
    rescore(Path(log.location), "overwrite", store=evalhost_env)
    rescored = read_eval_log(log.location)
    assert original.samples and rescored.samples
    rescored.samples[0] = original.samples[0]
    write_eval_log(rescored, log.location)

    result = validate_cli(evalhost_env, tmp_path)
    assert_fails_with(result, "rescore_mismatch")


def test_rescore_with_wrong_nonce(
    clean_run: CleanRun, validate_cli: ValidateCli
) -> None:
    """A rescore with a nonce other than the eval's: each of its records is a finding."""
    rescore(clean_run.location, "append", store=clean_run.store, nonce=FORGED_NONCE)
    result = validate_cli(clean_run.store, clean_run.log_dir)
    assert_fails_with(result, "nonce")
    assert sorted(
        rest.partition(":")[0].rpartition("/")[2] for _, rest in result.findings()
    ) == ["closing", "s0.1", "start"]


def test_rescore_without_nonce_fails_before_scoring(
    clean_run: CleanRun, validate_cli: ValidateCli
) -> None:
    """`inspect score --tamper-evident-store` without the nonce variable: an error, nothing written."""
    before = clean_run.location.read_bytes()
    result = score_command(
        clean_run.location, "append", store=clean_run.store.url, nonce=None
    )
    assert result.returncode != 0
    assert RESCORE_NONCE_ENV in result.stdout + result.stderr
    assert clean_run.location.read_bytes() == before
    validated = validate_cli(clean_run.store, clean_run.log_dir)
    assert validated.exit_code == 0, validated.output
    assert rescored_lines(validated) == []


def test_validate_nonce_prints_eval_nonce(clean_run: CleanRun) -> None:
    """`inspect validate --nonce` prints the start record's nonce, and nothing else."""
    start = StartRecord.model_validate_json(
        clean_run.read(f"{clean_run.eval_id}/{START}")
    )
    assert eval_nonce(clean_run.store, clean_run.eval_id) == start.nonce
    store = clean_run.store
    with pytest.raises(ValueError, match="no-such-eval: NoSuchKey"):
        read_eval_nonce(store.url, "no-such-eval", store.client(store.validator))


@scorer(metrics=[mean()])
def failing_score() -> Scorer:
    async def score(state: TaskState, target: Target) -> Score:
        raise RuntimeError("Scorer failed.")

    return score


def test_stopped_rescore_lists_stopped(
    clean_run: CleanRun, validate_cli: ValidateCli, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A rescore whose scorer fails writes a start record only: listed as stopped."""
    monkeypatch.setenv(
        RESCORE_NONCE_ENV, eval_nonce(clean_run.store, clean_run.eval_id)
    )
    with pytest.raises(Exception, match="Scorer failed"):
        score(
            read_eval_log(clean_run.location),
            failing_score(),
            action="append",
            display="none",
            tamper_evident_store=clean_run.store.url,
        )
    result = validate_cli(clean_run.store, clean_run.log_dir)
    assert result.exit_code == 0, result.output
    (stopped,) = result.stopped()
    assert stopped.startswith(f"rescores/{clean_run.eval_id}/")
    assert len(rescored_lines(result)) == 1


def test_eval_retry_of_rescored_log_validates(
    evalhost_env: MotoStore,
    tmp_path: Path,
    validate_cli: ValidateCli,
    failures: Path,
) -> None:
    """eval_retry of a rescored .eval: s1, reused, names the first eval's rescore."""
    log = retried_task_run(evalhost_env, tmp_path, failures, s0_failures=1)
    rescore(Path(log.location), "append", store=evalhost_env)
    retry = eval_retry(
        log.location,
        log_dir=str(tmp_path),
        display="none",
        tamper_evident_store=evalhost_env.url,
    )[0]
    assert retry.status == "success", retry.error
    assert retry.samples
    reused = next(s for s in retry.samples if s.id == "s1")
    marker = RescoreMarker.model_validate(rescore_marker(reused).data)
    assert marker.rescore.eval_id == log.eval.eval_id

    result = validate_cli(evalhost_env, tmp_path)
    assert result.exit_code == 0, result.output
    assert result.findings() == []
    assert "2 eval(s), 4 sample(s) compared, 0 finding(s)." in result.output


def stored_rescore_record(
    store: MotoStore, eval_id: str, sample_part: str
) -> RescoreSampleRecord:
    """The eval's one rescore record of the sample, read with the validator's keys."""
    s3 = store.client(store.validator)
    # (moto's signature check fails on a "/" in the listed prefix)
    (key,) = [
        o["Key"]
        for o in s3.list_objects_v2(Bucket=BUCKET, Prefix=store.prefix)["Contents"]
        if o["Key"].startswith(f"{store.prefix}/rescores/{eval_id}/")
        and o["Key"].endswith(f"/{sample_part}")
    ]
    return RescoreSampleRecord.model_validate_json(
        s3.get_object(Bucket=BUCKET, Key=key)["Body"].read()
    )


def copy_rescore(
    log_file: str, sample_id: str, record: RescoreSampleRecord, action: ScoreAction
) -> None:
    """Apply a stored rescore record to a sample of the .eval file, as `inspect score` would.

    Leaves the header's results as they are. Needs no nonce or store access.
    """
    log = read_eval_log(log_file)
    assert log.samples
    sample = next(s for s in log.samples if s.id == sample_id)
    events = _get_updated_events(sample, record.events, action)
    sample.scores = _get_updated_scores(sample, record.scores, action)
    sample.events = events
    write_eval_log(log, log_file)


def test_rescore_of_another_eval(
    evalhost_env: MotoStore, tmp_path: Path, validate_cli: ValidateCli
) -> None:
    """Eval B's rescore of s0 copied onto eval A's s0, which was not rescored."""
    log_a = run(agent_task(samples=1), tmp_path, tamper_evident_store=evalhost_env.url)
    log_b = run(agent_task(samples=1), tmp_path, tamper_evident_store=evalhost_env.url)
    rescore(Path(log_b.location), "overwrite", store=evalhost_env)
    record = stored_rescore_record(evalhost_env, log_b.eval.eval_id, "s0.1")
    copy_rescore(log_a.location, "s0", record, "overwrite")

    result = validate_cli(evalhost_env, tmp_path)
    assert_fails_with(result, "missing_rescore")
    assert (
        f"missing_rescore {log_a.eval.eval_id}/s0.1/1: The sample names rescore "
        f"rescores/{log_b.eval.eval_id}/{record.rescore_id}, of an eval this copy "
        "of the sample did not come through." in result.output
    )


def test_retry_takes_prior_rescore_of_own_sample(
    evalhost_env: MotoStore,
    tmp_path: Path,
    validate_cli: ValidateCli,
    failures: Path,
) -> None:
    """The first eval's rescore of s0 copied onto the retry's s0, which the retry ran itself."""
    log = retried_task_run(evalhost_env, tmp_path, failures, s0_failures=1)
    rescore(Path(log.location), "append", store=evalhost_env)
    retry = eval_retry(
        log.location,
        log_dir=str(tmp_path),
        display="none",
        tamper_evident_store=evalhost_env.url,
    )[0]
    assert retry.status == "success", retry.error
    record = stored_rescore_record(evalhost_env, log.eval.eval_id, "s0.1")
    copy_rescore(retry.location, "s0", record, "append")

    result = validate_cli(evalhost_env, tmp_path)
    assert_fails_with(result, "missing_rescore")
    ((_, message),) = result.findings()
    assert message.startswith(f"{retry.eval.eval_id}/s0.1/"), message
    assert f"rescores/{log.eval.eval_id}/{record.rescore_id}, of an eval" in message


def test_edit_results(clean_run: CleanRun, validate_cli: ValidateCli) -> None:
    """The eval's accuracy changed in the .eval header."""
    log = read_eval_log(clean_run.location)
    assert log.results
    log.results.scores[0].metrics["accuracy"].value = 0.5
    write_eval_log(log, clean_run.location)
    result = validate_cli(clean_run.store, clean_run.log_dir)
    assert_fails_with(result, "eval_mismatch")
    assert "results" in result.output


# ---------------------------------------------- tampering, add-only store
#
# The eval host can add keys (put with If-None-Match) and nothing else. Its
# keys outlive the eval, so after the eval anyone holding them can add
# records too, but without the eval's nonce, which was only in memory.


def test_forged_record_wrong_nonce(
    clean_run: CleanRun, validate_cli: ValidateCli
) -> None:
    """The next record of the sample added after the eval."""
    seq = clean_run.records() + 1
    clean_run.put(clean_run.sample_key(seq), clean_run.forged_record(seq))
    result = validate_cli(clean_run.store, clean_run.log_dir)
    assert_fails_with(result, "nonce", "record_count")
    assert f"nonce {clean_run.sample_key(seq)}:" in result.output


def test_forged_record_number_past_next(
    clean_run: CleanRun, validate_cli: ValidateCli
) -> None:
    """A record added with a number past the next one."""
    seq = clean_run.records() + 5
    clean_run.put(clean_run.sample_key(seq), clean_run.forged_record(seq))
    result = validate_cli(clean_run.store, clean_run.log_dir)
    assert_fails_with(result, "nonce", "record_count")


def test_forged_late_event_version(
    clean_run: CleanRun, validate_cli: ValidateCli
) -> None:
    """A record that changes an event the store already holds complete."""
    seq = clean_run.records() + 1
    tool_event = next(
        e
        for i in range(1, seq)
        for e in clean_run.stored_events(i)
        if e["event"] == "tool" and not e.get("pending")
    )
    edited = {**tool_event, "result": "harmless"}
    clean_run.put(clean_run.sample_key(seq), clean_run.forged_record(seq, edited))
    result = validate_cli(clean_run.store, clean_run.log_dir)
    assert_fails_with(
        result, "nonce", "record_count", "late_event_version", "event_mismatch"
    )
    assert f"event {tool_event['uuid']}, stored complete in record" in result.output


@pytest.mark.parametrize(
    "kind",
    [
        "not_json",
        "bad_event",
        "odd_key",
        "wrong_type",
        "bad_attempt_closing",
        "bad_attempt_record",
    ],
)
def test_malformed_record(
    clean_run: CleanRun, validate_cli: ValidateCli, kind: str
) -> None:
    """Something the eval never writes, added under its prefix.

    Before the validator reported these, it stopped with a traceback, so it
    could not check any eval under the prefix.
    """
    seq = clean_run.records() + 1
    match kind:
        case "not_json":
            key, body = clean_run.sample_key(seq), "not a record"
        case "bad_event":
            key = clean_run.sample_key(seq)
            body = clean_run.forged_record(seq, {"uuid": "u", "event": "info"})
        case "odd_key":
            key = f"{clean_run.eval_id}/s0.1/x"
            body = clean_run.forged_record(seq)
        case "bad_attempt_closing":
            key = f"{clean_run.eval_id}/s0.1/bad/{CLOSING}"
            body = clean_run.read(clean_run.sample_key(CLOSING)).decode()
        case "bad_attempt_record":
            key = f"{clean_run.eval_id}/s0.1/bad/{seq}"
            body = clean_run.forged_record(seq)
        case _:
            key = clean_run.sample_key(CLOSING, attempt=2)
            body = clean_run.read(f"{clean_run.eval_id}/{START}").decode()
    clean_run.put(key, body)
    result = validate_cli(clean_run.store, clean_run.log_dir)
    assert_fails_with(result, "malformed_record")
    assert f"malformed_record {key}:" in result.output
    assert ": :" not in result.output


def test_unreadable_record(clean_run: CleanRun, validate_cli: ValidateCli) -> None:
    """A record S3 will not return (GLACIER storage class), added with eval-host keys.

    Reported, and the eval's other records still checked.
    """
    key = clean_run.sample_key(clean_run.records() + 1)
    clean_run.store.client(clean_run.store.evalhost).put_object(
        Bucket=BUCKET,
        Key=f"{clean_run.store.prefix}/{key}",
        Body=clean_run.forged_record(clean_run.records() + 1),
        IfNoneMatch="*",
        StorageClass="GLACIER",
    )
    result = validate_cli(clean_run.store, clean_run.log_dir)
    assert_fails_with(result, "malformed_record")
    assert f"malformed_record {key}: Cannot read it: " in result.output
    assert "InvalidObjectState" in result.output
    assert "1 sample(s) compared" in result.output


class _GetObjectRefused:
    """The validator's client, with every ``get_object`` refused with ``code``."""

    def __init__(self, client: Any, code: str) -> None:
        self._client = client
        self._code = code

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)

    def get_object(self, **kwargs: Any) -> Any:
        raise ClientError({"Error": {"Code": self._code}}, "GetObject")


@pytest.mark.parametrize("code", ["AccessDenied", "NoSuchBucket", "ExpiredToken"])
def test_store_read_refused_fails(clean_run: CleanRun, code: str) -> None:
    """A refusal that means the validator cannot read the store stops it."""
    store = clean_run.store
    client = _GetObjectRefused(store.client(store.validator), code)
    with pytest.raises(ClientError, match=code):
        validate_store(store.url, str(clean_run.log_dir), client=client)


@pytest.mark.parametrize(
    "table,key",
    [
        ("message_pool", "new"),
        ("call_pool", "new"),
        ("message_pool", "stored"),
        ("call_pool", "stored"),
        ("attachments", "stored"),
    ],
)
def test_malformed_buffer_row(
    clean_run: CleanRun, validate_cli: ValidateCli, table: str, key: str
) -> None:
    """A record with a pool row whose data is not JSON, or a row with a key already stored.

    The record parses; the sample rebuild reads the rows. Another eval under
    the prefix is still checked.
    """
    records = [
        SampleRecord.model_validate_json(clean_run.read(clean_run.sample_key(i)))
        for i in range(1, clean_run.records() + 1)
    ]
    stored = _rebuild_rows(records)
    row_key = (
        "new-key"
        if key == "new"
        else stored.attachments[0].hash
        if table == "attachments"
        else getattr(stored, table)[0].key
    )
    pool_row = [BufferPoolRow(key=row_key, data="not json")]
    rows = (
        BufferRows(attachments=[BufferAttachmentRow(hash=row_key, content="x")])
        if table == "attachments"
        else BufferRows(message_pool=pool_row)
        if table == "message_pool"
        else BufferRows(call_pool=pool_row)
    )
    seq = len(records) + 1
    forged = SampleRecord(
        eval_id=clean_run.eval_id,
        nonce=FORGED_NONCE,
        sample=SampleAttemptRef(sample_id="s0", epoch=1, attempt=1),
        seq=seq,
        rows=rows,
    )
    clean_run.put(clean_run.sample_key(seq), forged.model_dump_json())
    other = run(
        agent_task(samples=1),
        clean_run.log_dir,
        tamper_evident_store=clean_run.store.url,
    )
    assert other.status == "success", other.error

    result = validate_cli(clean_run.store, clean_run.log_dir)
    assert_fails_with(result, "nonce", "record_count", "malformed_record")
    assert f"malformed_record {clean_run.eval_id}/s0.1/1:" in result.output
    assert "2 eval(s), 1 sample(s) compared" in result.output


@pytest.mark.parametrize("field", ["input_refs", "call_refs"])
def test_forged_model_event_pool_refs_out_of_range(
    clean_run: CleanRun, validate_cli: ValidateCli, field: str
) -> None:
    """A model event whose pool refs point past the end of the pool, or below 0.

    The rebuild reads the pools as lists, and a slice past either end is
    empty, so the validator reports the extra event and does not stop.
    """
    seq = clean_run.records() + 1
    event = next(
        e
        for i in range(1, seq)
        for e in clean_run.stored_events(i)
        if e["event"] == "model" and e.get("call")
    )
    refs = [[99, 100], [-99, -98]]
    if field == "input_refs":
        event["input_refs"] = refs
    else:
        event["call"]["call_refs"] = refs
    event["uuid"] = "forged-model-event"
    clean_run.put(clean_run.sample_key(seq), clean_run.forged_record(seq, event))
    result = validate_cli(clean_run.store, clean_run.log_dir)
    assert_fails_with(result, "nonce", "record_count", "event_mismatch")
    assert "Traceback" not in result.output


def test_forged_attempt(clean_run: CleanRun, validate_cli: ValidateCli) -> None:
    """A second attempt of the sample: attempt 1's rows and closing, copied."""
    records = [
        SampleRecord.model_validate_json(clean_run.read(clean_run.sample_key(i)))
        for i in range(1, clean_run.records() + 1)
    ]
    copy = SampleRecord(
        eval_id=clean_run.eval_id,
        nonce=FORGED_NONCE,
        sample=SampleAttemptRef(sample_id="s0", epoch=1, attempt=2),
        seq=1,
        rows=_rebuild_rows(records),
    )
    clean_run.put(clean_run.sample_key(1, attempt=2), copy.model_dump_json())
    closing = SampleClosingRecord.model_validate_json(
        clean_run.read(clean_run.sample_key(CLOSING))
    )
    closing.nonce = FORGED_NONCE
    closing.sample = SampleAttemptRef(sample_id="s0", epoch=1, attempt=2)
    closing.records = 1
    clean_run.put(clean_run.sample_key(CLOSING, attempt=2), closing.model_dump_json())
    result = validate_cli(clean_run.store, clean_run.log_dir)
    # the validator compares the .eval sample with the last attempt; the
    # copied rows match it, so only the nonce and the closing list catch it
    assert_fails_with(result, "nonce", "unlisted_attempt")


def test_forged_eval(clean_run: CleanRun, validate_cli: ValidateCli) -> None:
    """A whole eval added to the store: start, records, closings, its own nonce."""
    forged_id = "forged" + clean_run.eval_id[6:]
    for key in [
        "start",
        *[f"s0.1/1/{i}" for i in range(1, clean_run.records() + 1)],
        "s0.1/1/closing",
        "closing",
    ]:
        body = clean_run.read(f"{clean_run.eval_id}/{key}").decode()
        clean_run.put(f"{forged_id}/{key}", body.replace(clean_run.eval_id, forged_id))
    result = validate_cli(clean_run.store, clean_run.log_dir)
    assert_fails_with(result, "missing_eval_file")
    assert f"missing_eval_file {forged_id}:" in result.output


def test_forged_successor_lists_deleted_eval_file(
    clean_run: CleanRun, validate_cli: ValidateCli
) -> None:
    """The .eval file deleted, and a forged later eval that names the eval.

    With eval-host keys and write access to the log dir, someone adds an
    eval whose start record names the eval as its prior eval, and a .eval
    file of the forged eval. The deleted file is not a finding, but it is
    listed.
    """
    forged_id = "forged" + clean_run.eval_id[6:]
    for key in [
        *[f"s0.1/1/{i}" for i in range(1, clean_run.records() + 1)],
        "s0.1/1/closing",
        "closing",
    ]:
        body = clean_run.read(f"{clean_run.eval_id}/{key}").decode()
        clean_run.put(f"{forged_id}/{key}", body.replace(clean_run.eval_id, forged_id))
    start = StartRecord.model_validate_json(
        clean_run.read(f"{clean_run.eval_id}/start")
    )
    start.eval_id = forged_id
    start.prior_eval_id = clean_run.eval_id
    clean_run.put(f"{forged_id}/start", start.model_dump_json())
    log = read_eval_log(clean_run.location)
    log.eval.eval_id = forged_id
    write_eval_log(log, clean_run.log_dir / "forged.eval")
    clean_run.location.unlink()

    result = validate_cli(clean_run.store, clean_run.log_dir)
    assert result.exit_code == 0, result.output
    assert result.findings() == []
    assert (
        f"prior_without_file {clean_run.eval_id}: No .eval file; "
        f"{forged_id} names it as its prior eval." in result.output
    )


def test_eval_names_itself_as_prior(
    clean_run: CleanRun, validate_cli: ValidateCli
) -> None:
    """An eval whose start record names itself does not hide its deleted .eval file."""
    forged_id = "forged" + clean_run.eval_id[6:]
    for key in [
        *[f"s0.1/1/{i}" for i in range(1, clean_run.records() + 1)],
        "s0.1/1/closing",
        "closing",
    ]:
        body = clean_run.read(f"{clean_run.eval_id}/{key}").decode()
        clean_run.put(f"{forged_id}/{key}", body.replace(clean_run.eval_id, forged_id))
    start = StartRecord.model_validate_json(
        clean_run.read(f"{clean_run.eval_id}/start")
    )
    start.eval_id = forged_id
    start.prior_eval_id = forged_id
    clean_run.put(f"{forged_id}/start", start.model_dump_json())

    result = validate_cli(clean_run.store, clean_run.log_dir)
    assert_fails_with(result, "missing_eval_file")
    assert f"missing_eval_file {forged_id}:" in result.output
    assert "prior_without_file" not in result.output


def test_forged_eval_without_start(
    clean_run: CleanRun, validate_cli: ValidateCli
) -> None:
    """Records added under an eval id that has no start record."""
    clean_run.put(
        "no-such-eval/s0.1/1/1",
        clean_run.read(clean_run.sample_key(1)),
    )
    result = validate_cli(clean_run.store, clean_run.log_dir)
    assert_fails_with(result, "missing_start")
    assert "missing_start no-such-eval: No start record." in result.output


def test_overwrite_record(clean_run: CleanRun, validate_cli: ValidateCli) -> None:
    """The .eval file edited, and the store record overwritten to match it.

    The eval host puts without If-None-Match. On real S3 the bucket policy
    refuses that put; moto does not enforce it, so a second version is added.
    The validator reads the earliest version.
    """
    tool_seq, tool_event = next(
        (i, e)
        for i in range(1, clean_run.records() + 1)
        for e in clean_run.stored_events(i)
        if e["event"] == "tool" and not e.get("pending")
    )
    record = SampleRecord.model_validate_json(
        clean_run.read(clean_run.sample_key(tool_seq))
    )
    for row in record.rows.events:
        if row.event_id == tool_event["uuid"]:
            row.data = json.dumps({**json.loads(row.data), "result": "harmless"})
    clean_run.put(
        clean_run.sample_key(tool_seq), record.model_dump_json(), if_none_match=False
    )

    def edit(sample: EvalSample) -> None:
        event = next(e for e in sample.events if e.uuid == tool_event["uuid"])
        assert isinstance(event, ToolEvent)
        event.result = "harmless"

    edit_sample(clean_run, edit)
    result = validate_cli(clean_run.store, clean_run.log_dir)
    assert_fails_with(result, "overwrite", "event_mismatch")
    assert "2 versions: an overwrite got through." in result.output


def test_delete_marker(clean_run: CleanRun, validate_cli: ValidateCli) -> None:
    """A store admin deletes a record without a version id.

    Real S3 allows this under COMPLIANCE retention: it adds a delete marker
    and keeps the record. The eval host's role cannot delete.
    """
    clean_run.store.client(clean_run.store.admin).delete_object(
        Bucket=BUCKET, Key=f"{clean_run.store.prefix}/{clean_run.sample_key(CLOSING)}"
    )
    result = validate_cli(clean_run.store, clean_run.log_dir)
    assert_fails_with(result, "overwrite")
    assert "Delete marker." in result.output


# Records removed for good. Real S3 refuses this to everyone under COMPLIANCE
# retention. moto lets the admin shorten the retention and delete, so these
# tests use that. A host that stops writing early leaves a store like
# `remove_sample_closing` or `remove_eval_closing`; `remove_last_record` keeps
# both closing records, which such a host does not write.


def test_remove_sample_closing(clean_run: CleanRun, validate_cli: ValidateCli) -> None:
    clean_run.store.remove_version(clean_run.sample_key(CLOSING))
    result = validate_cli(clean_run.store, clean_run.log_dir)
    assert_fails_with(result, "unstored_sample")
    assert result.stopped() == [f"{clean_run.eval_id}/s0.1/1"]


def test_remove_last_record(clean_run: CleanRun, validate_cli: ValidateCli) -> None:
    clean_run.store.remove_version(clean_run.sample_key(clean_run.records()))
    result = validate_cli(clean_run.store, clean_run.log_dir)
    assert_fails_with(result, "record_count", "event_mismatch")


def test_remove_middle_record(clean_run: CleanRun, validate_cli: ValidateCli) -> None:
    clean_run.store.remove_version(clean_run.sample_key(2))
    result = validate_cli(clean_run.store, clean_run.log_dir)
    assert_fails_with(result, "record_count", "event_mismatch")


def test_remove_eval_closing(clean_run: CleanRun, validate_cli: ValidateCli) -> None:
    """The eval is listed as stopped, and its finished .eval file is a finding."""
    clean_run.store.remove_version(f"{clean_run.eval_id}/{CLOSING}")
    result = validate_cli(clean_run.store, clean_run.log_dir)
    assert_fails_with(result, "missing_eval_closing")
    assert result.stopped() == [clean_run.eval_id]


def test_eval_host_stops_before_finish(
    clean_run: CleanRun, validate_cli: ValidateCli
) -> None:
    """No eval closing record, and a .eval file still "started": listed as stopped.

    As when the host stops writing before the eval finishes: its .eval file
    has no header.json yet.
    """
    clean_run.store.remove_version(f"{clean_run.eval_id}/{CLOSING}")
    with zipfile.ZipFile(clean_run.location) as zf:
        entries = {
            info.filename: zf.read(info)
            for info in zf.infolist()
            if info.filename != "header.json"
        }
    with zipfile.ZipFile(clean_run.location, "w", zipfile.ZIP_DEFLATED) as zf:
        for entry, data in entries.items():
            zf.writestr(entry, data)
    assert read_eval_log(clean_run.location, header_only=True).status == "started"
    result = validate_cli(clean_run.store, clean_run.log_dir)
    assert result.exit_code == 0, result.output
    assert result.stopped() == [clean_run.eval_id]
    assert "1 eval(s), 1 sample(s) compared, 0 finding(s)." in result.output


@pytest.mark.parametrize("change", [None, "nonce"])
def test_stopped_attempt_records_checked(
    clean_run: CleanRun, change: FindingKind | None
) -> None:
    """An attempt and an eval with no closing record are listed as stopped.

    Their records are still checked: a wrong nonce is a finding.
    """
    eval_id = clean_run.eval_id
    keys = [f"{eval_id}/{START}"] + [
        clean_run.sample_key(seq) for seq in range(1, clean_run.records() + 1)
    ]
    records = {key: clean_run.read(key) for key in keys}
    if change == "nonce":
        forged = SampleRecord.model_validate_json(records[clean_run.sample_key(1)])
        forged.nonce = FORGED_NONCE
        records[clean_run.sample_key(1)] = forged.model_dump_json().encode()

    stored = _read_eval(eval_id, list(records), records.__getitem__)
    assert [f.kind for f in stored.findings] == ([change] if change else [])
    assert stored.stopped == [eval_id, f"{eval_id}/s0.1/1"]


@pytest.mark.parametrize("table", ["message_pool", "call_pool", "attachments"])
def test_stopped_attempt_malformed_buffer_row(
    clean_run: CleanRun, validate_cli: ValidateCli, table: str
) -> None:
    """A stopped attempt's record, with the eval's nonce and a row the eval could not have written.

    A pool row that is not JSON, or an attachment already stored. The sample
    closing record and the .eval sample are gone, so nothing is compared,
    but the attempt's rows are still rebuilt. The eval closing record lists
    the sample, so its absence from the .eval file is ``missing_sample``.
    """
    records = [
        SampleRecord.model_validate_json(clean_run.read(clean_run.sample_key(i)))
        for i in range(1, clean_run.records() + 1)
    ]
    rows = (
        BufferRows(attachments=[_rebuild_rows(records).attachments[0]])
        if table == "attachments"
        else BufferRows.model_validate(
            {table: [BufferPoolRow(key="new-key", data="not json")]}
        )
    )
    seq = len(records) + 1
    clean_run.put(
        clean_run.sample_key(seq),
        records[0].model_copy(update={"seq": seq, "rows": rows}).model_dump_json(),
    )
    clean_run.store.remove_version(clean_run.sample_key(CLOSING))
    log = read_eval_log(clean_run.location)
    log.samples = []
    write_eval_log(log, clean_run.location)

    result = validate_cli(clean_run.store, clean_run.log_dir)
    assert_fails_with(result, "malformed_record", "missing_sample")
    assert f"malformed_record {clean_run.eval_id}/s0.1/1:" in result.output
    assert f"missing_sample {clean_run.eval_id}/s0.1:" in result.output
    assert result.stopped() == [f"{clean_run.eval_id}/s0.1/1"]


def test_remove_start(clean_run: CleanRun, validate_cli: ValidateCli) -> None:
    clean_run.store.remove_version(f"{clean_run.eval_id}/{START}")
    result = validate_cli(clean_run.store, clean_run.log_dir)
    assert_fails_with(result, "missing_start")


# ------------------------------------------------- store settings changed


def test_policy_removed(clean_run: CleanRun, validate_cli: ValidateCli) -> None:
    """No bucket policy requires If-None-Match, so the host could overwrite."""
    result = validate_cli(clean_run.store, clean_run.log_dir, policy=False)
    assert_fails_with(result, "settings")
    assert "No bucket policy statement denies a put without If-None-Match." in (
        result.output
    )


# ------------------------------------------------------------------ scope


def test_prefix_per_log_dir_scopes_validation(
    evalhost_env: MotoStore, tmp_path: Path
) -> None:
    """Two log dirs share the bucket, each with its own store prefix."""
    other = replace(evalhost_env, url=f"{evalhost_env.url}x")
    run(agent_task(samples=1), tmp_path / "a", tamper_evident_store=evalhost_env.url)
    run(agent_task(samples=1), tmp_path / "b", tamper_evident_store=other.url)

    assert validate(evalhost_env, tmp_path / "a").findings == []
    assert validate(other, tmp_path / "b").findings == []
    missing = validate(evalhost_env, tmp_path / "b").findings
    assert sorted(f.kind for f in missing) == ["missing_eval_file", "unstored_eval"]


def test_sample_key_encoding() -> None:
    assert sample_key_part("a.1", 2) == "a.1.2"
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
        log = run(agent_task(samples=1), tmp_path, tamper_evident_store=store.url)
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
            tamper_evident_store=store.url,
        )[0]
        assert log.status == "error"
        assert log.error and "AccessDenied" in log.error.message

        # the sample is logged with its error, and the store refused its
        # closing record and the eval's, as it refused the record
        report = validate(store, tmp_path)
        assert sorted(f.kind for f in report.findings) == [
            "missing_eval_closing",
            "unstored_sample",
        ]
        eval_id = log.eval.eval_id
        assert report.stopped == [eval_id, f"{eval_id}/1.1/1"]


@pytest.mark.parametrize("stored", [False, True], ids=["not_stored", "response_lost"])
async def test_put_retries_and_412_after_retry(
    evalhost_env: MotoStore, stored: bool
) -> None:
    """Botocore retries a network error; a 412 after a retried put fails the write.

    The first send fails with a network error. With ``stored``, the put
    first reaches the store and only its response is lost.
    """
    store = AddOnlyStore(StoreLocation.parse(evalhost_env.url))
    other = evalhost_env.client(evalhost_env.evalhost)
    sends: list[str] = []

    def first_send_fails(request: Any, **_: Any) -> None:
        sends.append(request.url)
        if len(sends) > 1:
            return
        if stored:
            other.put_object(
                Bucket=BUCKET,
                Key=store.location.key("record"),
                Body=b"{}",
                IfNoneMatch="*",
            )
            raise ReadTimeoutError(endpoint_url="moto")
        raise EndpointConnectionError(endpoint_url="moto")

    store._client.meta.events.register("before-send.s3.PutObject", first_send_fails)
    if stored:
        with pytest.raises(AddOnlyStoreError, match="PreconditionFailed.*own earlier"):
            await store.put("record", b"{}")
    else:
        await store.put("record", b"{}")
    assert len(sends) == 2


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
