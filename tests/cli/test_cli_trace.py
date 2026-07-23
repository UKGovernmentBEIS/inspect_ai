import json
import time
from pathlib import Path
from typing import Any

import pytest
from test_helpers.trace import action_record, write_trace_log

from inspect_ai._cli.trace import anomalies_command_impl, http_command_impl


@pytest.fixture
def anomalies_trace_file(tmp_path: Path) -> Path:
    start = time.time() - 120
    trace_file = tmp_path / "trace-123.log"
    write_trace_log(
        trace_file,
        [
            # still running (enter, never exited)
            action_record(
                "run1", "Model", "enter", detail="generate", start_time=start
            ),
            # cancelled
            action_record(
                "can1", "Subprocess", "enter", detail="bash", start_time=start
            ),
            action_record("can1", "Subprocess", "cancel", detail="bash", duration=5.0),
            # errored
            action_record("err1", "Sandbox", "enter", detail="exec", start_time=start),
            action_record(
                "err1", "Sandbox", "error", detail="exec", duration=7.0, error="boom"
            ),
            # timed out
            action_record(
                "tmo1", "Model", "enter", detail="generate", start_time=start
            ),
            action_record("tmo1", "Model", "timeout", detail="generate", duration=9.0),
            # completed normally (should never appear)
            action_record("ok1", "Log", "enter", detail="write", start_time=start),
            action_record("ok1", "Log", "exit", detail="write", duration=1.0),
        ],
    )
    return trace_file


def test_trace_anomalies_json(
    anomalies_trace_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    anomalies_command_impl(
        str(anomalies_trace_file),
        filter=None,
        all=False,
        json=True,
        trace_dir=anomalies_trace_file.parent,
    )
    envelope = json.loads(capsys.readouterr().out)

    assert envelope["trace_file"] == anomalies_trace_file.as_posix()
    assert isinstance(envelope["as_of"], float)

    # all four buckets always populated, even without --all (which gates only
    # the human rendering), so empty always means "none occurred"
    assert [row["action"] for row in envelope["running"]] == ["Model"]
    assert [row["action"] for row in envelope["cancelled"]] == ["Subprocess"]
    assert [row["action"] for row in envelope["errors"]] == ["Sandbox"]
    assert [row["action"] for row in envelope["timeouts"]] == ["Model"]

    # running rows compute duration as as_of - start_time
    running = envelope["running"][0]
    assert running["detail"] == "generate"
    assert running["duration"] == pytest.approx(
        envelope["as_of"] - running["start_time"]
    )
    assert "error" not in running

    # finished rows carry the recorded duration and the enter start_time
    cancelled = envelope["cancelled"][0]
    assert cancelled["duration"] == 5.0
    assert cancelled["start_time"] is not None


def test_trace_anomalies_json_all(
    anomalies_trace_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    anomalies_command_impl(
        str(anomalies_trace_file),
        filter=None,
        all=True,
        json=True,
        trace_dir=anomalies_trace_file.parent,
    )
    envelope = json.loads(capsys.readouterr().out)

    assert [row["action"] for row in envelope["errors"]] == ["Sandbox"]
    assert envelope["errors"][0]["error"] == "boom"
    assert [row["action"] for row in envelope["timeouts"]] == ["Model"]
    assert envelope["timeouts"][0]["duration"] == 9.0


def test_trace_anomalies_json_empty(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    trace_file = tmp_path / "trace-456.log"
    write_trace_log(
        trace_file,
        [
            action_record("ok1", "Log", "enter", detail="write", start_time=1.0),
            action_record("ok1", "Log", "exit", detail="write", duration=1.0),
        ],
    )
    anomalies_command_impl(
        str(trace_file), filter=None, all=False, json=True, trace_dir=tmp_path
    )
    envelope = json.loads(capsys.readouterr().out)

    # the envelope is emitted (not the human "no anomalies" prose), with all
    # bucket keys present as empty lists
    assert envelope["running"] == []
    assert envelope["cancelled"] == []
    assert envelope["errors"] == []
    assert envelope["timeouts"] == []


def test_trace_anomalies_human_output(
    anomalies_trace_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    anomalies_command_impl(
        str(anomalies_trace_file),
        filter=None,
        all=False,
        json=False,
        trace_dir=anomalies_trace_file.parent,
    )
    out = capsys.readouterr().out
    assert "Running Actions" in out
    assert "Cancelled Actions" in out
    # errors/timeouts are gated behind --all in the human rendering
    assert "Error Actions" not in out
    assert "Timeout Actions" not in out


def test_trace_anomalies_human_output_all(
    anomalies_trace_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    anomalies_command_impl(
        str(anomalies_trace_file),
        filter=None,
        all=True,
        json=False,
        trace_dir=anomalies_trace_file.parent,
    )
    out = capsys.readouterr().out
    assert "Error Actions" in out
    assert "Timeout Actions" in out


def test_trace_anomalies_filter_matches_only_exit_record(
    anomalies_trace_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # "(error)" matches only the error (exit-side) record, not its enter
    # record; the reconstruction must tolerate the missing enter, not crash
    anomalies_command_impl(
        str(anomalies_trace_file),
        filter="(error)",
        all=True,
        json=True,
        trace_dir=anomalies_trace_file.parent,
    )
    envelope = json.loads(capsys.readouterr().out)
    assert [row["action"] for row in envelope["errors"]] == ["Sandbox"]
    assert envelope["errors"][0]["start_time"] is None


def test_trace_anomalies_tolerates_truncated_final_line(
    anomalies_trace_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A truncated final line (hard kill, or read mid-write) is skipped.

    `read_trace_file` must report the intact records rather than fail the
    whole read on the partial one.
    """
    with open(anomalies_trace_file, "a") as f:
        f.write('{"timestamp": "2026-07-16T12:0')
    anomalies_command_impl(
        str(anomalies_trace_file),
        filter=None,
        all=False,
        json=True,
        trace_dir=anomalies_trace_file.parent,
    )
    envelope = json.loads(capsys.readouterr().out)
    assert [row["action"] for row in envelope["running"]] == ["Model"]


def test_trace_anomalies_skips_records_failing_validation(
    anomalies_trace_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A record with an event verb this version doesn't know is skipped.

    A trace file written by a newer inspect may carry new event types;
    `read_trace_file` reports the intact records (noting the skip on
    stderr) rather than failing the whole read.
    """
    with open(anomalies_trace_file, "a") as f:
        f.write(json.dumps(action_record("new1", "Model", "frobnicate")) + "\n")
    anomalies_command_impl(
        str(anomalies_trace_file),
        filter=None,
        all=False,
        json=True,
        trace_dir=anomalies_trace_file.parent,
    )
    captured = capsys.readouterr()
    envelope = json.loads(captured.out)
    assert [row["action"] for row in envelope["running"]] == ["Model"]
    assert "skipped 1 trace record" in captured.err
    assert "event" in captured.err


def test_trace_anomalies_unknown_event_goes_to_stderr(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An unrecognized action event warns on stderr, keeping stdout envelope-safe.

    Not reachable through `read_trace_file` (it skips records that fail
    validation), so construct the record directly; the contract under test
    is that `trace_anomalies` never writes prose to stdout, where it would
    corrupt a `--json` envelope.
    """
    from inspect_ai._cli.trace import trace_anomalies
    from inspect_ai._util.trace import ActionTraceRecord

    record = ActionTraceRecord.model_construct(
        timestamp="2026-07-16T12:00:00+00:00",
        level="TRACE",
        message="Model: generate (frobnicate)",
        action="Model",
        event="frobnicate",
        trace_id="x1",
    )
    anomalies = trace_anomalies([record])
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Unknown event type: frobnicate" in captured.err
    assert anomalies == ([], [], [], [])


def http_record(timestamp: str, message: str) -> dict[str, Any]:
    return {"timestamp": timestamp, "level": "HTTP", "message": message}


def test_trace_http_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    trace_file = tmp_path / "trace-789.log"
    write_trace_log(
        trace_file,
        [
            http_record("2026-07-16T12:00:00+00:00", "POST https://api - 200 OK"),
            http_record("2026-07-16T12:00:01+00:00", "POST https://api - 429"),
        ],
    )

    http_command_impl(
        str(trace_file), filter=None, failed=False, json=True, trace_dir=tmp_path
    )
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["trace_file"] == trace_file.as_posix()
    assert isinstance(envelope["as_of"], float)
    assert [request["message"] for request in envelope["requests"]] == [
        "POST https://api - 200 OK",
        "POST https://api - 429",
    ]

    # --failed drops 200 OK requests from the JSON output too
    http_command_impl(
        str(trace_file), filter=None, failed=True, json=True, trace_dir=tmp_path
    )
    envelope = json.loads(capsys.readouterr().out)
    assert [request["message"] for request in envelope["requests"]] == [
        "POST https://api - 429"
    ]
