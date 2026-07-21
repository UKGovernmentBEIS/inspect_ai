import json
import time
from pathlib import Path
from typing import Any

import pytest

from inspect_ai._cli.trace import anomalies_command_impl, http_command_impl


def write_trace_log(file: Path, records: list[dict[str, Any]]) -> None:
    with open(file, "w") as f:
        for record in records:
            f.write(json.dumps(record) + "\n")


def action_record(
    trace_id: str,
    action: str,
    event: str,
    *,
    detail: str = "",
    start_time: float | None = None,
    duration: float | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "timestamp": "2026-07-16T12:00:00+00:00",
        "level": "TRACE",
        "message": f"{action}: {detail} ({event})",
        "action": action,
        "detail": detail,
        "event": event,
        "trace_id": trace_id,
    }
    if start_time is not None:
        record["start_time"] = start_time
    if duration is not None:
        record["duration"] = duration
    if error is not None:
        record["error"] = error
    return record


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
