"""Tamper-evident logs, against moto server.

Runs real evals (mockllm, react agents, parallel and serial tool stages, a
sub-agent used as a tool, two sub-agents at once, streamed output) with the
add-only store on, then validates the store and the .eval files. The
tampering tests change a clean run's .eval file or store, then run the
`inspect validate` command and check its findings. Set ADDONLY_EVIDENCE_DIR
to save each command's output. See
design/tamper-evident-logs-findings.md.
"""

import json
import os
import shutil
import subprocess
import sys
import uuid
import zipfile
from collections.abc import Callable, Iterator, Mapping
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, NamedTuple

import anyio
import pytest
from botocore.exceptions import EndpointConnectionError, ReadTimeoutError
from test_helpers.addonly_agents import (
    agent_task,
    run,
    scripted_call,
    scripted_output,
)
from test_helpers.addonly_moto import (
    BUCKET,
    CliResult,
    MotoStore,
    moto_addonly_store,
)

from inspect_ai import Task, eval, eval_retry, eval_set, task
from inspect_ai._eval.task.log import TaskLogger
from inspect_ai._util.registry import _registry
from inspect_ai.agent import react
from inspect_ai.dataset import Sample
from inspect_ai.event import Event, InfoEvent, ScoreEvent, ToolEvent
from inspect_ai.log import EvalLog, EvalSample, read_eval_log, write_eval_log
from inspect_ai.log._addonly._records import (
    CLOSING,
    START,
    SampleAttemptRef,
    SampleClosingRecord,
    SampleRecord,
)
from inspect_ai.log._addonly._store import (
    AddOnlyStore,
    AddOnlyStoreError,
    StoreLocation,
    sample_key_part,
)
from inspect_ai.log._addonly._validate import (
    ValidationReport,
    _event_version_problems,
    _rebuild_rows,
    validate_store,
)
from inspect_ai.log._addonly._writer import EvalRecordWriter
from inspect_ai.log._recorders.buffer.database import SampleBufferDatabase
from inspect_ai.log._recorders.buffer.types import (
    BufferAttachmentRow,
    BufferEventRow,
    BufferPoolRow,
    BufferRows,
)
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
from inspect_ai.scorer import Score, Scorer, Target, includes, mean, scorer
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


EVIDENCE_DIR_ENV = "ADDONLY_EVIDENCE_DIR"
"""If set, each `inspect validate` run of the tests saves its output there."""

ValidateCli = Callable[..., CliResult]


@pytest.fixture
def validate_cli(request: pytest.FixtureRequest) -> ValidateCli:
    """Runs `inspect validate` (a subprocess) and saves its output as evidence."""

    def validate_cli(
        store: MotoStore, log_dir: Path, *options: str, policy: bool = True
    ) -> CliResult:
        result = store.validate_cli(log_dir, *options, policy=policy)
        evidence = os.environ.get(EVIDENCE_DIR_ENV)
        if evidence:
            name = request.node.name.removeprefix("test_")
            shown = ["inspect", *result.command[3:]]
            Path(evidence, f"{name}.txt").write_text(
                f"$ {' '.join(shown)}\n{result.output}[exit code {result.exit_code}]\n"
            )
        return result

    return validate_cli


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
        "results.\n"
        "Not checked: everything else, including the eval spec and plan, each "
        "sample's messages, output and error, what the sample summaries say, "
        "invalidation and log_updates.\n"
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
    """Attempt 1 errors and is retried: it has no closing record, attempt 2 has one."""
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
    assert (
        f"retried {log.eval.eval_id}/s0.1/1: No closing record; a later attempt "
        "has one.\n" in result.output
    )


@solver
def fail_attempts_in_file(path: str) -> Solver:
    """As `fail_attempts`, with the counts in a JSON file.

    eval_retry imports the task file again, so module state does not carry
    over to the retry; the file and its path (a task arg) do.
    """

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        state = await generate(state)
        failures = json.loads(Path(path).read_text())
        key = str(state.sample_id)
        if failures.get(key, 0) > 0:
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


def retried_task_run(store: MotoStore, log_dir: Path, s0_failures: int) -> EvalLog:
    """First eval of `retried_task`: s1 succeeds, then s0 fails and stops the eval.

    One sample at a time, so the error cannot cancel s1.
    """
    failures = log_dir / "failures.json"
    failures.write_text(json.dumps({"s0": s0_failures}))
    log = eval(
        retried_task(str(failures)),
        model="mockllm/model",
        log_dir=str(log_dir),
        display="none",
        max_samples=1,
        tamper_evident_store=store.url,
    )[0]
    assert log.status == "error"
    return log


def test_eval_retry_validates(
    evalhost_env: MotoStore, tmp_path: Path, validate_cli: ValidateCli
) -> None:
    """eval_retry twice: s0 fails twice, s1 is reused from the first eval each time.

    s1 has no records under either retry. Each retry's start record names
    the eval it reused samples from; the second retry's names the first
    retry, whose own names the first eval, where the records are.
    """
    log = retried_task_run(evalhost_env, tmp_path, s0_failures=2)
    for status in ["error", "success"]:
        log = eval_retry(
            log,
            log_dir=str(tmp_path),
            display="none",
            tamper_evident_store=evalhost_env.url,
        )[0]
        assert log.status == status, log.error

    result = validate_cli(evalhost_env, tmp_path)
    assert result.exit_code == 0, result.output
    assert result.findings() == []
    assert "3 eval(s), 6 sample(s) compared, 0 finding(s)." in result.output


def test_task_retry_attempts_validates(
    evalhost_env: MotoStore, tmp_path: Path, validate_cli: ValidateCli
) -> None:
    """task_retry_attempts: the second eval reuses s1 from the first."""
    failures = tmp_path / "failures.json"
    failures.write_text(json.dumps({"s0": 1}))
    log_dir = tmp_path / "logs"
    log = eval(
        retried_task(str(failures)),
        model="mockllm/model",
        log_dir=str(log_dir),
        display="none",
        max_samples=1,
        task_retry_attempts=1,
        tamper_evident_store=evalhost_env.url,
    )[0]
    assert log.status == "success", log.error

    result = validate_cli(evalhost_env, log_dir)
    assert result.exit_code == 0, result.output
    assert "2 eval(s), 4 sample(s) compared, 0 finding(s)." in result.output


def test_eval_set_retry_validates(
    evalhost_env: MotoStore, tmp_path: Path, validate_cli: ValidateCli
) -> None:
    """eval_set retry: the second eval reuses s1 from the first.

    retry_cleanup=False keeps the failed attempt's .eval file.
    """
    failures = tmp_path / "failures.json"
    failures.write_text(json.dumps({"s0": 1}))
    log_dir = tmp_path / "logs"
    success, logs = eval_set(
        retried_task(str(failures)),
        log_dir=str(log_dir),
        model="mockllm/model",
        display="none",
        max_samples=1,
        retry_attempts=1,
        retry_cleanup=False,
        tamper_evident_store=evalhost_env.url,
    )
    assert success, logs[0].error

    result = validate_cli(evalhost_env, log_dir)
    assert result.exit_code == 0, result.output
    assert "2 eval(s), 4 sample(s) compared, 0 finding(s)." in result.output


def test_edit_reused_sample(
    evalhost_env: MotoStore, tmp_path: Path, validate_cli: ValidateCli
) -> None:
    """A retry's reused sample edited: compared with the earlier eval's records."""
    log = retried_task_run(evalhost_env, tmp_path, s0_failures=1)
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
    evalhost_env: MotoStore, tmp_path: Path, validate_cli: ValidateCli
) -> None:
    """A sample added to a retry's .eval: no eval in the chain ran it."""
    log = retried_task_run(evalhost_env, tmp_path, s0_failures=1)
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
    """An edited copy of the .eval file next to the original, with its eval id."""
    log = read_eval_log(clean_run.location)
    assert log.samples
    tool_event = next(e for e in log.samples[0].events if isinstance(e, ToolEvent))
    tool_event.result = "harmless"
    # the copy's name sorts after the original's (a date), which is compared
    write_eval_log(log, clean_run.log_dir / "copy.eval")
    result = validate_cli(clean_run.store, clean_run.log_dir)
    assert_fails_with(result, "duplicate_eval_file")
    assert f"duplicate_eval_file {clean_run.eval_id}:" in result.output


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


def test_rescore_fails_validation(
    clean_run: CleanRun, validate_cli: ValidateCli
) -> None:
    """`inspect score --action overwrite` after the run: fails validation today.

    Besides the scores and results, `inspect score` writes the sample's
    events again in span order, with the new scorers span in place of the
    old one, so the events differ too. How to report a rescore is not yet
    decided.
    """
    rescore = subprocess.run(
        [
            *[sys.executable, "-m", "inspect_ai", "score", str(clean_run.location)],
            *["--scorer", "match", "--overwrite", "--action", "overwrite"],
        ],
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
    )
    assert rescore.returncode == 0, rescore.stderr
    log = read_eval_log(clean_run.location)
    assert log.eval.eval_id == clean_run.eval_id
    assert log.samples and log.samples[0].scores
    assert set(log.samples[0].scores) == {"match"}

    result = validate_cli(clean_run.store, clean_run.log_dir)
    assert_fails_with(result, "score_mismatch", "eval_mismatch", "event_mismatch")


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


def test_forged_record_sequence_gap(
    clean_run: CleanRun, validate_cli: ValidateCli
) -> None:
    """A record added with a number past the next one."""
    seq = clean_run.records() + 5
    clean_run.put(clean_run.sample_key(seq), clean_run.forged_record(seq))
    result = validate_cli(clean_run.store, clean_run.log_dir)
    assert_fails_with(result, "nonce", "sequence_gap", "record_count")


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


def test_forged_event_without_uuid(
    clean_run: CleanRun, validate_cli: ValidateCli
) -> None:
    """A record with a row whose id is not its event's uuid."""
    seq = clean_run.records() + 1
    record = SampleRecord(
        eval_id=clean_run.eval_id,
        nonce=FORGED_NONCE,
        sample=SampleAttemptRef(sample_id="s0", epoch=1, attempt=1),
        seq=seq,
        rows=BufferRows(
            events=[
                BufferEventRow(
                    event_id="row-id",
                    data=InfoEvent(uuid="event-uuid", data="x").model_dump_json(),
                )
            ]
        ),
    )
    clean_run.put(clean_run.sample_key(seq), record.model_dump_json())
    result = validate_cli(clean_run.store, clean_run.log_dir)
    assert_fails_with(
        result, "nonce", "record_count", "event_without_uuid", "event_mismatch"
    )


@pytest.mark.parametrize("kind", ["not_json", "bad_event", "odd_key", "wrong_type"])
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
        case _:
            key = clean_run.sample_key(CLOSING, attempt=2)
            body = clean_run.read(f"{clean_run.eval_id}/{START}").decode()
    clean_run.put(key, body)
    result = validate_cli(clean_run.store, clean_run.log_dir)
    assert_fails_with(result, "malformed_record")
    assert f"malformed_record {key}:" in result.output
    assert ": :" not in result.output


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


def test_forged_record_in_parts(clean_run: CleanRun, validate_cli: ValidateCli) -> None:
    """A record added with a multipart upload, whose arrival time is its start."""
    seq = clean_run.records() + 1
    s3 = clean_run.store.client(clean_run.store.evalhost)
    key = f"{clean_run.store.prefix}/{clean_run.sample_key(seq)}"
    upload = s3.create_multipart_upload(Bucket=BUCKET, Key=key)["UploadId"]
    part = s3.upload_part(
        Bucket=BUCKET,
        Key=key,
        UploadId=upload,
        PartNumber=1,
        Body=clean_run.forged_record(seq),
    )
    s3.complete_multipart_upload(
        Bucket=BUCKET,
        Key=key,
        UploadId=upload,
        MultipartUpload={"Parts": [{"PartNumber": 1, "ETag": part["ETag"]}]},
        IfNoneMatch="*",
    )
    result = validate_cli(clean_run.store, clean_run.log_dir)
    assert_fails_with(result, "multipart", "nonce", "record_count")


def test_overwrite_record(clean_run: CleanRun, validate_cli: ValidateCli) -> None:
    """The .eval file edited, and the store record overwritten to match it.

    The eval host puts without If-None-Match. On real S3 the bucket policy
    refuses that put; moto does not enforce it, so a second version is added,
    usually in a later second than the first (the same second is
    `test_overwrite_in_same_second_reads_earliest`). The validator reads the
    earliest version.
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


class _SameSecondVersions:
    """An S3 client whose version listing gives every version one arrival time.

    S3 times have whole seconds, so versions stored in the same second look
    like this. Real S3 and moto list a key's versions newest first.
    """

    def __init__(self, client: Any) -> None:
        self._client = client

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)

    def get_paginator(self, name: str) -> Any:
        paginator = self._client.get_paginator(name)
        client = self

        class SameSecond:
            def paginate(self, **kwargs: Any) -> Iterator[dict[str, Any]]:
                for page in paginator.paginate(**kwargs):
                    for version in page.get("Versions", []):
                        version["LastModified"] = client.arrival
                    yield page

        return SameSecond()

    arrival = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_overwrite_in_same_second_reads_earliest(clean_run: CleanRun) -> None:
    """The validator reads a record's first version, also when both have one time."""
    key = clean_run.sample_key(1)
    record = SampleRecord.model_validate_json(clean_run.read(key))
    record.rows = BufferRows()
    clean_run.put(key, record.model_dump_json(), if_none_match=False)

    store = clean_run.store
    with store._policy_in_place():
        report = validate_store(
            store.url,
            str(clean_run.log_dir),
            client=_SameSecondVersions(store.client(store.validator)),
        )
    # the second version has no rows; read instead of the first, it would
    # leave the store without the sample's first events
    assert {f.kind for f in report.findings} == {"overwrite"}, report.findings


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
    assert_fails_with(result, "missing_closing")


def test_remove_last_record(clean_run: CleanRun, validate_cli: ValidateCli) -> None:
    clean_run.store.remove_version(clean_run.sample_key(clean_run.records()))
    result = validate_cli(clean_run.store, clean_run.log_dir)
    assert_fails_with(result, "record_count", "event_mismatch")


def test_remove_middle_record(clean_run: CleanRun, validate_cli: ValidateCli) -> None:
    clean_run.store.remove_version(clean_run.sample_key(2))
    result = validate_cli(clean_run.store, clean_run.log_dir)
    assert_fails_with(result, "sequence_gap", "record_count", "event_mismatch")


def test_remove_eval_closing(clean_run: CleanRun, validate_cli: ValidateCli) -> None:
    clean_run.store.remove_version(f"{clean_run.eval_id}/{CLOSING}")
    result = validate_cli(clean_run.store, clean_run.log_dir)
    assert_fails_with(result, "missing_eval_closing")


def test_remove_start(clean_run: CleanRun, validate_cli: ValidateCli) -> None:
    clean_run.store.remove_version(f"{clean_run.eval_id}/{START}")
    result = validate_cli(clean_run.store, clean_run.log_dir)
    assert_fails_with(result, "missing_start")


# ------------------------------------------------- store settings changed


def test_versioning_suspended(clean_run: CleanRun, validate_cli: ValidateCli) -> None:
    """Versioning suspended, so an overwrite would replace a record.

    Real S3 refuses this on an Object Lock bucket; moto allows it. (moto
    refuses to change the Object Lock mode of a bucket that holds objects,
    as real S3 does for COMPLIANCE, so that change is not tested.)
    """
    admin = clean_run.store.client(clean_run.store.admin)
    admin.put_bucket_versioning(
        Bucket=BUCKET, VersioningConfiguration={"Status": "Suspended"}
    )
    try:
        result = validate_cli(clean_run.store, clean_run.log_dir)
    finally:
        admin.put_bucket_versioning(
            Bucket=BUCKET, VersioningConfiguration={"Status": "Enabled"}
        )
    assert_fails_with(result, "settings")
    assert "Versioning is not enabled." in result.output


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
        tamper_evident_store=evalhost_env.url,
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
