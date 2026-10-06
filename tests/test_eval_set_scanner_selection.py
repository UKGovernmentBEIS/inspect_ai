"""Record-only scanning in eval-set selection (worker) mode.

Workers dispatch scanners per settled sample and write scout's per-transcript
buffer, and never touch the scan directory's lifecycle — no init, no finalize,
no orphan cleanup. The bracket belongs to the external runner: it lays the
directory down before any worker starts (`scan_init_from_spec`, from the
capture manifest's serialized spec) and compacts/finalizes as the single
writer (`scan_finalize(scanner=None)`).

The hazard these tests pin is the one that used to make scanner + selection a
hard error: a worker finalizing while a sibling's log had not landed computed
a live-transcripts set that omitted the sibling's samples, and pruned the
sibling's already-recorded rows.
"""

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from inspect_ai import Task, eval_set, task
from inspect_ai._eval.eval_set_manifest import (
    INSPECT_EVAL_SET_CAPTURE,
    EvalSetCapture,
)
from inspect_ai._eval.eval_set_selection import (
    EVAL_SET_SELECTION_VERSION,
    INSPECT_EVAL_SET_SELECTION,
    EvalSetSelection,
    EvalSetSelectionTask,
)
from inspect_ai._eval.task.scan import scan_finalize, scan_init_from_spec
from inspect_ai._util.error import PrerequisiteError
from inspect_ai.dataset import Sample
from inspect_ai.log import EvalLog, list_eval_logs, read_eval_log
from inspect_ai.scorer import exact
from inspect_ai.solver import generate

# inspect_scout is an optional runtime dep; skip these tests if unavailable.
# Guarding the imports rather than calling importorskip() first keeps them in
# the import block, where they don't read as out-of-order (E402).
try:
    from inspect_scout import Result, Transcript, scanner
    from inspect_scout._recorder.buffer import RecorderBuffer
    from inspect_scout._scancontext import _spec_scanners
except ImportError:
    pytest.skip("inspect_scout is not installed", allow_module_level=True)

MODEL = "mockllm/model"
EVAL_SET_ID = "scan-selection-test"


@task
def scan_selection_task_one() -> Task:
    return Task(
        dataset=[Sample(input="1+1", target="2"), Sample(input="2+2", target="4")],
        solver=[generate()],
        scorer=exact(),
    )


@task
def scan_selection_task_two() -> Task:
    return Task(
        dataset=[Sample(input="hello", target="hello")],
        solver=[generate()],
        scorer=exact(),
    )


@scanner(messages="all", name="sel_echo_scanner")
def sel_echo_scanner():
    async def scan(transcript: Transcript) -> Result:
        return Result(value=f"scanned:{transcript.transcript_id}")

    return scan


@scanner(messages="all", name="sel_injected_scanner")
def sel_injected_scanner():
    async def scan(transcript: Transcript) -> Result:
        return Result(value="injected")

    return scan


@scanner(messages="all", name="sel_param_scanner")
def sel_param_scanner(threshold: int = 1):
    async def scan(transcript: Transcript) -> Result:
        return Result(value=threshold)

    return scan


def _capture(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, **kwargs: Any
) -> EvalSetCapture:
    manifest_path = tmp_path / "manifest.json"
    monkeypatch.setenv(INSPECT_EVAL_SET_CAPTURE, str(manifest_path))
    try:
        with pytest.raises(SystemExit):
            eval_set(
                tasks=[scan_selection_task_one(), scan_selection_task_two()],
                model=MODEL,
                log_dir=str(tmp_path / "capture-logs"),
                display="plain",
                **kwargs,
            )
    finally:
        monkeypatch.delenv(INSPECT_EVAL_SET_CAPTURE)
    return EvalSetCapture.model_validate_json(manifest_path.read_bytes())


def _run_worker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    selection: EvalSetSelection,
    log_dir: Path,
    *,
    name: str,
    **kwargs: Any,
) -> tuple[bool, list[EvalLog]]:
    selection_path = tmp_path / f"{name}.json"
    selection_path.write_text(selection.model_dump_json())
    monkeypatch.setenv(INSPECT_EVAL_SET_SELECTION, str(selection_path))
    try:
        return eval_set(
            tasks=[scan_selection_task_one(), scan_selection_task_two()],
            model=MODEL,
            log_dir=str(log_dir),
            display="plain",
            **kwargs,
        )
    finally:
        monkeypatch.delenv(INSPECT_EVAL_SET_SELECTION)


def _selection(identifier: str, **kwargs: Any) -> EvalSetSelection:
    return EvalSetSelection(
        version=EVAL_SET_SELECTION_VERSION,
        eval_set_id=EVAL_SET_ID,
        tasks=[EvalSetSelectionTask(identifier=identifier)],
        **kwargs,
    )


def _identifier(capture: EvalSetCapture, task_name: str) -> str:
    return next(t.identifier for t in capture.tasks if t.name == task_name)


def _scan_dir(log_dir: Path) -> Path:
    return log_dir / "scans" / f"scan_id={EVAL_SET_ID}"


def _buffer_stems(scan_dir: Path, scanner_name: str) -> set[str]:
    sdir = RecorderBuffer.buffer_dir(str(scan_dir)) / f"scanner={scanner_name}"
    if not sdir.exists():
        return set()
    return {p.stem for p in sdir.glob("*.parquet")}


def _complete_flag(scan_dir: Path) -> bool:
    summary = scan_dir / "_summary.json"
    if not summary.exists():
        return False
    return bool(json.loads(summary.read_text()).get("complete"))


def _parquet_transcript_ids(scan_dir: Path, scanner_name: str) -> set[str]:
    import pyarrow.parquet as pq

    path = scan_dir / f"{scanner_name}.parquet"
    if not path.exists():
        return set()
    pf = pq.ParquetFile(str(path))
    ids: set[str] = set()
    for i in range(pf.metadata.num_row_groups):
        rg = pf.read_row_group(i, columns=["transcript_id"])
        ids.update(t for t in rg.column("transcript_id").to_pylist() if t)
    return ids


def test_capture_serializes_the_scan_spec(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    capture = _capture(
        monkeypatch, tmp_path, scanner={"sel_echo_scanner": sel_echo_scanner()}
    )
    assert capture.options["scanners"] is True
    assert capture.scan is not None
    assert set(capture.scan.spec["scanners"].keys()) == {"sel_echo_scanner"}
    # the inspect-side config hash rides in the spec's metadata, so a runner
    # can verify a re-launch without reconstructing scanner objects
    assert "__inspect_scan_config_hash__" in capture.scan.spec["metadata"]
    # no `scans` redirect was declared, so the runner resolves the default
    # under its own log_dir (which capture cannot compute)
    assert capture.scan.scans is None


def test_capture_without_scanner_has_no_scan_field(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    capture = _capture(monkeypatch, tmp_path)
    assert capture.options["scanners"] is False
    assert capture.scan is None


def test_selection_scanning_is_record_only_and_the_runner_brackets(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The whole lifecycle, in the order a runner performs it.

    Worker B lands a log and its scan rows, and the log is then deleted —
    the shape a superseded attempt has. Worker A then runs to completion:
    under the old in-worker lifecycle its finalize would have pruned B's
    rows; record-only must delete nothing and finalize nothing. The
    runner's own finalize then does both halves correctly from the spec
    alone: keeps A's rows, prunes B's, marks complete.
    """
    capture = _capture(
        monkeypatch, tmp_path, scanner={"sel_echo_scanner": sel_echo_scanner()}
    )
    assert capture.scan is not None
    log_dir = tmp_path / "logs"
    log_dir.mkdir()

    # the runner's init, from the captured spec
    scan_dir = Path(
        asyncio.run(
            scan_init_from_spec(
                capture.scan.spec,
                scan_id=EVAL_SET_ID,
                log_dir=str(log_dir),
                scans=capture.scan.scans,
            )
        )
    )
    assert (scan_dir / "_scan.json").exists()
    assert scan_dir == _scan_dir(log_dir)

    # worker B: one sample, log lands, then is deleted (a superseded shape)
    success, _ = _run_worker(
        monkeypatch,
        tmp_path,
        _selection(_identifier(capture, "scan_selection_task_two")),
        log_dir,
        name="worker-b",
        scanner={"sel_echo_scanner": sel_echo_scanner()},
    )
    assert success
    b_stems = _buffer_stems(scan_dir, "sel_echo_scanner")
    assert len(b_stems) == 1
    for info in list_eval_logs(str(log_dir)):
        Path(info.name.replace("file://", "")).unlink()

    # worker A: completes with B's rows orphaned in the buffer. Record-only
    # means no compacted parquet, no complete flag, and B's rows intact.
    success, logs_a = _run_worker(
        monkeypatch,
        tmp_path,
        _selection(_identifier(capture, "scan_selection_task_one")),
        log_dir,
        name="worker-a",
        scanner={"sel_echo_scanner": sel_echo_scanner()},
    )
    assert success
    log_a = read_eval_log(logs_a[0].location)
    a_uuids = {s.uuid for s in (log_a.samples or [])}
    assert len(a_uuids) == 2
    stems = _buffer_stems(scan_dir, "sel_echo_scanner")
    assert stems == a_uuids | b_stems
    assert not (scan_dir / "sel_echo_scanner.parquet").exists()
    assert not _complete_flag(scan_dir)

    # the runner's finalize: no scanner objects, names from _scan.json.
    # A's rows survive, B's orphans are pruned, the scan reads complete.
    asyncio.run(scan_finalize(scan_id=EVAL_SET_ID, log_dir=str(log_dir), scanner=None))
    assert _parquet_transcript_ids(scan_dir, "sel_echo_scanner") == a_uuids
    assert _complete_flag(scan_dir)
    assert _buffer_stems(scan_dir, "sel_echo_scanner") == set()

    # a re-launch attaches rather than resets: the finalized flag is
    # invalidated for the new run and the transcripts snapshot survives
    asyncio.run(
        scan_init_from_spec(
            capture.scan.spec,
            scan_id=EVAL_SET_ID,
            log_dir=str(log_dir),
            scans=capture.scan.scans,
        )
    )
    assert not _complete_flag(scan_dir)
    spec = json.loads((scan_dir / "_scan.json").read_text())
    assert spec.get("transcripts") is not None
    assert _parquet_transcript_ids(scan_dir, "sel_echo_scanner") == a_uuids


def test_selection_scanning_refuses_without_scan_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    capture = _capture(
        monkeypatch, tmp_path, scanner={"sel_echo_scanner": sel_echo_scanner()}
    )
    with pytest.raises(PrerequisiteError, match="scan directory"):
        _run_worker(
            monkeypatch,
            tmp_path,
            _selection(_identifier(capture, "scan_selection_task_one")),
            tmp_path / "logs",
            name="worker",
            scanner={"sel_echo_scanner": sel_echo_scanner()},
        )


def test_injected_scanners_run_in_a_definition_that_declares_none(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    capture = _capture(monkeypatch, tmp_path)
    assert capture.scan is None
    log_dir = tmp_path / "logs"
    log_dir.mkdir()

    # the runner-built spec: injected scanners only, in ScannerSpec form
    injected = {
        name: spec.model_dump(mode="json", exclude_none=True)
        for name, spec in _spec_scanners(
            {"sel_injected_scanner": sel_injected_scanner()}
        ).items()
    }
    scan_dir = Path(
        asyncio.run(
            scan_init_from_spec(
                {"scan_name": "eval_set", "scanners": injected},
                scan_id=EVAL_SET_ID,
                log_dir=str(log_dir),
            )
        )
    )

    success, logs = _run_worker(
        monkeypatch,
        tmp_path,
        _selection(_identifier(capture, "scan_selection_task_two"), scanners=injected),
        log_dir,
        name="worker",
    )
    assert success
    assert len(_buffer_stems(scan_dir, "sel_injected_scanner")) == 1


def _init_from(capture: EvalSetCapture, log_dir: Path) -> Path:
    assert capture.scan is not None
    return Path(
        asyncio.run(
            scan_init_from_spec(
                capture.scan.spec,
                scan_id=EVAL_SET_ID,
                log_dir=str(log_dir),
                scans=capture.scan.scans,
            )
        )
    )


def test_a_drifted_scanner_refuses_at_worker_startup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A changed scanner refuses at worker startup.

    The runner verified the configuration it captured, but a worker executes
    the definition file as it stands at spawn time — a scanner changed between
    the two must refuse rather than record rows the on-disk spec misdescribes.
    """
    capture = _capture(
        monkeypatch,
        tmp_path,
        scanner={"sel_param_scanner": sel_param_scanner(threshold=1)},
    )
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    _init_from(capture, log_dir)
    with pytest.raises(PrerequisiteError, match="sel_param_scanner"):
        _run_worker(
            monkeypatch,
            tmp_path,
            _selection(_identifier(capture, "scan_selection_task_one")),
            log_dir,
            name="worker",
            scanner={"sel_param_scanner": sel_param_scanner(threshold=2)},
        )


def test_a_drifted_scanner_set_refuses_at_worker_startup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A changed scanner set refuses at worker startup.

    A worker cannot admit a scanner the runner never wrote into the spec —
    recording for it would leave rows the scan disowns.
    """
    capture = _capture(
        monkeypatch, tmp_path, scanner={"sel_echo_scanner": sel_echo_scanner()}
    )
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    _init_from(capture, log_dir)
    with pytest.raises(PrerequisiteError, match="Scanner set"):
        _run_worker(
            monkeypatch,
            tmp_path,
            _selection(_identifier(capture, "scan_selection_task_one")),
            log_dir,
            name="worker",
            scanner={
                "sel_echo_scanner": sel_echo_scanner(),
                "sel_param_scanner": sel_param_scanner(),
            },
        )


def test_a_drifted_scanner_config_refuses_at_worker_startup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A changed eval-set-level config refuses at worker startup.

    The config wrapper (filter, scan-side model, ...) lives in no
    `ScannerSpec` — the hash the spec's metadata carries is what catches it.
    """
    from inspect_ai import ScannerConfig

    capture = _capture(
        monkeypatch, tmp_path, scanner={"sel_echo_scanner": sel_echo_scanner()}
    )
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    _init_from(capture, log_dir)
    with pytest.raises(PrerequisiteError, match="config"):
        _run_worker(
            monkeypatch,
            tmp_path,
            _selection(_identifier(capture, "scan_selection_task_one")),
            log_dir,
            name="worker",
            scanner=ScannerConfig(
                scanners={"sel_echo_scanner": sel_echo_scanner()},
                filter="1 = 1",
            ),
        )


def test_package_version_drift_is_tolerated_at_worker_startup(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`package_version` drift alone does not refuse.

    It is provenance rather than identity: under a development install it
    moves with every commit while the scanner remains the same scanner, and
    a worker spawned after a reinstall must still start.
    """
    capture = _capture(
        monkeypatch, tmp_path, scanner={"sel_echo_scanner": sel_echo_scanner()}
    )
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    scan_dir = _init_from(capture, log_dir)

    scan_json = scan_dir / "_scan.json"
    spec = json.loads(scan_json.read_text())
    spec["scanners"]["sel_echo_scanner"]["package_version"] = "0.0.0"
    scan_json.write_text(json.dumps(spec))

    success, _ = _run_worker(
        monkeypatch,
        tmp_path,
        _selection(_identifier(capture, "scan_selection_task_one")),
        log_dir,
        name="worker",
        scanner={"sel_echo_scanner": sel_echo_scanner()},
    )
    assert success


def test_injected_scanner_name_collision_is_refused(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    capture = _capture(
        monkeypatch, tmp_path, scanner={"sel_echo_scanner": sel_echo_scanner()}
    )
    injected = {
        name: spec.model_dump(mode="json", exclude_none=True)
        for name, spec in _spec_scanners(
            {"sel_echo_scanner": sel_echo_scanner()}
        ).items()
    }
    with pytest.raises(PrerequisiteError, match="collide"):
        _run_worker(
            monkeypatch,
            tmp_path,
            _selection(
                _identifier(capture, "scan_selection_task_one"), scanners=injected
            ),
            tmp_path / "logs",
            name="worker",
            scanner={"sel_echo_scanner": sel_echo_scanner()},
        )
