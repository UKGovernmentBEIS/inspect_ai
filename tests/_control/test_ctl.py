"""Unit tests for `inspect ctl` target resolution (id + name matching)."""

from typing import Any

import click
import pytest

from inspect_ai._cli.ctl import (
    _print_keep_alive_footer,
    _print_samples_table,
    _resolve_target_eval,
    _resolve_target_server,
)
from inspect_ai._control.discovery import DiscoveredControlServer


def _summary(task_id: str, task: str) -> dict[str, str]:
    return {"task_id": task_id, "task": task, "eval_id": f"eval_{task_id}"}


def test_name_match_is_anchored_at_start_or_after_slash() -> None:
    # `gpqa` matches the leaf of inspect_evals/gpqa_diamond, but not the
    # mid-name `failing_gpqa_diamond`.
    summaries = [
        _summary("aaa111", "inspect_evals/gpqa_diamond"),
        _summary("bbb222", "failing_gpqa_diamond"),
    ]
    assert _resolve_target_eval(summaries, "gpqa")["task_id"] == "aaa111"


def test_name_match_at_start_of_name() -> None:
    summaries = [
        _summary("aaa111", "inspect_evals/gpqa_diamond"),
        _summary("bbb222", "failing_gpqa_diamond"),
    ]
    assert _resolve_target_eval(summaries, "failing")["task_id"] == "bbb222"


def test_task_id_takes_precedence_over_name() -> None:
    # `gpqa` is a prefix of task_id "gpqaID" → resolve by id, not by the
    # name match on the other entry.
    summaries = [
        _summary("gpqaID", "something_else"),
        _summary("zzz999", "gpqa_diamond"),
    ]
    assert _resolve_target_eval(summaries, "gpqa")["task_id"] == "gpqaID"


def test_exact_name_preferred_over_prefix() -> None:
    summaries = [_summary("aaa111", "gpqa"), _summary("bbb222", "gpqa_diamond")]
    assert _resolve_target_eval(summaries, "gpqa")["task_id"] == "aaa111"


def test_ambiguous_name_exits(capsys: pytest.CaptureFixture[str]) -> None:
    # Same task against two models → two ids, same name → ambiguous.
    summaries = [
        _summary("aaa111", "inspect_evals/gpqa_diamond"),
        _summary("bbb222", "inspect_evals/gpqa_diamond"),
    ]
    with pytest.raises(click.exceptions.Exit):
        _resolve_target_eval(summaries, "gpqa")
    err = capsys.readouterr().err
    assert "matches multiple tasks" in err
    assert "aaa111" in err and "bbb222" in err


def test_no_match_exits(capsys: pytest.CaptureFixture[str]) -> None:
    summaries = [_summary("aaa111", "inspect_evals/gpqa_diamond")]
    with pytest.raises(click.exceptions.Exit):
        _resolve_target_eval(summaries, "nope")
    assert "No running task matching 'nope'" in capsys.readouterr().err


def test_default_to_sole_task() -> None:
    summaries = [_summary("aaa111", "only_task")]
    assert _resolve_target_eval(summaries, None)["task_id"] == "aaa111"


def test_no_query_with_multiple_exits(capsys: pytest.CaptureFixture[str]) -> None:
    summaries = [_summary("aaa111", "t1"), _summary("bbb222", "t2")]
    with pytest.raises(click.exceptions.Exit):
        _resolve_target_eval(summaries, None)
    assert "Multiple tasks are running" in capsys.readouterr().err


def _sample(
    sample_id: int, status: str, scores: dict[str, object]
) -> dict[str, object]:
    return {
        "sample_id": sample_id,
        "epoch": 1,
        "status": status,
        "total_time": 1.0,
        "total_tokens": 0,
        "message_count": 1,
        "scores": scores,
    }


def test_score_column_shown_for_single_scorer(
    capsys: pytest.CaptureFixture[str],
) -> None:
    samples = [
        _sample(1, "completed", {"match": "C"}),
        _sample(2, "running", {}),  # not scored yet → blank cell
    ]
    _print_samples_table(samples)
    out = capsys.readouterr().out
    lines = out.splitlines()
    assert "score" in lines[0]  # header row has the column
    # The completed sample shows its score; the running one is blank.
    completed_row = next(ln for ln in lines if ln.startswith("1 "))
    assert "C" in completed_row


def test_score_column_hidden_for_multiple_scorers(
    capsys: pytest.CaptureFixture[str],
) -> None:
    samples = [_sample(1, "completed", {"match": "C", "f1": 0.5})]
    _print_samples_table(samples)
    assert "score" not in capsys.readouterr().out.splitlines()[0]


def test_score_column_hidden_when_no_scores(
    capsys: pytest.CaptureFixture[str],
) -> None:
    samples = [_sample(1, "running", {})]
    _print_samples_table(samples)
    assert "score" not in capsys.readouterr().out.splitlines()[0]


def test_idle_column_shown_and_populated_for_running(
    capsys: pytest.CaptureFixture[str],
) -> None:
    import time

    now = time.time()
    samples = [
        {**_sample(1, "running", {}), "last_activity_at": now - 3661},
        {**_sample(2, "completed", {}), "last_activity_at": now - 10},
    ]
    _print_samples_table(samples)
    lines = capsys.readouterr().out.splitlines()
    assert "idle" in lines[0]  # column shown because a sample is running
    running_row = next(ln for ln in lines if ln.startswith("1 "))
    assert "1:01:0" in running_row  # ~3661s of idle on the running sample
    # idle is a running-only signal; the completed row carries no idle duration
    completed_row = next(ln for ln in lines if ln.startswith("2 "))
    assert "1:01:0" not in completed_row


def test_idle_column_hidden_when_nothing_running(
    capsys: pytest.CaptureFixture[str],
) -> None:
    samples = [{**_sample(1, "completed", {}), "last_activity_at": 100.0}]
    _print_samples_table(samples)
    assert "idle" not in capsys.readouterr().out.splitlines()[0]


def test_sorted_samples_orders_running_then_terminal_then_pending() -> None:
    from inspect_ai._control.state import _sorted_samples

    rows: list[dict[str, Any]] = [
        {"status": "pending", "started_at": None},
        {"status": "completed", "started_at": 100.0},
        {"status": "running", "started_at": 200.0},
        {"status": "error", "started_at": 50.0},
    ]
    ordered = [r["status"] for r in _sorted_samples(rows)]
    # running first; terminal (completed/error) by start time; pending last.
    assert ordered == ["running", "error", "completed", "pending"]


def test_retries_column_shown_when_a_sample_retried(
    capsys: pytest.CaptureFixture[str],
) -> None:
    samples = [
        {**_sample(1, "completed", {}), "retries": 2},
        {**_sample(2, "completed", {}), "retries": 0},  # no retries → blank cell
    ]
    _print_samples_table(samples)
    lines = capsys.readouterr().out.splitlines()
    assert "retries" in lines[0]  # header row has the column
    retried_row = next(ln for ln in lines if ln.startswith("1 "))
    assert "2" in retried_row


def test_retries_column_hidden_when_no_retries(
    capsys: pytest.CaptureFixture[str],
) -> None:
    samples = [{**_sample(1, "completed", {}), "retries": 0}]
    _print_samples_table(samples)
    assert "retries" not in capsys.readouterr().out.splitlines()[0]


def test_sample_detail_shows_prior_attempts_message_only(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from inspect_ai._cli.ctl import _print_sample_detail

    detail = {
        "sample_id": "recABC",
        "epoch": 1,
        "status": "completed",
        "retries": 2,
        "error": None,
        "error_retries": [
            {"message": "RuntimeError('boom 1')", "traceback_ansi": "TB-ONE"},
            {"message": "RuntimeError('boom 2')", "traceback_ansi": "TB-TWO"},
        ],
        "scores": {},
    }
    _print_sample_detail(detail, show_traceback=False)
    out = capsys.readouterr().out
    assert "prior attempts" in out
    assert "attempt 1: RuntimeError('boom 1')" in out
    assert "attempt 2: RuntimeError('boom 2')" in out
    # message-only by default — no traceback bodies
    assert "TB-ONE" not in out and "TB-TWO" not in out


def test_sample_detail_traceback_flag_expands(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from inspect_ai._cli.ctl import _print_sample_detail

    detail = {
        "sample_id": 1,
        "epoch": 1,
        "status": "error",
        "retries": 0,
        "error": {"message": "ValueError('nope')", "traceback_ansi": "TRACE-BODY"},
        "error_retries": [],
        "scores": {},
    }
    _print_sample_detail(detail, show_traceback=True)
    out = capsys.readouterr().out
    assert "final error" in out
    assert "ValueError('nope')" in out
    assert "TRACE-BODY" in out


def test_sample_detail_no_errors(capsys: pytest.CaptureFixture[str]) -> None:
    from inspect_ai._cli.ctl import _print_sample_detail

    detail = {
        "sample_id": 1,
        "epoch": 1,
        "status": "completed",
        "retries": 0,
        "error": None,
        "error_retries": [],
        "scores": {},
    }
    _print_sample_detail(detail, show_traceback=False)
    assert "(no errors)" in capsys.readouterr().out


def test_errors_table_lists_retried_and_errored(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from inspect_ai._cli.ctl import _print_errors_table

    samples = [
        {
            "sample_id": "recABC",
            "epoch": 1,
            "status": "completed",
            "retries": 1,
            "error": None,
        },
        {
            "sample_id": 2,
            "epoch": 1,
            "status": "error",
            "retries": 0,
            "error": "TimeoutError('slow')",
        },
    ]
    _print_errors_table(samples)
    out = capsys.readouterr().out
    assert "recABC" in out
    assert "TimeoutError('slow')" in out
    assert "retries" in out.splitlines()[0]


def test_print_events_table_and_footer(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from inspect_ai._cli.ctl import _print_events

    page = {
        "events": [
            {
                "event": "model",
                "timestamp": 1000.0,
                "model": "openai/gpt",
                "tokens": 42,
                "stop_reason": "stop",
                "completion": "hello",
            },
            {
                "event": "tool",
                "timestamp": 1001.0,
                "function": "bash",
                "arguments": "ls",
                "result": "files",
            },
            {"event": "error", "timestamp": 1002.0, "error": "boom"},
        ],
        "next": "CURSORX",
        "done": False,
    }
    _print_events(page)
    out = capsys.readouterr().out
    assert "event" in out.splitlines()[0]  # table header
    # per-type summaries
    assert "openai/gpt" in out and "bash" in out and "boom" in out
    # footer: count, "more" (not done), and the resume cursor
    assert "3 events" in out
    assert "more" in out
    assert "next: CURSORX" in out


def test_print_events_empty_and_done(capsys: pytest.CaptureFixture[str]) -> None:
    from inspect_ai._cli.ctl import _print_events

    _print_events({"events": [], "next": "X", "done": True})
    out = capsys.readouterr().out
    assert "(no events)" in out
    assert "done" in out
    assert "next:" not in out  # a done stream offers no resume cursor


def test_keep_alive_footer_on_when_all_tasks_keep_alive(
    capsys: pytest.CaptureFixture[str],
) -> None:
    summaries = [{"keep_alive": True}, {"keep_alive": True}]
    _print_keep_alive_footer(summaries)
    assert "keep-alive: on" in capsys.readouterr().out


def test_keep_alive_footer_off_hints_keep_command(
    capsys: pytest.CaptureFixture[str],
) -> None:
    summaries = [{"keep_alive": False}, {"keep_alive": False}]
    _print_keep_alive_footer(summaries)
    out = capsys.readouterr().out
    assert "keep-alive: off" in out
    # off everywhere → hint at the command that turns it on
    assert "inspect ctl keep" in out


def test_keep_alive_footer_off_when_field_absent(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # An older server may omit keep_alive entirely — treated as off.
    _print_keep_alive_footer([{}, {}])
    assert "keep-alive: off" in capsys.readouterr().out


def test_keep_alive_footer_mixed_reports_counts(
    capsys: pytest.CaptureFixture[str],
) -> None:
    summaries = [{"keep_alive": True}, {"keep_alive": False}, {"keep_alive": False}]
    _print_keep_alive_footer(summaries)
    out = capsys.readouterr().out
    assert "keep-alive: mixed" in out
    assert "1/3 on" in out


class _FakeServer:
    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.socket_path = f"/tmp/{pid}.sock"


def test_resolve_target_server_defaults_to_sole_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "inspect_ai._cli.ctl.list_discovered_servers", lambda: [_FakeServer(7)]
    )
    assert _resolve_target_server(None).pid == 7


def test_resolve_target_server_matches_pid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    servers = [_FakeServer(7), _FakeServer(8)]
    monkeypatch.setattr("inspect_ai._cli.ctl.list_discovered_servers", lambda: servers)
    assert _resolve_target_server(8).pid == 8


def test_resolve_target_server_ambiguous_exits(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    servers = [_FakeServer(7), _FakeServer(8)]
    monkeypatch.setattr("inspect_ai._cli.ctl.list_discovered_servers", lambda: servers)
    with pytest.raises(click.exceptions.Exit):
        _resolve_target_server(None)
    err = capsys.readouterr().err
    assert "Multiple inspect processes" in err
    assert "7" in err and "8" in err


def test_resolve_target_server_unknown_pid_exits(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "inspect_ai._cli.ctl.list_discovered_servers", lambda: [_FakeServer(7)]
    )
    with pytest.raises(click.exceptions.Exit):
        _resolve_target_server(99)
    assert "No running inspect process with pid 99" in capsys.readouterr().err


def test_resolve_target_server_none_running_exits(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("inspect_ai._cli.ctl.list_discovered_servers", lambda: [])
    with pytest.raises(click.exceptions.Exit):
        _resolve_target_server(None)
    assert "No running inspect processes found" in capsys.readouterr().err


# --- read timeout / retry behavior (issue #14) -----------------------------


def _stub_httpx(
    monkeypatch: pytest.MonkeyPatch, sequence: list[object]
) -> dict[str, int]:
    """Replace httpx in ctl so each ``client.get`` consumes one ``sequence`` item.

    Each item is either an ``Exception`` to raise (e.g. a ``TimeoutException``)
    or a payload to return from ``response.json()``. Returns a dict whose
    ``"gets"`` entry counts how many requests were attempted.
    """
    counter = {"gets": 0}
    seq = list(sequence)

    class _Resp:
        def __init__(self, payload: object) -> None:
            self._payload = payload

        def raise_for_status(self) -> None:
            pass

        def json(self) -> object:
            return self._payload

    class _Client:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def __enter__(self) -> "_Client":
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def get(self, path: str, params: object = None) -> _Resp:
            counter["gets"] += 1
            item = seq.pop(0)
            if isinstance(item, Exception):
                raise item
            return _Resp(item)

    monkeypatch.setattr("inspect_ai._cli.ctl.httpx.Client", _Client)
    monkeypatch.setattr("inspect_ai._cli.ctl.httpx.HTTPTransport", lambda *a, **k: None)
    return counter


def _disc(pid: int) -> "DiscoveredControlServer":
    from pathlib import Path

    return DiscoveredControlServer(
        pid=pid, socket_path=Path(f"/tmp/{pid}.sock"), started_at=0.0
    )


def test_get_with_retry_retries_timeout_then_succeeds(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A read that times out twice, then succeeds, returns the payload.

    Each timeout prints a status to stderr; the eventual success is returned.
    """
    import httpx

    from inspect_ai._cli.ctl import _get_with_retry

    counter = _stub_httpx(
        monkeypatch,
        [httpx.ReadTimeout("slow"), httpx.ReadTimeout("slow"), [{"task_id": "a"}]],
    )
    result = _get_with_retry("/tmp/x.sock", "/evals", what="Reading tasks")
    assert result == [{"task_id": "a"}]
    assert counter["gets"] == 3
    err = capsys.readouterr().err
    assert err.count("retrying") == 2
    assert "attempt 1/8" in err and "attempt 2/8" in err


def test_get_with_retry_exhausts_and_exits(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Eight consecutive timeouts exhaust the retries → error + failure status."""
    import httpx

    from inspect_ai._cli.ctl import _REQUEST_ATTEMPTS, _get_with_retry

    counter = _stub_httpx(monkeypatch, [httpx.ReadTimeout("slow")] * _REQUEST_ATTEMPTS)
    with pytest.raises(click.exceptions.Exit) as exc_info:
        _get_with_retry("/tmp/x.sock", "/evals", what="Reading tasks")
    assert exc_info.value.exit_code == 1
    assert counter["gets"] == _REQUEST_ATTEMPTS
    err = capsys.readouterr().err
    assert f"gave up after {_REQUEST_ATTEMPTS} attempts" in err


def test_get_with_retry_does_not_retry_connection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-timeout transport error (server gone) is not retried."""
    import httpx

    from inspect_ai._cli.ctl import _get_with_retry, _ServerUnreachable

    counter = _stub_httpx(monkeypatch, [httpx.ConnectError("refused")])
    with pytest.raises(_ServerUnreachable):
        _get_with_retry("/tmp/x.sock", "/evals", what="Reading tasks")
    assert counter["gets"] == 1  # tried once, no retry


def test_fetch_summaries_skips_gone_server_but_aggregates_live_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An unreachable server is skipped (with a visible warning); a live one is kept.

    Decorating each kept row with its pid/socket_path is preserved, and the
    skip is surfaced on stderr (naming the pid and the cause) rather than
    silently swallowed.
    """
    import httpx

    from inspect_ai._cli.ctl import _fetch_summaries

    # server 7 refuses (gone); server 8 returns one task.
    _stub_httpx(
        monkeypatch,
        [httpx.ConnectError("refused"), [{"task_id": "live"}]],
    )
    summaries = _fetch_summaries([_disc(7), _disc(8)])
    assert [s["task_id"] for s in summaries] == ["live"]
    assert summaries[0]["pid"] == 8
    assert summaries[0]["socket_path"] == "/tmp/8.sock"
    # the skipped server is surfaced, not swallowed
    err = capsys.readouterr().err
    assert "Skipping pid 7" in err


def test_fetch_summaries_unresponsive_server_exits(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A server that keeps timing out fails the command (not silently dropped)."""
    import httpx

    from inspect_ai._cli.ctl import _REQUEST_ATTEMPTS, _fetch_summaries

    _stub_httpx(monkeypatch, [httpx.ReadTimeout("slow")] * _REQUEST_ATTEMPTS)
    with pytest.raises(click.exceptions.Exit):
        _fetch_summaries([_disc(7)])
    assert "gave up" in capsys.readouterr().err
