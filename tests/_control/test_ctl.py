"""Unit tests for the `inspect ctl` CLI.

Covers target resolution (id + name matching), the noun-group command
surface (implied `list`, strict verb boundary, hidden aliases), the agent
output contract (envelopes, unconditional task_id, mutation results,
cursor validation), and rendering helpers.
"""

import json
from pathlib import Path
from typing import Any

import click
import pytest

from _control.conftest import cli_runner
from inspect_ai._cli.ctl import (
    _KNOB_SCOPE,
    _KNOB_SINCE,
    _SHORT_ID_LEN,
    _ConfigResult,
    _FetchedSummaries,
    _print_human_table,
    _print_keep_alive_footer,
    _print_samples_table,
    _resolve_target_eval,
    _resolve_target_server,
    _SamplesPage,
    ctl_command,
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


def _task_row(task_id: str, task: str, **extra: Any) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "task": task,
        "samples": {"total": 2, "completed": 1, "in_flight": 1},
        "started_at": 1000.0,
        **extra,
    }


def test_tasks_table_shows_model_and_solver_columns(
    capsys: pytest.CaptureFixture[str],
) -> None:
    summaries = [
        _task_row("aaa111", "t1", model="openai/gpt-5", solver="react"),
        _task_row("bbb222", "t2", model="mockllm/model", solver="generate"),
    ]
    _print_human_table(summaries)
    lines = capsys.readouterr().out.splitlines()
    assert "model" in lines[0] and "solver" in lines[0]
    row = next(ln for ln in lines if ln.startswith("aaa111"))
    assert "openai/gpt-5" in row and "react" in row


def test_tasks_table_hides_solver_column_when_absent(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # An older server may omit `solver` entirely — drop the column rather
    # than render it all-blank.
    _print_human_table([_task_row("aaa111", "t1", model="openai/gpt-5")])
    header = capsys.readouterr().out.splitlines()[0]
    assert "model" in header
    assert "solver" not in header


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


def test_turns_column_always_shown(
    capsys: pytest.CaptureFixture[str],
) -> None:
    samples = [{**_sample(1, "running", {}), "turn_count": 7}]
    _print_samples_table(samples)
    lines = capsys.readouterr().out.splitlines()
    assert "turns" in lines[0]
    row = next(ln for ln in lines if ln.startswith("1 "))
    assert "7" in row  # turn count rendered alongside messages


def test_turns_column_blank_when_unknown(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # pending rows and samples logged before turn counting existed carry
    # turn_count=None: render blank, not a misleading 0
    samples = [
        {**_sample(1, "completed", {}), "turn_count": 4},
        _sample(2, "completed", {}),  # no turn_count key -> unknown
    ]
    _print_samples_table(samples)
    lines = capsys.readouterr().out.splitlines()
    row1 = next(ln for ln in lines if ln.startswith("1 "))
    row2 = next(ln for ln in lines if ln.startswith("2 "))
    assert row1.split()[-1] == "4"
    # the unknown row has an empty trailing turns cell (one fewer field)
    assert len(row2.split()) == len(row1.split()) - 1


def test_token_limit_columns_shown_when_configured(
    capsys: pytest.CaptureFixture[str],
) -> None:
    samples = [
        {
            **_sample(1, "running", {}),
            "token_limit_usage": 1234,
            "token_limit_total": 5678,
            "token_limit_type": "output",
        },
        _sample(2, "running", {}),  # no configured limit → blank cells
    ]
    _print_samples_table(samples)
    lines = capsys.readouterr().out.splitlines()
    assert "limit usage" in lines[0]
    assert "limit total" in lines[0]
    row1 = next(ln for ln in lines if ln.startswith("1 "))
    assert "1234" in row1 and "5678" in row1
    # the sample without a configured limit leaves both cells blank
    row2 = next(ln for ln in lines if ln.startswith("2 "))
    assert "5678" not in row2


def test_token_limit_columns_shown_for_all_type(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # For an "all" limit we still report the pair (usage tracks total tokens),
    # for consistency with computed limits.
    samples = [
        {
            **_sample(1, "running", {}),
            "token_limit_usage": 900,
            "token_limit_total": 9999,
            "token_limit_type": "all",
        }
    ]
    _print_samples_table(samples)
    lines = capsys.readouterr().out.splitlines()
    assert "limit usage" in lines[0] and "limit total" in lines[0]
    row = next(ln for ln in lines if ln.startswith("1 "))
    assert "9999" in row


def test_token_limit_columns_hidden_when_no_limit(
    capsys: pytest.CaptureFixture[str],
) -> None:
    samples = [_sample(1, "running", {})]  # no token_limit_total anywhere
    _print_samples_table(samples)
    header = capsys.readouterr().out.splitlines()[0]
    assert "limit usage" not in header and "limit total" not in header


def test_sorted_samples_orders_running_queued_terminal_pending() -> None:
    """The cap keeps the head of this order, so every status's rank matters.

    Queued rows must sort between running and terminal by explicit rank —
    not by a started_at tiebreak a terminal row without a start time
    could tie with.
    """
    from inspect_ai._control.state import _sorted_samples

    rows: list[dict[str, Any]] = [
        {"status": "pending", "started_at": None},
        {"status": "completed", "started_at": 100.0},
        {"status": "cancelled", "started_at": None},
        {"status": "running", "started_at": 200.0},
        {"status": "queued", "started_at": None},
        {"status": "error", "started_at": 50.0},
    ]
    ordered = [r["status"] for r in _sorted_samples(rows)]
    assert ordered == [
        "running",
        "queued",
        "cancelled",  # terminal without a start time still sorts after queued
        "error",
        "completed",
        "pending",
    ]


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
            {
                "event": "info",
                "timestamp": 1003.0,
                "source": "my-solver",
                "data": "phase 1 complete",
            },
        ],
        "next": "CURSORX",
        "done": False,
    }
    _print_events(page)
    out = capsys.readouterr().out
    assert "event" in out.splitlines()[0]  # table header
    # per-type summaries
    assert "openai/gpt" in out and "bash" in out and "boom" in out
    assert "my-solver" in out and "phase 1 complete" in out
    # footer: count, "more" (not done), and the resume cursor
    assert "4 events" in out
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
    assert "inspect ctl process keep" in out


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


def test_footer_reports_paused_tasks(capsys: pytest.CaptureFixture[str]) -> None:
    summaries: list[dict[str, Any]] = [
        {"keep_alive": True, "paused": "task", "quiesced": True},
        {"keep_alive": True, "paused": None},
    ]
    _print_keep_alive_footer(summaries)
    out = capsys.readouterr().out
    assert "paused: 1/2 tasks (1 quiesced)" in out
    assert "inspect ctl process resume" in out
    # keep-alive on → the run parks rather than exiting, no contradiction
    assert "never finishes" not in out


def test_footer_flags_process_paused_with_exit_when_done(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A process-paused run with keep-alive off never reaches its exit."""
    summaries: list[dict[str, Any]] = [
        {"keep_alive": False, "paused": "process", "quiesced": False}
    ]
    _print_keep_alive_footer(summaries)
    out = capsys.readouterr().out
    assert "paused: 1/1 task" in out
    assert "never finishes" in out


def test_footer_silent_when_nothing_paused(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # older servers omit the field entirely — treated as not paused
    _print_keep_alive_footer([{"keep_alive": True}])
    out = capsys.readouterr().out
    assert "paused" not in out


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

    Each item is either an ``Exception`` to raise (e.g. a ``TimeoutException``),
    a payload to return from ``response.json()``, or a ``(status_code, payload)``
    tuple for a non-200 response. Returns a dict whose ``"gets"`` entry counts
    how many requests were attempted.
    """
    counter = {"gets": 0, "posts": 0, "patches": 0}
    seq = list(sequence)

    class _Resp:
        def __init__(self, payload: object, status_code: int = 200) -> None:
            self._payload = payload
            self.status_code = status_code

        def raise_for_status(self) -> None:
            # faithful to httpx: a 4xx/5xx raises HTTPStatusError carrying a
            # response whose status_code callers can inspect
            if self.status_code >= 400:
                import httpx

                request = httpx.Request("GET", "http://localhost/stub")
                response = httpx.Response(self.status_code, request=request)
                raise httpx.HTTPStatusError(
                    f"{self.status_code}", request=request, response=response
                )

        def json(self) -> object:
            return self._payload

    class _Client:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def __enter__(self) -> "_Client":
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def _next(self, kind: str) -> _Resp:
            counter[kind] += 1
            item = seq.pop(0)
            if isinstance(item, Exception):
                raise item
            if isinstance(item, tuple):
                status, payload = item
                return _Resp(payload, status)
            return _Resp(item)

        def get(self, path: str, params: object = None) -> _Resp:
            return self._next("gets")

        def post(self, path: str, params: object = None) -> _Resp:
            return self._next("posts")

        def patch(self, path: str, params: object = None) -> _Resp:
            return self._next("patches")

        def request(self, method: str, path: str, params: object = None) -> _Resp:
            return getattr(self, method)(path, params)

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
    result = _get_with_retry("/tmp/x.sock", "/tasks", what="Reading tasks")
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
        _get_with_retry("/tmp/x.sock", "/tasks", what="Reading tasks")
    assert exc_info.value.exit_code == 1
    assert counter["gets"] == _REQUEST_ATTEMPTS
    err = capsys.readouterr().err
    assert f"gave up after {_REQUEST_ATTEMPTS} attempts" in err


def test_config_read_retries_timeout_then_succeeds(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A config read (GET) retries a busy process on timeout, like other reads."""
    import httpx

    from inspect_ai._cli.ctl import _exec_limits

    view = {"max_samples": {"adjustable": False}, "buffer": None}
    counter = _stub_httpx(
        monkeypatch,
        [httpx.ReadTimeout("slow"), httpx.ReadTimeout("slow"), view],
    )
    result = _exec_limits(
        "/tmp/x.sock",
        "t1",
        max_samples=None,
        max_sandboxes=None,
        max_connections=None,
        model=None,
        dry_run=False,
    )
    assert result.view == view
    assert result.mutated is False
    assert counter["gets"] == 3
    assert counter["patches"] == 0
    assert "retrying" in capsys.readouterr().err


def test_config_set_does_not_retry_timeout(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A config update (PATCH) is single-shot — a mutation must not be retried."""
    import httpx

    from inspect_ai._cli.ctl import _exec_limits

    counter = _stub_httpx(monkeypatch, [httpx.ReadTimeout("slow")])
    with pytest.raises(click.exceptions.Exit) as exc_info:
        _exec_limits(
            "/tmp/x.sock",
            "t1",
            max_samples=None,
            max_sandboxes=None,
            max_connections=None,
            model=None,
            log_buffer=3,
            dry_run=False,
        )
    assert exc_info.value.exit_code == 1
    assert counter["patches"] == 1  # tried once, no retry
    assert "Failed to update config" in capsys.readouterr().err


def test_get_with_retry_busy_raises_without_terminal_echo(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A degradable read raises _ServerBusy on exhaustion — no 'gave up' echo.

    The raising caller owns the terminal narration (its skip/omit message);
    a helper-printed 'gave up … busy; try again shortly' right before it
    would double-narrate. Only the shared per-attempt retry lines print.
    """
    import httpx

    from inspect_ai._cli.ctl import _get_with_retry, _ServerBusy

    counter = _stub_httpx(monkeypatch, [httpx.ReadTimeout("slow")] * 2)
    with pytest.raises(_ServerBusy):
        _get_with_retry(
            "/tmp/x.sock",
            "/tasks",
            what="Reading tasks",
            raise_on_busy=True,
            attempts=2,
        )
    assert counter["gets"] == 2
    err = capsys.readouterr().err
    # the final attempt doesn't promise a retry that never comes
    assert err.count("retrying") == 1
    assert "attempt 2/2" in err
    assert "gave up" not in err


def test_fetch_summaries_busy_server_skipped_when_degradable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """With raise_on_busy, a wedged process is skipped and live ones still list.

    The unscoped sample fan-out's summaries stage: one busy sibling process
    (on the degraded attempt budget) must not kill the whole listing.
    """
    import httpx

    from inspect_ai._cli.ctl import _DEGRADED_READ_ATTEMPTS, _fetch_summaries

    _stub_httpx(
        monkeypatch,
        [httpx.ReadTimeout("slow")] * _DEGRADED_READ_ATTEMPTS + [[{"task_id": "live"}]],
    )
    fetched = _fetch_summaries([_disc(7), _disc(8)], raise_on_busy=True)
    assert [s["task_id"] for s in fetched.summaries] == ["live"]
    assert fetched.busy_pids == [7]
    err = capsys.readouterr().err
    assert "Skipping pid 7" in err
    assert "try again shortly" in err


def test_fetch_summaries_sole_server_rides_full_budget(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A sole busy server gets the full budget — there is no fan-out to protect.

    A stall longer than the degraded budget still resolves in one invocation,
    keeping the full-budget payload reads behind it reachable.
    """
    import httpx

    from inspect_ai._cli.ctl import _DEGRADED_READ_ATTEMPTS, _fetch_summaries

    stalls = _DEGRADED_READ_ATTEMPTS + 1
    _stub_httpx(
        monkeypatch,
        [httpx.ReadTimeout("slow")] * stalls + [[{"task_id": "live"}]],
    )
    fetched = _fetch_summaries([_disc(7)], raise_on_busy=True)
    assert [s["task_id"] for s in fetched.summaries] == ["live"]
    assert fetched.busy_pids == []
    assert "retrying" in capsys.readouterr().err


def test_fetch_summaries_exact_id_match_short_circuits_fan_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An exact full-task_id match stops the fan-out at the server holding it."""
    from inspect_ai._cli.ctl import _fetch_summaries

    counter = _stub_httpx(monkeypatch, [[{"task_id": "aaa111"}]])
    fetched = _fetch_summaries(
        [_disc(7), _disc(8)], raise_on_busy=True, stop_on_task_id="aaa111"
    )
    assert [s["task_id"] for s in fetched.summaries] == ["aaa111"]
    assert counter["gets"] == 1  # pid 8 never contacted


def test_fetch_summaries_prefix_query_still_fans_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A prefix (non-exact) query never stops early — ambiguity needs all servers."""
    from inspect_ai._cli.ctl import _fetch_summaries

    counter = _stub_httpx(
        monkeypatch, [[{"task_id": "aaa111"}], [{"task_id": "aaa222"}]]
    )
    fetched = _fetch_summaries(
        [_disc(7), _disc(8)], raise_on_busy=True, stop_on_task_id="aaa"
    )
    assert [s["task_id"] for s in fetched.summaries] == ["aaa111", "aaa222"]
    assert counter["gets"] == 2


def test_fetch_summaries_duplicate_id_resolves_to_newest_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The duplicate-id corner (old kept-alive attempt, newer retry) resolves newest.

    Only the newest server's payload is stubbed: contacting the older
    sibling would exhaust the sequence and fail loudly.
    """
    from inspect_ai._cli.ctl import _fetch_summaries

    counter = _stub_httpx(monkeypatch, [[{"task_id": "aaa111", "task": "t1"}]])
    fetched = _fetch_summaries(
        [_disc(8), _disc(7)], raise_on_busy=True, stop_on_task_id="aaa111"
    )
    assert counter["gets"] == 1
    resolved = _resolve_target_eval(fetched.summaries, "aaa111")
    assert resolved["pid"] == 8


def test_list_discovered_servers_sorts_newest_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Discovery lists servers newest-first — the exact-id short-circuit relies on it."""
    from inspect_ai._control import discovery

    entries = [
        {"pid": 1, "socket_path": "/tmp/1.sock", "started_at": 100.0},
        {"pid": 3, "socket_path": "/tmp/3.sock", "started_at": 300.0},
        {"pid": 2, "socket_path": "/tmp/2.sock", "started_at": 200.0},
    ]
    monkeypatch.setattr(discovery, "list_alive_discovery_entries", lambda d: entries)
    assert [s.pid for s in discovery.list_discovered_servers()] == [3, 2, 1]


def test_events_poll_with_full_task_id_skips_sibling_servers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`sample events` with a full task_id never contacts sibling processes.

    Two servers discovered, match on the first: the whole invocation is
    exactly two requests (its /tasks + the events read) — a third would
    exhaust the stub sequence and fail loudly.
    """
    monkeypatch.setattr(
        "inspect_ai._cli.ctl.list_discovered_servers",
        lambda: [_disc(8), _disc(7)],
    )
    counter = _stub_httpx(
        monkeypatch,
        [
            [{"task_id": "aaa111", "task": "t1", "eval_id": "eval_a"}],
            {"events": [], "next": None, "done": True},
        ],
    )
    result = cli_runner().invoke(
        ctl_command, ["sample", "events", "aaa111", "s1", "--json"]
    )
    assert result.exit_code == 0, result.output
    assert counter["gets"] == 2
    payload = json.loads(result.stdout)
    assert payload["task_id"] == "aaa111"


def test_sample_detail_read_retries_busy_timeout(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The authoritative detail read rides the narrated busy-retry policy."""
    import httpx

    from inspect_ai._cli.ctl import _fetch_sample_detail

    counter = _stub_httpx(
        monkeypatch,
        [httpx.ReadTimeout("slow"), {"sample_id": "s1", "epoch": 1}],
    )
    detail = _fetch_sample_detail("/tmp/x.sock", "eval_a", "s1", 1)
    assert detail == {"sample_id": "s1", "epoch": 1}
    assert counter["gets"] == 2
    assert "retrying" in capsys.readouterr().err


def test_sample_events_read_retries_busy_timeout(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The authoritative events read rides the narrated busy-retry policy."""
    import httpx

    from inspect_ai._cli.ctl import _fetch_sample_events

    counter = _stub_httpx(
        monkeypatch,
        [httpx.ReadTimeout("slow"), {"events": [], "next": None, "done": True}],
    )
    page = _fetch_sample_events(
        "/tmp/x.sock",
        "eval_a",
        "s1",
        1,
        cursor=None,
        tail=5,
        limit=None,
        types=None,
        full=False,
        since_time=None,
        until=None,
    )
    assert page == {"events": [], "next": None, "done": True}
    assert counter["gets"] == 2
    assert "retrying" in capsys.readouterr().err


def test_get_with_retry_does_not_retry_connection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-timeout transport error (server gone) is not retried."""
    import httpx

    from inspect_ai._cli.ctl import _get_with_retry, _ServerUnreachable

    counter = _stub_httpx(monkeypatch, [httpx.ConnectError("refused")])
    with pytest.raises(_ServerUnreachable):
        _get_with_retry("/tmp/x.sock", "/tasks", what="Reading tasks")
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
    summaries = _fetch_summaries([_disc(7), _disc(8)]).summaries
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


# --- noun-group surface + agent output contract -----------------------------


class _DiscServer:
    """Discovery entry double (pid / socket_path / started_at / api_version)."""

    def __init__(self, pid: int, api_version: int = 0) -> None:
        self.pid = pid
        self.socket_path = f"/tmp/{pid}.sock"
        self.started_at = 100.0
        self.api_version = api_version


def _full_summary(
    task_id: str, task: str, *, pid: int = 7, status: str = "running"
) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "task": task,
        "eval_id": f"eval_{task_id}",
        "socket_path": f"/tmp/{pid}.sock",
        "pid": pid,
        "status": status,
        "samples": {},
        "started_at": 100.0,
        "keep_alive": False,
    }


def _sample_row(sample_id: str, **overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "sample_id": sample_id,
        "epoch": 1,
        "status": "completed",
        "total_time": 1.0,
        "total_tokens": 5,
        "message_count": 1,
        "scores": {},
        "error": None,
        "retries": 0,
    }
    row.update(overrides)
    return row


def _patch_surface(
    monkeypatch: pytest.MonkeyPatch,
    summaries: list[dict[str, Any]],
    samples_by_eval: dict[str, list[dict[str, Any]]] | None = None,
    servers: list[Any] | None = None,
    busy_pids: list[int] | None = None,
) -> None:
    """Stub discovery + the HTTP reads so CLI commands run hermetically."""
    monkeypatch.setattr(
        "inspect_ai._cli.ctl.list_discovered_servers",
        lambda: servers if servers is not None else [_DiscServer(7)],
    )
    monkeypatch.setattr(
        "inspect_ai._cli.ctl._fetch_summaries",
        lambda s, **kwargs: _FetchedSummaries(summaries, busy_pids or []),
    )
    if samples_by_eval is not None:
        # Mirrors the real server: `sample_filter="errors"` returns only
        # errored/retried rows (the CLI keeps no client-side fallback).
        def fake_fetch_samples(
            socket_path: Any,
            eval_id: str,
            active_since: float | None = None,
            *,
            sample_filter: str | None = None,
            **kwargs: Any,
        ) -> _SamplesPage:
            samples = samples_by_eval.get(eval_id, [])
            if sample_filter == "errors":
                samples = [s for s in samples if s["error"] or (s["retries"] or 0) > 0]
            return _SamplesPage(as_of=123.0, samples=samples)

        monkeypatch.setattr("inspect_ai._cli.ctl._fetch_samples", fake_fetch_samples)


def test_bare_task_noun_implies_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """`ctl task --json` (no verb) runs `list` — with the mirrored option."""
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    result = cli_runner().invoke(ctl_command, ["task", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert "as_of" in payload
    assert payload["tasks"][0]["task_id"] == "aaa111"


def test_task_list_explicit_matches_bare(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    runner = cli_runner()
    bare = runner.invoke(ctl_command, ["task", "--json"]).output
    explicit = runner.invoke(ctl_command, ["task", "list", "--json"]).output
    assert json.loads(bare)["tasks"] == json.loads(explicit)["tasks"]


def test_sample_selector_in_verb_slot_teaches() -> None:
    """The implied-list default never fires past a positional; the error teaches."""
    result = cli_runner().invoke(ctl_command, ["sample", "my-task"])
    assert result.exit_code != 0
    assert "sample list my-task" in result.stderr
    # ...and points the old `ctl sample TASK SID` invocation at `sample show`
    assert "sample show my-task" in result.stderr


def test_bare_sample_noun_empty_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    """`ctl sample --json` with nothing running emits an empty envelope."""
    _patch_surface(monkeypatch, [], samples_by_eval={})
    result = cli_runner().invoke(ctl_command, ["sample", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["samples"] == []
    assert "as_of" in payload


def test_sample_list_unscoped_spans_tasks(monkeypatch: pytest.MonkeyPatch) -> None:
    """No TASK = unfiltered across tasks; every row carries task identity."""
    _patch_surface(
        monkeypatch,
        [_full_summary("aaa111", "t1"), _full_summary("bbb222", "t2")],
        samples_by_eval={
            "eval_aaa111": [_sample_row("s1")],
            "eval_bbb222": [_sample_row("s2")],
        },
    )
    result = cli_runner().invoke(ctl_command, ["sample", "list", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["as_of"] == 123.0  # server-provided, not client-minted
    assert [(r["task_id"], r["sample_id"]) for r in payload["samples"]] == [
        ("aaa111", "s1"),
        ("bbb222", "s2"),
    ]


def test_sample_list_scoped_rows_still_carry_task_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """task_id is unconditional — present even when rows are from one task."""
    _patch_surface(
        monkeypatch,
        [_full_summary("aaa111", "t1")],
        samples_by_eval={"eval_aaa111": [_sample_row("s1")]},
    )
    result = cli_runner().invoke(ctl_command, ["sample", "list", "aaa111", "--json"])
    payload = json.loads(result.stdout)
    assert payload["samples"][0]["task_id"] == "aaa111"
    assert payload["samples"][0]["task"] == "t1"


def test_sample_errors_unscoped_filters_across_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_surface(
        monkeypatch,
        [_full_summary("aaa111", "t1"), _full_summary("bbb222", "t2")],
        samples_by_eval={
            "eval_aaa111": [_sample_row("ok"), _sample_row("bad", error="boom")],
            "eval_bbb222": [_sample_row("retried", retries=2)],
        },
    )
    result = cli_runner().invoke(ctl_command, ["sample", "errors", "--json"])
    payload = json.loads(result.stdout)
    assert [(r["task_id"], r["sample_id"]) for r in payload["samples"]] == [
        ("aaa111", "bad"),
        ("bbb222", "retried"),
    ]


def test_sample_errors_requests_server_side_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`sample errors` asks the server to filter and trusts the result.

    The request carries `sample_filter="errors"` and the returned rows are
    displayed as-is — there is no client-side fallback filter.
    """
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    seen: dict[str, Any] = {}

    def fake_samples(
        socket_path: Any,
        eval_id: str,
        active_since: float | None = None,
        *,
        sample_filter: str | None = None,
        **kwargs: Any,
    ) -> _SamplesPage:
        seen["sample_filter"] = sample_filter
        return _SamplesPage(
            as_of=123.0,
            samples=[_sample_row("bad", error="boom")],
        )

    monkeypatch.setattr("inspect_ai._cli.ctl._fetch_samples", fake_samples)
    result = cli_runner().invoke(ctl_command, ["sample", "errors", "--json"])
    assert result.exit_code == 0, result.output
    assert seen["sample_filter"] == "errors"
    payload = json.loads(result.stdout)
    assert [r["sample_id"] for r in payload["samples"]] == ["bad"]


def test_sample_list_does_not_request_errors_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    seen: dict[str, Any] = {}

    def fake_samples(
        socket_path: Any,
        eval_id: str,
        active_since: float | None = None,
        *,
        sample_filter: str | None = None,
        **kwargs: Any,
    ) -> _SamplesPage:
        seen["sample_filter"] = sample_filter
        return _SamplesPage(as_of=123.0, samples=[_sample_row("s1")])

    monkeypatch.setattr("inspect_ai._cli.ctl._fetch_samples", fake_samples)
    result = cli_runner().invoke(ctl_command, ["sample", "list", "--json"])
    assert result.exit_code == 0, result.output
    assert seen["sample_filter"] is None


def test_fetch_samples_sends_filter_param(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The wire param is `filter=errors`, and only when requested."""
    from inspect_ai._cli.ctl import _fetch_samples

    seen: dict[str, Any] = {}

    def fake_get(
        socket_path: Any, path: str, *, params: Any = None, **kwargs: Any
    ) -> Any:
        seen["params"] = params
        return {"as_of": 1.0, "samples": []}

    monkeypatch.setattr("inspect_ai._cli.ctl._get_with_retry", fake_get)
    _fetch_samples("/tmp/x.sock", "e1", sample_filter="errors")
    assert seen["params"] == {"filter": "errors"}
    _fetch_samples("/tmp/x.sock", "e1")
    assert seen["params"] == {}


def _capture_fetch_kwargs(
    monkeypatch: pytest.MonkeyPatch,
    page: _SamplesPage | None = None,
) -> list[dict[str, Any]]:
    """Stub `_fetch_samples`, recording each call's cap/filter kwargs."""
    calls: list[dict[str, Any]] = []
    result = page if page is not None else _SamplesPage(as_of=123.0, samples=[])

    def fake_samples(
        socket_path: Any,
        eval_id: str,
        active_since: float | None = None,
        **kwargs: Any,
    ) -> _SamplesPage:
        calls.append(dict(kwargs))
        return result

    monkeypatch.setattr("inspect_ai._cli.ctl._fetch_samples", fake_samples)
    return calls


def test_sample_list_forwards_cap_and_filter_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--limit` / `--status` ride the request; the default sends neither."""
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    calls = _capture_fetch_kwargs(monkeypatch)

    cli_runner().invoke(
        ctl_command,
        ["sample", "list", "--limit", "5", "--status", "running,error", "--json"],
    )
    assert calls[-1]["limit"] == 5
    # the filter rides in its parsed (normalized) form, not the raw flag value
    assert calls[-1]["status"] == "error,running"
    assert calls[-1]["all_samples"] is False

    cli_runner().invoke(ctl_command, ["sample", "list", "--json"])
    assert calls[-1]["limit"] is None  # server default cap applies
    assert calls[-1]["all_samples"] is False


def test_sample_list_all_requests_full_listing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    calls = _capture_fetch_kwargs(monkeypatch)
    result = cli_runner().invoke(ctl_command, ["sample", "list", "--all", "--json"])
    assert result.exit_code == 0, result.output
    assert calls[-1]["all_samples"] is True


def test_sample_list_all_and_limit_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--all` and `--limit` contradict; error rather than pick silently."""
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    calls = _capture_fetch_kwargs(monkeypatch)
    result = cli_runner().invoke(
        ctl_command, ["sample", "list", "--all", "--limit", "5", "--json"]
    )
    assert result.exit_code != 0
    assert "mutually exclusive" in result.stderr
    assert calls == []  # failed before any request


def test_sample_list_unknown_status_teaches_vocabulary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A `--status` typo fails fast with the valid statuses, before any read."""
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    calls = _capture_fetch_kwargs(monkeypatch)
    result = cli_runner().invoke(
        ctl_command, ["sample", "list", "--status", "compleeted", "--json"]
    )
    assert result.exit_code != 0
    assert "compleeted" in result.stderr
    assert "pending" in result.stderr  # names the vocabulary
    assert calls == []


def test_sample_list_empty_status_fails_fast(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty `--status` member set errors rather than dropping every row."""
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    calls = _capture_fetch_kwargs(monkeypatch)
    for empty in ("", ","):
        result = cli_runner().invoke(
            ctl_command, ["sample", "list", "--status", empty, "--json"]
        )
        assert result.exit_code != 0, empty
        assert "at least one status" in result.stderr
    assert calls == []


def test_sample_list_mirrored_cap_flags_on_bare_noun(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`ctl sample --limit N --status S` (no verb) behaves like `list`."""
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    calls = _capture_fetch_kwargs(monkeypatch)
    result = cli_runner().invoke(
        ctl_command, ["sample", "--limit", "7", "--status", "running", "--json"]
    )
    assert result.exit_code == 0, result.output
    assert calls[-1]["limit"] == 7
    assert calls[-1]["status"] == "running"


def test_sample_list_envelope_aggregates_counts_and_truncated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The `--json` envelope sums per-eval histograms and ORs `truncated`."""
    _patch_surface(
        monkeypatch,
        [_full_summary("aaa111", "t1"), _full_summary("bbb222", "t2")],
    )
    pages = {
        "eval_aaa111": _SamplesPage(
            as_of=123.0,
            samples=[_sample_row("s1", status="running")],
            counts={"running": 1, "completed": 200},
            truncated=True,
        ),
        "eval_bbb222": _SamplesPage(
            as_of=124.0,
            samples=[_sample_row("s2")],
            counts={"completed": 1},
            truncated=False,
        ),
    }
    monkeypatch.setattr(
        "inspect_ai._cli.ctl._fetch_samples",
        lambda socket_path, eval_id, active_since=None, **kwargs: pages[eval_id],
    )
    result = cli_runner().invoke(ctl_command, ["sample", "list", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["truncated"] is True
    assert payload["counts"]["running"] == 1
    assert payload["counts"]["completed"] == 201
    assert payload["counts"]["error"] == 0  # stable keys, zero when empty
    assert len(payload["samples"]) == 2


def test_sample_list_counts_derived_for_older_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A histogram-less envelope (older server) derives counts from its rows.

    On such a server the rows are the full listing, so the derived histogram
    is accurate — and the envelope keeps its shape for agents either way.
    """
    _patch_surface(
        monkeypatch,
        [_full_summary("aaa111", "t1")],
        samples_by_eval={
            "eval_aaa111": [
                _sample_row("s1", status="running"),
                _sample_row("s2"),
                _sample_row("s3", status="error", error="boom"),
            ]
        },
    )
    result = cli_runner().invoke(ctl_command, ["sample", "list", "--json"])
    payload = json.loads(result.stdout)
    assert payload["counts"]["running"] == 1
    assert payload["counts"]["completed"] == 1
    assert payload["counts"]["error"] == 1
    assert payload["truncated"] is False


def test_sample_list_filters_and_caps_for_older_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An older server ignores `status`/`limit`; the CLI applies them itself.

    A histogram-less envelope signals a server that dropped the new query
    params and returned the full listing — presenting those rows under the
    requested flags would fake a filtered/capped read, so the filter and cap
    run client-side (with `truncated` derived from the cap) and the counts
    stay whole-listing.
    """
    _patch_surface(
        monkeypatch,
        [_full_summary("aaa111", "t1")],
        samples_by_eval={
            "eval_aaa111": [
                _sample_row("s1", status="running"),
                _sample_row("s2"),
                _sample_row("s3"),
                _sample_row("s4", status="error", error="boom"),
            ]
        },
    )
    result = cli_runner().invoke(
        ctl_command, ["sample", "list", "--status", "completed", "--json"]
    )
    payload = json.loads(result.stdout)
    assert [r["sample_id"] for r in payload["samples"]] == ["s2", "s3"]
    assert payload["counts"]["running"] == 1  # counts stay whole-listing
    assert payload["truncated"] is False

    result = cli_runner().invoke(
        ctl_command, ["sample", "list", "--limit", "2", "--json"]
    )
    payload = json.loads(result.stdout)
    assert [r["sample_id"] for r in payload["samples"]] == ["s1", "s2"]
    assert payload["truncated"] is True

    result = cli_runner().invoke(ctl_command, ["sample", "list", "--all", "--json"])
    payload = json.loads(result.stdout)
    assert len(payload["samples"]) == 4
    assert payload["truncated"] is False


def test_sample_list_human_truncation_footer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A capped human listing says so — no silent truncation."""
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    _capture_fetch_kwargs(
        monkeypatch,
        page=_SamplesPage(
            as_of=123.0,
            samples=[_sample_row("s1", status="running")],
            counts={"running": 1, "completed": 250},
            truncated=True,
        ),
    )
    result = cli_runner().invoke(ctl_command, ["sample", "list"])
    assert result.exit_code == 0, result.output
    assert "showing 1 of 251 samples" in result.output
    assert "--all" in result.output
    assert "--status to filter" in result.output


def test_sample_list_truncation_footer_with_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The footer's totals honor an active filter.

    `counts` is the whole-task histogram, so a `--status`-narrowed footer
    must not claim `--all` would return the whole-task total — it reports
    the matching total from the histogram instead (and drops the redundant
    `--status` hint). A delta poll's matching total is unknowable
    client-side, so that footer claims no matching total at all.
    """
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    _capture_fetch_kwargs(
        monkeypatch,
        page=_SamplesPage(
            as_of=123.0,
            samples=[_sample_row("s1", status="error", error="boom")],
            counts={"running": 3, "completed": 240, "error": 8},
            truncated=True,
        ),
    )

    result = cli_runner().invoke(ctl_command, ["sample", "list", "--status", "error"])
    assert result.exit_code == 0, result.output
    assert "showing 1 of 8 matching samples (251 total" in result.output
    assert "--all" in result.output
    assert "--status to filter" not in result.output

    result = cli_runner().invoke(
        ctl_command, ["sample", "list", "--active-since", "99"]
    )
    assert result.exit_code == 0, result.output
    assert "showing first 1 matching sample (251 total" in result.output
    assert "--status to filter" in result.output


def test_sample_list_empty_filtered_listing_says_no_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty filtered listing must not claim nothing started.

    `--status error` on a healthy eval returns zero rows while samples are
    running — "(no samples started yet)" would be a false claim, so the
    empty message reports the miss against the whole-task histogram. An
    empty `--active-since` delta likewise scopes its claim to the window.
    """
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    _capture_fetch_kwargs(
        monkeypatch,
        page=_SamplesPage(
            as_of=123.0,
            samples=[],
            counts={"running": 3, "completed": 248, "error": 0},
            truncated=False,
        ),
    )

    result = cli_runner().invoke(ctl_command, ["sample", "list", "--status", "error"])
    assert result.exit_code == 0, result.output
    assert "(no matching samples: 0 of 251)" in result.output
    assert "no samples started yet" not in result.output

    result = cli_runner().invoke(
        ctl_command, ["sample", "list", "--active-since", "99"]
    )
    assert result.exit_code == 0, result.output
    assert "(no samples active since the given timestamp)" in result.output
    assert "no samples started yet" not in result.output


def test_sample_errors_requests_full_listing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The triage view sees every row — the cap must not hide errors."""
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    calls = _capture_fetch_kwargs(monkeypatch)
    result = cli_runner().invoke(ctl_command, ["sample", "errors", "--json"])
    assert result.exit_code == 0, result.output
    assert calls[-1]["all_samples"] is True


def test_sample_show_row_lookup_requests_full_listing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`show`'s supplemental row lookup must not lose its row to the cap."""
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    calls = _capture_fetch_kwargs(monkeypatch)
    monkeypatch.setattr(
        "inspect_ai._cli.ctl._fetch_sample_detail",
        lambda *a, **k: {"sample_id": "s1", "epoch": 1, "status": "completed"},
    )
    result = cli_runner().invoke(
        ctl_command, ["sample", "show", "aaa111", "s1", "--json"]
    )
    assert result.exit_code == 0, result.output
    assert calls[-1]["all_samples"] is True


def _patch_samples_unreachable_for(
    monkeypatch: pytest.MonkeyPatch,
    gone_eval_id: str,
    exc: Exception | None = None,
) -> None:
    """Stub `_fetch_samples` so one eval's read fails.

    ``exc`` is the error raised for that eval (default: a connection-refused
    ``_ServerUnreachable``; pass a ``_ServerBusy`` to simulate retry
    exhaustion).
    """
    import httpx

    from inspect_ai._cli.ctl import _ServerUnreachable

    if exc is None:
        exc = _ServerUnreachable()
        exc.__cause__ = httpx.ConnectError("refused")
    failure = exc

    def fake_samples(
        socket_path: Any,
        eval_id: str,
        active_since: float | None = None,
        **kwargs: Any,
    ) -> _SamplesPage:
        if eval_id == gone_eval_id:
            raise failure
        return _SamplesPage(as_of=123.0, samples=[_sample_row("s2")])

    monkeypatch.setattr("inspect_ai._cli.ctl._fetch_samples", fake_samples)


def test_sample_list_unscoped_skips_unreachable_eval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fan-out spanning tasks warns-and-skips one gone eval, keeps the rest."""
    _patch_surface(
        monkeypatch,
        [_full_summary("aaa111", "t1"), _full_summary("bbb222", "t2")],
    )
    _patch_samples_unreachable_for(monkeypatch, "eval_aaa111")
    result = cli_runner().invoke(ctl_command, ["sample", "list", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert [(r["task_id"], r["sample_id"]) for r in payload["samples"]] == [
        ("bbb222", "s2")
    ]
    # the skipped eval is surfaced on stderr, not swallowed
    assert "Skipping eval eval_aaa111" in result.stderr


def test_sample_list_unscoped_single_eval_unreachable_still_skips(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unscoped tolerance keys on intent, not target count.

    With exactly one eval running, an unscoped read still warns-and-skips
    (exit 0, JSON envelope) when that eval exits between discovery and the
    read.
    """
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    _patch_samples_unreachable_for(monkeypatch, "eval_aaa111")
    result = cli_runner().invoke(ctl_command, ["sample", "list", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["samples"] == []
    assert "Skipping eval eval_aaa111" in result.stderr


def test_sample_list_human_skipped_target_says_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The human output makes no positive claim about samples it never read."""
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    _patch_samples_unreachable_for(monkeypatch, "eval_aaa111")
    result = cli_runner().invoke(ctl_command, ["sample", "list"])
    assert result.exit_code == 0, result.output
    assert "(samples unavailable)" in result.output
    assert "no samples started yet" not in result.output
    assert "Skipping eval eval_aaa111" in result.stderr


def test_sample_errors_human_skipped_target_says_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`sample errors` likewise avoids '(no errors or retries)' when unread."""
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    _patch_samples_unreachable_for(monkeypatch, "eval_aaa111")
    result = cli_runner().invoke(ctl_command, ["sample", "errors"])
    assert result.exit_code == 0, result.output
    assert "(samples unavailable)" in result.output
    assert "no errors or retries" not in result.output
    assert "Skipping eval eval_aaa111" in result.stderr


def test_sample_list_scoped_unreachable_exits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A single targeted read keeps the hard failure — nothing else to show."""
    _patch_surface(
        monkeypatch,
        [_full_summary("aaa111", "t1"), _full_summary("bbb222", "t2")],
    )
    _patch_samples_unreachable_for(monkeypatch, "eval_aaa111")
    result = cli_runner().invoke(ctl_command, ["sample", "list", "aaa111", "--json"])
    assert result.exit_code == 1
    assert "Failed to read samples for eval eval_aaa111" in result.stderr


def test_sample_show_reports_detail_summary_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`show` reports the summary fields the detail read itself carries."""
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    detail = {
        "sample_id": "s1",
        "epoch": 1,
        "status": "error",
        "total_time": 1.0,
        "total_tokens": 42,
        "message_count": 3,
        "retries": 0,
        "error": {"message": "boom"},
        "error_retries": [],
        "scores": {},
    }
    monkeypatch.setattr(
        "inspect_ai._cli.ctl._fetch_sample_detail", lambda *a, **k: detail
    )
    result = cli_runner().invoke(
        ctl_command, ["sample", "show", "aaa111", "s1", "--json"]
    )
    payload = json.loads(result.stdout)
    assert payload["task_id"] == "aaa111"
    assert payload["total_tokens"] == 42
    assert payload["message_count"] == 3
    assert payload["error"] == {"message": "boom"}
    assert payload["status"] == "error"
    assert (payload["sample_id"], payload["epoch"]) == ("s1", 1)  # echoed


def test_sample_show_is_a_single_read(monkeypatch: pytest.MonkeyPatch) -> None:
    """`show` never fetches the eval's sample listing.

    A current server's detail response carries the summary fields itself
    (message_count marks it), so the former O(dataset) supplemental listing
    read (and the torn view a retry between the two reads produced) is gone.
    """
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])

    def fail_fetch(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("sample show should not fetch the samples listing")

    monkeypatch.setattr("inspect_ai._cli.ctl._fetch_samples", fail_fetch)
    detail = {
        "sample_id": "s1",
        "epoch": 1,
        "status": "completed",
        "total_tokens": 7,
        "message_count": 2,
        "retries": 0,
        "error": None,
        "error_retries": [],
        "scores": {},
    }
    monkeypatch.setattr(
        "inspect_ai._cli.ctl._fetch_sample_detail", lambda *a, **k: detail
    )
    result = cli_runner().invoke(
        ctl_command, ["sample", "show", "aaa111", "s1", "--json"]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["total_tokens"] == 7


def _old_server_detail() -> dict[str, Any]:
    """A detail response from a server that predates the summary fields.

    No ``message_count`` (or other summary) keys — the marker `show` uses
    to decide the listing fallback is needed.
    """
    return {
        "sample_id": "s1",
        "epoch": 1,
        "status": "error",
        "retries": 1,
        "error": {"message": "boom"},
        "error_retries": [],
        "scores": {},
    }


def test_sample_show_old_server_falls_back_to_listing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Against an old server, `show` folds in the sample's listing row.

    An old server's detail response has no summary fields at all; the CLI
    detects their absence and restores the two-read flow so timing / tokens
    / messages aren't silently dropped — with the detail's own fields still
    winning on overlap.
    """
    _patch_surface(
        monkeypatch,
        [_full_summary("aaa111", "t1")],
        samples_by_eval={
            "eval_aaa111": [
                _sample_row("s1", status="completed", retries=0, total_tokens=42)
            ]
        },
    )
    monkeypatch.setattr(
        "inspect_ai._cli.ctl._fetch_sample_detail",
        lambda *a, **k: _old_server_detail(),
    )
    result = cli_runner().invoke(
        ctl_command, ["sample", "show", "aaa111", "s1", "--json"]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    # summary fields come from the listing row...
    assert payload["total_tokens"] == 42
    assert payload["message_count"] == 1
    # ...while the detail stays authoritative on overlap
    assert payload["status"] == "error"
    assert payload["retries"] == 1
    assert payload["error"] == {"message": "boom"}


@pytest.mark.parametrize("busy", [False, True], ids=["unreachable", "busy"])
def test_sample_show_old_server_fallback_unreachable_degrades(
    monkeypatch: pytest.MonkeyPatch, busy: bool
) -> None:
    """A failed fallback listing read degrades with a caveat, not an error.

    The detail already in hand answers the question; the old server exiting
    — or staying busy through the listing read's retries (_ServerBusy, which
    adds a "try again shortly" hint) — costs only the summary fields,
    surfaced on stderr, with stdout still valid JSON.
    """
    from inspect_ai._cli.ctl import _ServerBusy

    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    _patch_samples_unreachable_for(
        monkeypatch,
        "eval_aaa111",
        exc=_ServerBusy("no response after 2 attempts — the eval's event loop is busy")
        if busy
        else None,
    )
    monkeypatch.setattr(
        "inspect_ai._cli.ctl._fetch_sample_detail",
        lambda *a, **k: _old_server_detail(),
    )
    result = cli_runner().invoke(
        ctl_command, ["sample", "show", "aaa111", "s1", "--json"]
    )
    assert result.exit_code == 0, result.output
    assert "Could not read the samples listing" in result.stderr
    assert ("try again shortly" in result.stderr) == busy
    payload = json.loads(result.stdout)
    assert payload["error"] == {"message": "boom"}
    assert "message_count" not in payload


def test_old_flat_spellings_hidden_from_help() -> None:
    result = cli_runner().invoke(ctl_command, ["--help"])
    for old in (
        "tasks",
        "samples",
        "errors",
        "events",
        "keep",
        "release",
        "flush",
        "buffer",
        "limits",
    ):
        assert f"\n  {old} " not in result.output, old


def test_tasks_alias_delegates_with_deprecation_note(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The hidden alias runs the new implementation (new JSON) + stderr note."""
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    result = cli_runner().invoke(ctl_command, ["tasks", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)  # note on stderr keeps stdout parseable
    assert payload["tasks"][0]["task_id"] == "aaa111"
    assert "is now `inspect ctl task list`" in result.stderr


def _stub_limits(
    monkeypatch: pytest.MonkeyPatch,
    buffer: dict[str, Any] | None = None,
) -> None:
    """Stub the server config view for `ctl config` (minimal adjustable knobs)."""

    def fake_limits(*args: Any, **kwargs: Any) -> _ConfigResult:
        # derive from the canonical knob table so a future knob can't be
        # missed here (which would misreport its sets as mutated=False)
        knobs = _KNOB_SCOPE.keys()
        return _ConfigResult(
            view={
                "max_samples": {"limit": 3, "in_use": 1, "adjustable": True},
                "max_sandboxes": [],
                "adaptive": [],
                "buffer": buffer,
                "requested": None,
                "warnings": [],
                "dry_run": False,
            },
            mutated=any(kwargs.get(k) is not None for k in knobs),
        )

    monkeypatch.setattr("inspect_ai._cli.ctl._exec_limits", fake_limits)


def test_limits_alias_delegates_to_config(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    _stub_limits(
        monkeypatch, buffer={"log_buffer": 10, "pending": 0, "log_shared": None}
    )
    result = cli_runner().invoke(ctl_command, ["limits", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["knobs"]["max_samples"]["scope"] == "task"
    assert "is now `inspect ctl config`" in result.stderr


def test_config_view_tolerates_missing_buffer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A view of a task with no live buffer (reused log) warns — exit 0."""
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    _stub_limits(monkeypatch, buffer=None)
    result = cli_runner().invoke(ctl_command, ["config", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert "log_buffer" not in payload["knobs"]
    assert any("log_buffer" in w for w in payload["warnings"])

    human = cli_runner().invoke(ctl_command, ["config"])
    assert human.exit_code == 0
    assert "! log_buffer/log_shared are not adjustable" in human.output


def test_config_set_buffer_knob_errors_when_no_buffer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit --log-buffer with no live buffer errors.

    And when a limits knob was set alongside it, the error says that set
    still landed.
    """
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    _stub_limits(monkeypatch, buffer=None)
    result = cli_runner().invoke(ctl_command, ["config", "--log-buffer", "2"])
    assert result.exit_code == 1
    assert "has no sample buffer" in result.stderr
    assert "still applied" not in result.stderr  # no limits knob was set

    both = cli_runner().invoke(
        ctl_command, ["config", "--log-buffer", "2", "--max-samples", "5"]
    )
    assert both.exit_code == 1
    assert "still applied" in both.stderr


def test_config_set_buffer_error_does_not_claim_unapplied_knobs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A limits knob the server rejected is not claimed as 'still applied'.

    And the server's not-adjustable warnings are surfaced on the error path
    rather than swallowed by the exit.
    """
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    monkeypatch.setattr(
        "inspect_ai._cli.ctl._exec_limits",
        lambda *a, **k: _ConfigResult(
            view={
                "max_samples": {"adjustable": False, "tracks_adaptive": True},
                "max_sandboxes": [],
                "adaptive": [],
                "buffer": None,
                "requested": {"max_samples": 5, "log_buffer": 2},
                "warnings": [
                    "max_samples is not adjustable for this task (it uses adaptive "
                    "connection concurrency, or ran no samples in this process).",
                    "log_buffer/log_shared are not adjustable for this task (no "
                    "live sample buffer — e.g. a reused log, or a superseded "
                    "retry attempt).",
                ],
                "dry_run": False,
            },
            mutated=True,
        ),
    )
    result = cli_runner().invoke(
        ctl_command, ["config", "--log-buffer", "2", "--max-samples", "5"]
    )
    assert result.exit_code == 1
    assert "has no sample buffer" in result.stderr
    assert "still applied" not in result.stderr
    assert "! max_samples is not adjustable" in result.stderr
    # the buffer warning restates the headline error and is not repeated
    assert "! log_buffer" not in result.stderr


def test_config_gates_key_on_pre_version_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--key` gates on the shipped `_KNOB_SINCE` entry (since-2).

    An older server's PATCH handler silently ignores the unknown key/key_limit
    params (returning a success-shaped view with the retune unapplied), so the
    gate must refuse the whole request pre-flight — a server that predates the
    knob refuses it, and a current server (advertising `CONTROL_API_VERSION`)
    accepts it.
    """
    from inspect_ai._control import CONTROL_API_VERSION

    _patch_surface(
        monkeypatch,
        [_full_summary("aaa111", "t1")],
        servers=[_DiscServer(7, api_version=1)],
    )

    def _no_patch(*args: Any, **kwargs: Any) -> _ConfigResult:
        raise AssertionError("the mutation must not be sent")

    monkeypatch.setattr("inspect_ai._cli.ctl._exec_limits", _no_patch)
    result = cli_runner().invoke(ctl_command, ["config", "--key", "my_api", "2"])
    assert result.exit_code == 1
    assert "--key not supported" in result.stderr
    assert "pid 7 is running an older inspect" in result.stderr

    # the gate covers dry runs too: a dry-run PATCH on an older server would
    # report a success-shaped view that omits the key retune
    dry = cli_runner().invoke(
        ctl_command, ["config", "--key", "my_api", "2", "--dry-run"]
    )
    assert dry.exit_code == 1
    assert "--key not supported" in dry.stderr

    _patch_surface(
        monkeypatch,
        [_full_summary("aaa111", "t1")],
        servers=[_DiscServer(7, api_version=CONTROL_API_VERSION)],
    )
    sent: dict[str, Any] = {}

    def fake_limits(*args: Any, **kwargs: Any) -> _ConfigResult:
        sent.update(kwargs)
        return _ConfigResult(
            view={
                "max_samples": {"limit": 3, "in_use": 1, "adjustable": True},
                "max_sandboxes": [],
                "adaptive": [],
                "concurrency": [
                    {"name": "my_api", "limit": 2, "in_use": 0, "adjustable": True}
                ],
                "buffer": {"log_buffer": 10, "pending": 0, "log_shared": None},
                "requested": {"concurrency:my_api": 2},
                "warnings": [],
                "dry_run": False,
            },
            mutated=True,
        )

    monkeypatch.setattr("inspect_ai._cli.ctl._exec_limits", fake_limits)
    result = cli_runner().invoke(
        ctl_command, ["config", "--key", "my_api", "2", "--json"]
    )
    assert result.exit_code == 0, result.output
    assert sent["key"] == ("my_api", 2)
    payload = json.loads(result.stdout)
    assert payload["applied"] is True
    assert payload["knobs"]["concurrency"]["keys"][0]["name"] == "my_api"


def test_config_task_knob_with_only_orphan_task_says_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A just-starting attempt (no task id yet) gets retry guidance.

    Not the impossible 'pass a task id to choose one' over a table whose id
    cell is blank.
    """
    _patch_surface(monkeypatch, [_full_summary("", "t1", status="running")])
    result = cli_runner().invoke(ctl_command, ["config", "--max-samples", "3"])
    assert result.exit_code == 1
    assert "hasn't finished registering yet" in result.stderr
    assert "retry in a moment" in result.stderr
    assert "pass a task id" not in result.stderr


def test_config_task_knob_with_only_pre_task_id_logs_says_unaddressable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_surface(monkeypatch, [_full_summary("", "t1", status="completed")])
    result = cli_runner().invoke(ctl_command, ["config", "--max-samples", "3"])
    assert result.exit_code == 1
    assert "predate task ids" in result.stderr
    assert "pass a task id" not in result.stderr


def test_config_help_scope_tags_derive_from_knob_table() -> None:
    """Every knob's --help entry carries the scope from _KNOB_SCOPE.

    The help tags, the JSON "scope" fields, and the human render labels all
    derive from that one table; this pins the help side (the JSON side is
    pinned by test_compose_config_labels_every_knob_with_scope).
    """
    out = cli_runner().invoke(ctl_command, ["config", "--help"]).output
    options = out[out.index("Options:") :]  # the docstring also names flags
    for knob, scope in _KNOB_SCOPE.items():
        flag = "--" + knob.replace("_", "-")
        start = options.index(flag)
        assert f"[{scope}]" in options[start : start + 120], knob


def test_knob_since_table_is_consistent() -> None:
    """Every knob has a min-version entry, and no entry outruns the constant.

    Key parity (also asserted at runtime in `_exec_limits`) forces a new knob
    to declare its since-version explicitly rather than silently defaulting
    to "understood by every server". The second assertion catches
    forgot-to-bump variant A (a `_KNOB_SINCE` entry of N+1 while
    `CONTROL_API_VERSION` is still N), which would make the CLI block its own
    new knob against every server — including current ones. (Variant B —
    reusing the current N without a bump — is convention only; see the
    comment on `CONTROL_API_VERSION`.)
    """
    from inspect_ai._control import CONTROL_API_VERSION

    assert _KNOB_SINCE.keys() == _KNOB_SCOPE.keys()
    assert max(_KNOB_SINCE.values()) <= CONTROL_API_VERSION


def test_config_gates_newer_knob_on_older_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A knob the target server predates hard-errors before the PATCH.

    An older server's PATCH handler silently ignores unknown query params
    (applying whatever it does recognize), so the gate must fail the whole
    request pre-flight — `_exec_limits` must never run.
    """
    _patch_surface(
        monkeypatch,
        [_full_summary("aaa111", "t1")],
        servers=[_DiscServer(7, api_version=0)],
    )
    monkeypatch.setitem(_KNOB_SINCE, "max_samples", 1)

    def _no_patch(*args: Any, **kwargs: Any) -> _ConfigResult:
        raise AssertionError("the mutation must not be sent")

    monkeypatch.setattr("inspect_ai._cli.ctl._exec_limits", _no_patch)

    result = cli_runner().invoke(ctl_command, ["config", "--max-samples", "3"])
    assert result.exit_code == 1
    assert "--max-samples not supported" in result.stderr
    assert "pid 7 is running an older inspect" in result.stderr
    assert "restart the eval" in result.stderr

    # the gate covers dry runs too: a dry-run PATCH on an older server would
    # report a success-shaped view that omits the unknown knobs
    dry = cli_runner().invoke(
        ctl_command, ["config", "--max-samples", "3", "--dry-run"]
    )
    assert dry.exit_code == 1
    assert "--max-samples not supported" in dry.stderr


def test_config_gate_names_only_unsupported_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pre-flight error lists the offending flags, not every set knob."""
    _patch_surface(
        monkeypatch,
        [_full_summary("aaa111", "t1")],
        servers=[_DiscServer(7, api_version=0)],
    )
    monkeypatch.setitem(_KNOB_SINCE, "log_buffer", 1)
    result = cli_runner().invoke(
        ctl_command, ["config", "--log-buffer", "2", "--max-samples", "5"]
    )
    assert result.exit_code == 1
    assert "--log-buffer not supported" in result.stderr
    assert "--max-samples" not in result.stderr


def test_config_gate_passes_on_current_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A server whose advertised version covers the knob is not gated."""
    _patch_surface(
        monkeypatch,
        [_full_summary("aaa111", "t1")],
        servers=[_DiscServer(7, api_version=1)],
    )
    monkeypatch.setitem(_KNOB_SINCE, "max_samples", 1)
    _stub_limits(
        monkeypatch, buffer={"log_buffer": 10, "pending": 0, "log_shared": None}
    )
    result = cli_runner().invoke(
        ctl_command, ["config", "--max-samples", "3", "--json"]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["applied"] is True


def test_config_gate_ignores_since_zero_knobs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Since-0 knobs pass against any server, version-reporting or not."""
    _patch_surface(
        monkeypatch,
        [_full_summary("aaa111", "t1")],
        servers=[_DiscServer(7, api_version=0)],
    )
    _stub_limits(
        monkeypatch, buffer={"log_buffer": 10, "pending": 0, "log_shared": None}
    )
    result = cli_runner().invoke(
        ctl_command, ["config", "--max-samples", "3", "--json"]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["applied"] is True


def test_config_gates_max_subprocesses_on_pre_version_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--max-subprocesses` gates on the shipped `_KNOB_SINCE` entry (since-1).

    The gate-mechanism tests above monkeypatch `_KNOB_SINCE`; this pins the
    real table: a server that predates version reporting refuses the knob,
    and a current server (advertising `CONTROL_API_VERSION`) accepts it.
    """
    from inspect_ai._control import CONTROL_API_VERSION

    _patch_surface(
        monkeypatch,
        [_full_summary("aaa111", "t1")],
        servers=[_DiscServer(7, api_version=0)],
    )
    result = cli_runner().invoke(ctl_command, ["config", "--max-subprocesses", "2"])
    assert result.exit_code == 1
    assert "--max-subprocesses not supported" in result.stderr

    _patch_surface(
        monkeypatch,
        [_full_summary("aaa111", "t1")],
        servers=[_DiscServer(7, api_version=CONTROL_API_VERSION)],
    )
    _stub_limits(
        monkeypatch, buffer={"log_buffer": 10, "pending": 0, "log_shared": None}
    )
    result = cli_runner().invoke(
        ctl_command, ["config", "--max-subprocesses", "2", "--json"]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["applied"] is True


def test_config_gates_retry_overrides_by_real_since_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The retry overrides gate on their real `_KNOB_SINCE` entries (since-2).

    Unlike the gate tests above, no table entry is monkeypatched: a version-0
    process rejects a retry-override set pre-flight, and a process at the
    current version applies it.
    """
    _patch_surface(
        monkeypatch,
        [_full_summary("aaa111", "t1")],
        servers=[_DiscServer(7, api_version=0)],
    )
    result = cli_runner().invoke(
        ctl_command, ["config", "--timeout", "300", "--attempt-timeout", "60"]
    )
    assert result.exit_code == 1
    assert "--timeout, --attempt-timeout not supported" in result.stderr

    from inspect_ai._control import CONTROL_API_VERSION

    _patch_surface(
        monkeypatch,
        [_full_summary("aaa111", "t1")],
        servers=[_DiscServer(7, api_version=CONTROL_API_VERSION)],
    )
    _stub_limits(
        monkeypatch, buffer={"log_buffer": 10, "pending": 0, "log_shared": None}
    )
    result = cli_runner().invoke(ctl_command, ["config", "--timeout", "300", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["applied"] is True


def test_config_retry_overrides_accept_clear_keyword(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`clear` parses as a knob value (a mutation) and bad spellings fail early."""
    from inspect_ai._control import CONTROL_API_VERSION

    _patch_surface(
        monkeypatch,
        [_full_summary("aaa111", "t1")],
        servers=[_DiscServer(7, api_version=CONTROL_API_VERSION)],
    )
    _stub_limits(
        monkeypatch, buffer={"log_buffer": 10, "pending": 0, "log_shared": None}
    )
    result = cli_runner().invoke(
        ctl_command, ["config", "--max-retries", "clear", "--json"]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["applied"] is True

    # neither an integer nor 'clear' → click usage error, no request made
    result = cli_runner().invoke(ctl_command, ["config", "--max-retries", "unset"])
    assert result.exit_code == 2
    assert "is not an integer or 'clear'" in result.stderr

    result = cli_runner().invoke(ctl_command, ["config", "--timeout=-5"])
    assert result.exit_code == 2
    assert "negative" in result.stderr

    # over the shared value bound -> click usage error, no request made
    from inspect_ai.model._generate_overrides import MAX_GENERATE_CONFIG_OVERRIDE

    result = cli_runner().invoke(
        ctl_command,
        ["config", "--attempt-timeout", str(MAX_GENERATE_CONFIG_OVERRIDE + 1)],
    )
    assert result.exit_code == 2
    assert "maximum override value" in result.stderr


def test_discovery_api_version_parsed_with_bootstrap_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`api_version` rides the discovery file; a file predating it is version 0.

    The missing-field default is the one-time bootstrap for processes
    launched before version reporting existed — the CLI gate treats them as
    understanding only since-0 knobs.
    """
    import inspect_ai._control.discovery as discovery
    import inspect_ai._util.process as process

    monkeypatch.setattr(discovery, "inspect_data_dir", lambda subdir=None: tmp_path)
    monkeypatch.setattr(process, "pid_alive", lambda pid: True)
    (tmp_path / "1.json").write_text(
        json.dumps(
            {
                "pid": 1,
                "socket_path": "/tmp/1.sock",
                "started_at": 1.0,
                "api_version": 3,
            }
        )
    )
    (tmp_path / "2.json").write_text(
        json.dumps({"pid": 2, "socket_path": "/tmp/2.sock", "started_at": 2.0})
    )
    servers = {s.pid: s for s in discovery.list_discovered_servers()}
    assert servers[1].api_version == 3
    assert servers[2].api_version == 0


def test_config_log_shared_rejects_below_one() -> None:
    """--log-shared validates up front like --log-buffer (IntRange min=1)."""
    result = cli_runner().invoke(ctl_command, ["config", "--log-shared", "0"])
    assert result.exit_code == 2
    assert "--log-shared" in result.stderr


def test_process_release_json_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "inspect_ai._cli.ctl.list_discovered_servers", lambda: [_DiscServer(7)]
    )
    monkeypatch.setattr(
        "inspect_ai._cli.ctl._request_json",
        lambda *a, **k: {"ok": True, "keep_alive": False, "changed": True},
    )
    result = cli_runner().invoke(ctl_command, ["process", "release", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["target"] == {"pid": 7}
    assert payload["applied"] is True and payload["dry_run"] is False
    assert payload["detail"] == {"keep_alive": False, "changed": True}


def test_process_keep_reports_idempotent_noop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "inspect_ai._cli.ctl.list_discovered_servers", lambda: [_DiscServer(7)]
    )
    monkeypatch.setattr(
        "inspect_ai._cli.ctl._request_json",
        lambda *a, **k: {"ok": True, "keep_alive": True, "changed": False},
    )
    result = cli_runner().invoke(ctl_command, ["process", "keep"])
    assert result.exit_code == 0
    assert "already on" in result.output


def test_process_keep_pid_is_positional(monkeypatch: pytest.MonkeyPatch) -> None:
    posted: list[str] = []

    def record(socket_path: str, path: str, **kwargs: Any) -> dict[str, Any]:
        posted.append(str(socket_path))
        return {"ok": True}

    monkeypatch.setattr(
        "inspect_ai._cli.ctl.list_discovered_servers",
        lambda: [_DiscServer(7), _DiscServer(8)],
    )
    monkeypatch.setattr("inspect_ai._cli.ctl._request_json", record)
    result = cli_runner().invoke(ctl_command, ["process", "keep", "8"])
    assert result.exit_code == 0, result.output
    assert posted == ["/tmp/8.sock"]


def test_process_list_json(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_surface(
        monkeypatch,
        [_full_summary("aaa111", "t1"), _full_summary("bbb222", "t2", pid=8)],
        servers=[_DiscServer(7), _DiscServer(8)],
    )
    result = cli_runner().invoke(ctl_command, ["process", "list", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert "as_of" in payload
    rows = payload["processes"]
    assert [r["pid"] for r in rows] == [7, 8]
    assert rows[0]["keep_alive"] is False
    assert rows[0]["tasks"] == [
        {"task_id": "aaa111", "task": "t1", "status": "running"}
    ]
    assert rows[1]["tasks"][0]["task_id"] == "bbb222"


def test_events_unseeded_defaults_to_recent_tail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The first events page is never empty: unseeded reads take a tail."""
    captured: dict[str, Any] = {}

    def fake_events(
        socket_path: Any, eval_id: str, sample_id: str, epoch: int, **kwargs: Any
    ) -> dict[str, Any]:
        captured.clear()
        captured.update(kwargs)
        return {"events": [], "next": None, "done": True}

    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    monkeypatch.setattr("inspect_ai._cli.ctl._fetch_sample_events", fake_events)
    runner = cli_runner()

    result = runner.invoke(ctl_command, ["sample", "events", "aaa111", "s1", "--json"])
    assert result.exit_code == 0, result.output
    assert captured["tail"] == 20

    # a cursor (or a wall-clock window) disables the default tail
    from inspect_ai._control.events import encode_cursor

    runner.invoke(
        ctl_command,
        ["sample", "events", "aaa111", "s1", "--cursor", encode_cursor("n", 3)],
    )
    assert captured["tail"] is None and captured["cursor"] == encode_cursor("n", 3)

    runner.invoke(
        ctl_command, ["sample", "events", "aaa111", "s1", "--since-time", "5.0"]
    )
    assert captured["tail"] is None and captured["since_time"] == 5.0

    # --until alone is also an explicit window: the server applies the tail
    # slice before the wall-clock filter, so a defaulted tail would reduce a
    # past window to an empty page
    runner.invoke(ctl_command, ["sample", "events", "aaa111", "s1", "--until", "5.0"])
    assert captured["tail"] is None and captured["until"] == 5.0

    # the resolved identifiers are echoed on the page
    result = runner.invoke(ctl_command, ["sample", "events", "aaa111", "s1", "--json"])
    payload = json.loads(result.stdout)
    assert payload["task_id"] == "aaa111"
    assert (payload["sample_id"], payload["epoch"]) == ("s1", 1)


def test_events_type_all_normalized_to_star(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--type all` is the blessed shell-safe spelling of `--type '*'`.

    Normalized client-side to the `*` wire value so it also works against a
    running server that predates the synonym; a comma list member normalizes
    the same way, and other members pass through untouched.
    """
    captured: dict[str, Any] = {}

    def fake_events(
        socket_path: Any, eval_id: str, sample_id: str, epoch: int, **kwargs: Any
    ) -> dict[str, Any]:
        captured.clear()
        captured.update(kwargs)
        return {"events": [], "next": None, "done": True}

    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    monkeypatch.setattr("inspect_ai._cli.ctl._fetch_sample_events", fake_events)
    runner = cli_runner()

    result = runner.invoke(
        ctl_command, ["sample", "events", "aaa111", "s1", "--type", "all"]
    )
    assert result.exit_code == 0, result.output
    assert captured["types"] == "*"

    runner.invoke(
        ctl_command, ["sample", "events", "aaa111", "s1", "--type", "model, all"]
    )
    assert captured["types"] == "model,*"

    # non-magic members pass through untouched (`*` stays a quiet synonym)
    runner.invoke(
        ctl_command, ["sample", "events", "aaa111", "s1", "--type", "model,tool"]
    )
    assert captured["types"] == "model,tool"

    runner.invoke(ctl_command, ["sample", "events", "aaa111", "s1", "--type", "*"])
    assert captured["types"] == "*"


def test_events_from_start_reads_full_backlog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--from-start` seeds the window at event 0 (no default tail)."""
    captured: dict[str, Any] = {}

    def fake_events(
        socket_path: Any, eval_id: str, sample_id: str, epoch: int, **kwargs: Any
    ) -> dict[str, Any]:
        captured.clear()
        captured.update(kwargs)
        return {"events": [], "next": None, "done": True}

    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    monkeypatch.setattr("inspect_ai._cli.ctl._fetch_sample_events", fake_events)
    runner = cli_runner()

    result = runner.invoke(
        ctl_command, ["sample", "events", "aaa111", "s1", "--from-start", "--json"]
    )
    assert result.exit_code == 0, result.output
    # no window params on the wire — an unseeded, tail-less read starts at 0
    assert captured["tail"] is None and captured["cursor"] is None
    assert captured["since_time"] is None

    # --until is allowed: bound a from-the-start read by wall clock
    result = runner.invoke(
        ctl_command,
        ["sample", "events", "aaa111", "s1", "--from-start", "--until", "5.0"],
    )
    assert result.exit_code == 0, result.output
    assert captured["tail"] is None and captured["until"] == 5.0


def test_events_from_start_conflicts_with_window_seeds() -> None:
    """`--from-start` rejects --cursor / --tail / --since-time."""
    from inspect_ai._control.events import encode_cursor

    runner = cli_runner()
    for extra in (
        ["--cursor", encode_cursor("n", 3)],
        ["--tail", "5"],
        ["--since-time", "5.0"],
    ):
        result = runner.invoke(
            ctl_command, ["sample", "events", "t", "s1", "--from-start", *extra]
        )
        assert result.exit_code == 1
        assert "--from-start" in result.stderr and extra[0] in result.stderr


def test_events_limit_rides_wire_and_combines_with_seeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--limit` is a page size: passed through, combinable with any seed."""
    captured: dict[str, Any] = {}

    def fake_events(
        socket_path: Any, eval_id: str, sample_id: str, epoch: int, **kwargs: Any
    ) -> dict[str, Any]:
        captured.clear()
        captured.update(kwargs)
        return {"events": [], "next": None, "done": True}

    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    monkeypatch.setattr("inspect_ai._cli.ctl._fetch_sample_events", fake_events)
    runner = cli_runner()

    result = runner.invoke(
        ctl_command,
        ["sample", "events", "aaa111", "s1", "--from-start", "--limit", "15"],
    )
    assert result.exit_code == 0, result.output
    assert captured["limit"] == 15

    # --limit is not a window seed: the unseeded default tail still applies
    result = runner.invoke(
        ctl_command, ["sample", "events", "aaa111", "s1", "--limit", "15"]
    )
    assert result.exit_code == 0, result.output
    assert captured["limit"] == 15 and captured["tail"] == 20

    # omitted → not on the wire (server default applies)
    runner.invoke(ctl_command, ["sample", "events", "aaa111", "s1"])
    assert captured["limit"] is None

    result = runner.invoke(
        ctl_command, ["sample", "events", "aaa111", "s1", "--limit", "0"]
    )
    assert result.exit_code == 1
    assert "--limit" in result.stderr


def test_events_json_no_servers_echoes_identifiers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The no-running-evals empty page keeps the identifier echo shape."""
    monkeypatch.setattr("inspect_ai._cli.ctl.list_discovered_servers", lambda: [])
    result = cli_runner().invoke(
        ctl_command, ["sample", "events", "aaa111", "s1", "--json"]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["task_id"] is None
    assert (payload["sample_id"], payload["epoch"]) == ("s1", 1)
    assert payload["events"] == [] and payload["next"] is None and payload["done"]


def test_group_option_before_verb_forwards(monkeypatch: pytest.MonkeyPatch) -> None:
    """A mirrored option given at the group level reaches the explicit verb."""
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    result = cli_runner().invoke(ctl_command, ["task", "--json", "list"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert "as_of" in payload
    assert payload["tasks"][0]["task_id"] == "aaa111"


def test_group_option_forwards_value_and_verb_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_samples(
        socket_path: Any,
        eval_id: str,
        active_since: float | None = None,
        **kwargs: Any,
    ) -> _SamplesPage:
        captured["active_since"] = active_since
        return _SamplesPage(as_of=123.0, samples=[])

    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    monkeypatch.setattr("inspect_ai._cli.ctl._fetch_samples", fake_samples)
    runner = cli_runner()

    result = runner.invoke(ctl_command, ["sample", "--active-since", "5.0", "list"])
    assert result.exit_code == 0, result.output
    assert captured["active_since"] == 5.0

    # the group value is a default only — spelled after the verb it wins
    result = runner.invoke(
        ctl_command,
        ["sample", "--active-since", "5.0", "list", "--active-since", "9.0"],
    )
    assert result.exit_code == 0, result.output
    assert captured["active_since"] == 9.0


def test_group_option_unsupported_by_verb_errors() -> None:
    """A mirrored option the verb doesn't accept fails, teaching `list`."""
    result = cli_runner().invoke(
        ctl_command, ["sample", "--active-since", "5.0", "show", "t", "s1"]
    )
    assert result.exit_code != 0
    assert "sample show" in result.stderr and "does not accept" in result.stderr
    assert "sample list --active-since" in result.stderr


def test_events_cursor_that_looks_like_timestamp_errors() -> None:
    result = cli_runner().invoke(
        ctl_command, ["sample", "events", "t", "s1", "--cursor", "1751900000.5"]
    )
    assert result.exit_code == 1
    assert "did you mean --since-time" in result.stderr


def test_events_garbage_cursor_errors() -> None:
    result = cli_runner().invoke(
        ctl_command, ["sample", "events", "t", "s1", "--cursor", "!!!"]
    )
    assert result.exit_code == 1
    assert "prior page" in result.stderr


def test_events_removed_since_flag_teaches_split() -> None:
    """A bare --since (the pre-rename cursor flag) routes by value type.

    click's stock no-such-option error would suggest --since-time, which is
    wrong for a cursor value — the hidden --since exists to give the right
    pointer for each.
    """
    ts = cli_runner().invoke(
        ctl_command, ["sample", "events", "t", "s1", "--since", "1751900000"]
    )
    assert ts.exit_code == 1
    assert "use --since-time" in ts.stderr

    cur = cli_runner().invoke(
        ctl_command, ["sample", "events", "t", "s1", "--since", "opaque-token"]
    )
    assert cur.exit_code == 1
    assert "--cursor" in cur.stderr and "prior page" in cur.stderr


def test_compose_config_labels_every_knob_with_scope() -> None:
    from inspect_ai._cli.ctl import _compose_config, _DirectiveScope

    scope = _DirectiveScope(
        socket_path="/tmp/7.sock",
        task_id="t1",
        task="tn",
        header="h",
        siblings=3,
    )
    limits_view = {
        "max_samples": {"limit": 3, "in_use": 1, "adjustable": True},
        "max_sandboxes": [{"type": "docker", "limit": 4, "in_use": 2}],
        "max_subprocesses": {"limit": 8, "in_use": 1},
        "adaptive": [],
        "buffer": {"log_buffer": 10, "pending": 2, "log_shared": None},
        "requested": {"max_samples": 3, "log_buffer": 5},
        "warnings": ["w"],
        "dry_run": False,
    }
    config = _compose_config(
        scope,
        limits_view,
        dry_run=False,
        set_values=True,
        notes=["blast radius"],
    )
    assert config["target"] == {"scope": "task", "task_id": "t1", "task": "tn"}
    assert config["knobs"]["max_samples"]["scope"] == "task"
    assert config["knobs"]["max_sandboxes"]["scope"] == "process"
    assert config["knobs"]["max_subprocesses"] == {
        "scope": "process",
        "limit": 8,
        "in_use": 1,
    }
    assert config["knobs"]["max_connections"]["scope"] == "process"
    assert config["knobs"]["log_buffer"]["scope"] == "task"
    assert config["knobs"]["log_shared"]["scope"] == "task"
    assert config["applied"] is True and config["dry_run"] is False
    assert config["requested"] == {"max_samples": 3, "log_buffer": 5}
    assert config["warnings"] == ["w"]
    assert config["notes"] == ["blast radius"]


def test_compose_config_process_scope_dry_run() -> None:
    from inspect_ai._cli.ctl import _compose_config, _DirectiveScope

    scope = _DirectiveScope(
        socket_path="/tmp/7.sock",
        task_id=None,
        task=None,
        header="process · 2 tasks",
        siblings=2,
    )
    limits_view = {
        "max_sandboxes": [],
        "adaptive": [],
        "requested": {"max_connections": 9},
        "warnings": [],
        "dry_run": True,
    }
    config = _compose_config(
        scope,
        limits_view,
        dry_run=True,
        set_values=True,
        notes=[],
    )
    assert config["target"]["scope"] == "process"
    assert "max_samples" not in config["knobs"]  # process view has no task knob
    assert "log_buffer" not in config["knobs"]
    assert config["applied"] is False and config["dry_run"] is True


def test_log_flush_resolves_sole_active_task(monkeypatch: pytest.MonkeyPatch) -> None:
    """log-flush follows the directive resolution rule (`_resolve_scope`).

    In an eval-set with one running and several completed tasks, the sole
    *active* task is the default target — the same rule `ctl config` uses —
    rather than erroring "task log-flush targets a single task".
    """
    _patch_surface(
        monkeypatch,
        [
            _full_summary("aaa111", "t1", status="completed"),
            _full_summary("bbb222", "t2", status="completed"),
            _full_summary("ccc333", "t3", status="running"),
        ],
    )
    monkeypatch.setattr(
        "inspect_ai._cli.ctl._post_flush", lambda *a, **k: {"flushed": 1}
    )
    result = cli_runner().invoke(ctl_command, ["task", "log-flush", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["target"]["task_id"] == "ccc333"


def test_log_flush_multiple_active_tasks_shows_candidate_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_surface(
        monkeypatch,
        [_full_summary("aaa111", "t1"), _full_summary("bbb222", "t2")],
    )
    result = cli_runner().invoke(ctl_command, ["task", "log-flush"])
    assert result.exit_code == 1
    assert "task log-flush targets a single task" in result.stderr
    assert "aaa111" in result.stderr and "bbb222" in result.stderr


def test_fetch_summaries_404_names_version_skew(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A 404 from a live server reads as version skew, not 'just exited'."""
    from inspect_ai._cli.ctl import _fetch_summaries

    _stub_httpx(monkeypatch, [(404, {"error": "not found"})])
    fetched = _fetch_summaries([_disc(7)])
    assert fetched.summaries == []
    assert fetched.busy_pids == []
    err = capsys.readouterr().err
    assert "different inspect version" in err
    assert "just exited" not in err


def test_log_flush_json_mutation_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    monkeypatch.setattr(
        "inspect_ai._cli.ctl._post_flush", lambda *a, **k: {"flushed": 2}
    )
    result = cli_runner().invoke(ctl_command, ["task", "log-flush", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["target"]["task_id"] == "aaa111"
    assert payload["applied"] is True and payload["dry_run"] is False
    assert payload["detail"] == {"flushed": 2}


class _RequestSpy:
    """Capture `_request_json` calls and answer with a canned response."""

    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.paths: list[str] = []
        self.params: list[dict[str, Any]] = []

    def __call__(self, socket_path: str, path: str, **kwargs: Any) -> dict[str, Any]:
        self.paths.append(path)
        self.params.append(kwargs.get("params") or {})
        return self.response


def test_task_cancel_requires_task_argument() -> None:
    """The destructive verb requires its selector outright — no sole-task default."""
    result = cli_runner().invoke(ctl_command, ["task", "cancel"])
    assert result.exit_code == 2
    assert "TASK" in result.stderr


def test_task_cancel_json_mutation_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    spy = _RequestSpy(
        {"ok": True, "task_id": "aaa111", "changed": True, "in_flight": 2}
    )
    monkeypatch.setattr("inspect_ai._cli.ctl._request_json", spy)
    result = cli_runner().invoke(ctl_command, ["task", "cancel", "aaa111", "--json"])
    assert result.exit_code == 0, result.output
    assert spy.paths == ["/tasks/aaa111/cancel"]
    assert spy.params == [{}]
    payload = json.loads(result.stdout)
    assert payload["target"]["task_id"] == "aaa111"
    assert payload["applied"] is True and payload["dry_run"] is False
    assert payload["detail"]["in_flight"] == 2


def test_task_cancel_dry_run_not_applied(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    spy = _RequestSpy({"ok": True, "changed": True, "dry_run": True, "in_flight": 1})
    monkeypatch.setattr("inspect_ai._cli.ctl._request_json", spy)
    result = cli_runner().invoke(
        ctl_command, ["task", "cancel", "aaa111", "--dry-run", "--json"]
    )
    assert result.exit_code == 0, result.output
    assert spy.params == [{"dry_run": True}]
    payload = json.loads(result.stdout)
    assert payload["applied"] is False and payload["dry_run"] is True


def test_task_cancel_noop_reports_unapplied(monkeypatch: pytest.MonkeyPatch) -> None:
    """The idempotent no-op (already finished) reports applied: false."""
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1", status="completed")])
    spy = _RequestSpy({"ok": True, "changed": False, "reason": "task already finished"})
    monkeypatch.setattr("inspect_ai._cli.ctl._request_json", spy)
    result = cli_runner().invoke(ctl_command, ["task", "cancel", "aaa111", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["applied"] is False
    assert payload["detail"]["reason"] == "task already finished"


def test_task_cancel_human_output(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    spy = _RequestSpy({"ok": True, "changed": True, "in_flight": 3})
    monkeypatch.setattr("inspect_ai._cli.ctl._request_json", spy)
    result = cli_runner().invoke(ctl_command, ["task", "cancel", "aaa111"])
    assert result.exit_code == 0, result.output
    assert "Cancel requested" in result.stdout
    assert "3 in-flight samples" in result.stdout


def test_task_cancel_missing_route_names_version_skew(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A router 404 (no `error` body) means the server predates the endpoint."""
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    _stub_httpx(monkeypatch, [(404, {"detail": "Not Found"})])
    result = cli_runner().invoke(ctl_command, ["task", "cancel", "aaa111"])
    assert result.exit_code == 1
    assert "older inspect without the cancel endpoint" in result.stderr
    assert "may have finished" not in result.stderr


def test_task_cancel_handler_404_means_task_gone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A handler 404 (`{"error": ...}` body) is definitive: the task is gone."""
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    _stub_httpx(monkeypatch, [(404, {"error": "task aaa111 not found"})])
    result = cli_runner().invoke(ctl_command, ["task", "cancel", "aaa111"])
    assert result.exit_code == 1
    assert "may have finished" in result.stderr
    assert "older inspect" not in result.stderr


def test_task_cancel_action_sent_on_current_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--action score`/`--action error` ride as the `action` query param."""
    from inspect_ai._control import CONTROL_API_VERSION

    _patch_surface(
        monkeypatch,
        [_full_summary("aaa111", "t1")],
        servers=[_DiscServer(7, api_version=CONTROL_API_VERSION)],
    )
    spy = _RequestSpy({"ok": True, "changed": True, "in_flight": 1})
    monkeypatch.setattr("inspect_ai._cli.ctl._request_json", spy)

    runner = cli_runner()
    score = runner.invoke(
        ctl_command, ["task", "cancel", "aaa111", "--action", "score"]
    )
    assert score.exit_code == 0, score.output
    error = runner.invoke(
        ctl_command, ["task", "cancel", "aaa111", "--action", "error", "--dry-run"]
    )
    assert error.exit_code == 0, error.output
    assert spy.params == [
        {"action": "score"},
        {"action": "error", "dry_run": True},
    ]


def test_task_cancel_rejects_unknown_action() -> None:
    result = cli_runner().invoke(
        ctl_command, ["task", "cancel", "aaa111", "--action", "explode"]
    )
    assert result.exit_code == 2
    assert "explode" in result.stderr


def test_task_pause_json_mutation_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    spy = _RequestSpy(
        {
            "ok": True,
            "task_id": "aaa111",
            "paused": "task",
            "changed": True,
            "dispatched": 2,
        }
    )
    monkeypatch.setattr("inspect_ai._cli.ctl._request_json", spy)
    result = cli_runner().invoke(ctl_command, ["task", "pause", "aaa111", "--json"])
    assert result.exit_code == 0, result.output
    assert spy.paths == ["/tasks/aaa111/pause"]
    assert spy.params == [{}]
    payload = json.loads(result.stdout)
    assert payload["target"]["task_id"] == "aaa111"
    assert payload["applied"] is True and payload["dry_run"] is False
    assert payload["detail"]["dispatched"] == 2


def test_task_pause_resolves_sole_running_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pause is reversible, so it gets the sole-task default (unlike cancel)."""
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    spy = _RequestSpy({"ok": True, "changed": True, "dispatched": 0})
    monkeypatch.setattr("inspect_ai._cli.ctl._request_json", spy)
    result = cli_runner().invoke(ctl_command, ["task", "pause", "--json"])
    assert result.exit_code == 0, result.output
    assert spy.paths == ["/tasks/aaa111/pause"]


def test_task_pause_multiple_tasks_requires_selector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_surface(
        monkeypatch, [_full_summary("aaa111", "t1"), _full_summary("bbb222", "t2")]
    )
    result = cli_runner().invoke(ctl_command, ["task", "pause"])
    assert result.exit_code == 1
    assert "task pause targets a single task" in result.stderr


def test_task_pause_dry_run_not_applied(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    spy = _RequestSpy({"ok": True, "changed": True, "dry_run": True, "dispatched": 1})
    monkeypatch.setattr("inspect_ai._cli.ctl._request_json", spy)
    result = cli_runner().invoke(
        ctl_command, ["task", "pause", "aaa111", "--dry-run", "--json"]
    )
    assert result.exit_code == 0, result.output
    assert spy.params == [{"dry_run": True}]
    payload = json.loads(result.stdout)
    assert payload["applied"] is False and payload["dry_run"] is True


def test_task_pause_human_output(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    spy = _RequestSpy({"ok": True, "paused": "task", "changed": True, "dispatched": 3})
    monkeypatch.setattr("inspect_ai._cli.ctl._request_json", spy)
    result = cli_runner().invoke(ctl_command, ["task", "pause", "aaa111"])
    assert result.exit_code == 0, result.output
    assert "Pause requested" in result.output
    assert "3 dispatched samples" in result.output


def test_task_resume_human_output_notes_process_latch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A task resume that leaves the task held by the process latch says so."""
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    spy = _RequestSpy({"ok": True, "paused": "process", "changed": True})
    monkeypatch.setattr("inspect_ai._cli.ctl._request_json", spy)
    result = cli_runner().invoke(ctl_command, ["task", "resume", "aaa111"])
    assert result.exit_code == 0, result.output
    assert spy.paths == ["/tasks/aaa111/resume"]
    assert "Resume requested" in result.output
    assert "process is paused" in result.output


def test_task_resume_noop_notes_process_latch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resuming a task held only by the process latch points at the real hold.

    The no-op reason ("task is not paused") is technically right — the task
    gate is open — but an operator who saw the task listed as paused needs to
    know a `process resume` is what un-holds it.
    """
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    spy = _RequestSpy(
        {
            "ok": True,
            "paused": "process",
            "changed": False,
            "reason": "task is not paused",
        }
    )
    monkeypatch.setattr("inspect_ai._cli.ctl._request_json", spy)
    result = cli_runner().invoke(ctl_command, ["task", "resume", "aaa111"])
    assert result.exit_code == 0, result.output
    assert "Nothing to do: task is not paused." in result.output
    assert "process is paused" in result.output


def test_task_pause_noop_reports_unapplied(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    spy = _RequestSpy({"ok": True, "changed": False, "reason": "task already paused"})
    monkeypatch.setattr("inspect_ai._cli.ctl._request_json", spy)
    result = cli_runner().invoke(ctl_command, ["task", "pause", "aaa111", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["applied"] is False
    assert payload["detail"]["reason"] == "task already paused"


def test_task_pause_missing_route_names_version_skew(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    _stub_httpx(monkeypatch, [(404, {"detail": "Not Found"})])
    result = cli_runner().invoke(ctl_command, ["task", "pause", "aaa111"])
    assert result.exit_code == 1
    assert "older inspect without the pause/resume endpoints" in result.stderr


def test_process_pause_json_mutation_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "inspect_ai._cli.ctl.list_discovered_servers", lambda: [_DiscServer(7)]
    )
    spy = _RequestSpy({"ok": True, "paused": True, "changed": True})
    monkeypatch.setattr("inspect_ai._cli.ctl._request_json", spy)
    result = cli_runner().invoke(ctl_command, ["process", "pause", "--json"])
    assert result.exit_code == 0, result.output
    assert spy.paths == ["/pause"]
    assert spy.params == [{}]
    payload = json.loads(result.stdout)
    assert payload["target"] == {"pid": 7}
    assert payload["applied"] is True and payload["dry_run"] is False


def test_process_resume_pid_is_positional(monkeypatch: pytest.MonkeyPatch) -> None:
    posted: list[str] = []

    def record(socket_path: str, path: str, **kwargs: Any) -> dict[str, Any]:
        posted.append(str(socket_path))
        return {"ok": True, "paused": False, "changed": True}

    monkeypatch.setattr(
        "inspect_ai._cli.ctl.list_discovered_servers",
        lambda: [_DiscServer(7), _DiscServer(8)],
    )
    monkeypatch.setattr("inspect_ai._cli.ctl._request_json", record)
    result = cli_runner().invoke(ctl_command, ["process", "resume", "8"])
    assert result.exit_code == 0, result.output
    assert posted == ["/tmp/8.sock"]


def test_process_pause_dry_run_rides_query_param(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "inspect_ai._cli.ctl.list_discovered_servers", lambda: [_DiscServer(7)]
    )
    # `paused` is the actual latch state, still False under a dry-run pause
    spy = _RequestSpy({"ok": True, "paused": False, "changed": True, "dry_run": True})
    monkeypatch.setattr("inspect_ai._cli.ctl._request_json", spy)
    result = cli_runner().invoke(
        ctl_command, ["process", "pause", "--dry-run", "--json"]
    )
    assert result.exit_code == 0, result.output
    assert spy.params == [{"dry_run": True}]
    payload = json.loads(result.stdout)
    assert payload["applied"] is False and payload["dry_run"] is True


def test_process_pause_noop_human_output(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "inspect_ai._cli.ctl.list_discovered_servers", lambda: [_DiscServer(7)]
    )
    monkeypatch.setattr(
        "inspect_ai._cli.ctl._request_json",
        lambda *a, **k: {
            "ok": True,
            "paused": True,
            "changed": False,
            "reason": "process already paused",
        },
    )
    result = cli_runner().invoke(ctl_command, ["process", "pause"])
    assert result.exit_code == 0, result.output
    assert "Nothing to do" in result.output
    assert "already paused" in result.output


def test_sample_cancel_defaults_epoch_for_single_epoch_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary = _full_summary("aaa111", "t1")
    summary["epochs"] = 1
    _patch_surface(monkeypatch, [summary])
    spy = _RequestSpy({"ok": True, "sample_id": "s1", "epoch": 1, "changed": True})
    monkeypatch.setattr("inspect_ai._cli.ctl._request_json", spy)
    result = cli_runner().invoke(
        ctl_command, ["sample", "cancel", "aaa111", "s1", "--json"]
    )
    assert result.exit_code == 0, result.output
    assert spy.paths == ["/evals/eval_aaa111/sample/cancel"]
    assert spy.params == [{"sample_id": "s1", "epoch": 1, "action": "score"}]
    payload = json.loads(result.stdout)
    assert payload["target"]["sample_id"] == "s1"
    assert payload["target"]["epoch"] == 1
    assert payload["applied"] is True


def test_sample_cancel_requires_epoch_when_multi_epoch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A defaulted epoch on a multi-epoch task resolves to a different sample."""
    summary = _full_summary("aaa111", "t1")
    summary["epochs"] = 3
    _patch_surface(monkeypatch, [summary])
    spy = _RequestSpy({"ok": True, "changed": True})
    monkeypatch.setattr("inspect_ai._cli.ctl._request_json", spy)
    result = cli_runner().invoke(ctl_command, ["sample", "cancel", "aaa111", "s1"])
    assert result.exit_code == 1
    assert "pass EPOCH explicitly" in result.stderr
    assert spy.paths == []  # nothing was sent

    # ...and an explicit epoch goes through
    ok = cli_runner().invoke(ctl_command, ["sample", "cancel", "aaa111", "s1", "2"])
    assert ok.exit_code == 0, ok.output
    assert spy.params == [{"sample_id": "s1", "epoch": 2, "action": "score"}]


def test_sample_cancel_error_flag_and_dry_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary = _full_summary("aaa111", "t1")
    summary["epochs"] = 1
    _patch_surface(monkeypatch, [summary])
    spy = _RequestSpy(
        {"ok": True, "sample_id": "s1", "epoch": 1, "changed": True, "dry_run": True}
    )
    monkeypatch.setattr("inspect_ai._cli.ctl._request_json", spy)
    result = cli_runner().invoke(
        ctl_command,
        [
            "sample",
            "cancel",
            "aaa111",
            "s1",
            "--action",
            "error",
            "--dry-run",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    assert spy.params == [
        {"sample_id": "s1", "epoch": 1, "action": "error", "dry_run": True}
    ]
    payload = json.loads(result.stdout)
    assert payload["applied"] is False and payload["dry_run"] is True


def test_sample_cancel_cancel_action_sent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary = _full_summary("aaa111", "t1")
    summary["epochs"] = 1
    _patch_surface(monkeypatch, [summary])
    spy = _RequestSpy({"ok": True, "sample_id": "s1", "epoch": 1, "changed": True})
    monkeypatch.setattr("inspect_ai._cli.ctl._request_json", spy)
    result = cli_runner().invoke(
        ctl_command,
        ["sample", "cancel", "aaa111", "s1", "--action", "cancel", "--json"],
    )
    assert result.exit_code == 0, result.output
    assert spy.params == [{"sample_id": "s1", "epoch": 1, "action": "cancel"}]
    assert json.loads(result.stdout)["applied"] is True


def test_sample_cancel_rejects_unknown_action() -> None:
    result = cli_runner().invoke(
        ctl_command, ["sample", "cancel", "aaa111", "s1", "--action", "explode"]
    )
    assert result.exit_code == 2
    assert "explode" in result.stderr


def test_sample_cancel_noop_human_output(monkeypatch: pytest.MonkeyPatch) -> None:
    summary = _full_summary("aaa111", "t1")
    summary["epochs"] = 1
    _patch_surface(monkeypatch, [summary])
    spy = _RequestSpy(
        {
            "ok": True,
            "sample_id": "s1",
            "epoch": 1,
            "changed": False,
            "status": "completed",
            "reason": "sample already finished",
        }
    )
    monkeypatch.setattr("inspect_ai._cli.ctl._request_json", spy)
    result = cli_runner().invoke(ctl_command, ["sample", "cancel", "aaa111", "s1"])
    assert result.exit_code == 0, result.output
    assert "already finished" in result.stdout
    assert "status: completed" in result.stdout


def test_print_config_process_scope_shows_buffer_placeholder(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The process-level view points at the per-task buffer knobs.

    Mirrors the max_samples placeholder, so `ctl config` (and the deprecated
    `ctl buffer` alias) in a multi-task process never silently omits them.
    """
    from inspect_ai._cli.ctl import _print_config

    _print_config(
        {
            "target": {"scope": "process", "task_id": None, "task": None},
            "dry_run": False,
            "knobs": {
                "max_sandboxes": {"scope": "process", "providers": []},
                "max_connections": {"scope": "process", "adaptive": []},
            },
            "requested": None,
            "warnings": [],
            "notes": [],
        },
        changed=False,
    )
    out = capsys.readouterr().out
    assert "log buffer [task]:          per task (pass a task to view/set)" in out
    assert "shared sync [task]:         per task (pass a task to view/set)" in out


def test_resolve_scope_siblings_counts_active_only() -> None:
    """Completed eval-set siblings don't inflate the blast-radius count."""
    from inspect_ai._cli.ctl import _resolve_scope

    summaries = [
        _full_summary("aaa111", "t1", status="running"),
        _full_summary("bbb222", "t2", status="completed"),
    ]
    scope = _resolve_scope([], summaries, "aaa111")
    assert scope is not None
    assert scope.siblings == 1  # the completed sibling is excluded


def test_keep_alias_accepts_positional_pid(monkeypatch: pytest.MonkeyPatch) -> None:
    """The shared ambiguity error teaches `... keep <pid>`; the alias obeys."""
    posted: list[str] = []

    def record(socket_path: str, path: str, **kwargs: Any) -> dict[str, Any]:
        posted.append(str(socket_path))
        return {"ok": True}

    monkeypatch.setattr(
        "inspect_ai._cli.ctl.list_discovered_servers",
        lambda: [_DiscServer(7), _DiscServer(8)],
    )
    monkeypatch.setattr("inspect_ai._cli.ctl._request_json", record)
    result = cli_runner().invoke(ctl_command, ["keep", "8"])
    assert result.exit_code == 0, result.output
    assert posted == ["/tmp/8.sock"]
    assert "is now `inspect ctl process keep`" in result.stderr


def test_sample_list_unscoped_skips_busy_eval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A busy eval (listing retries exhausted) is skipped, not fatal.

    Mirrors the unreachable-skip: the fan-out opts into _ServerBusy so one
    busy sibling can't kill the whole listing and discard other evals' rows.
    """
    from inspect_ai._cli.ctl import _ServerBusy

    _patch_surface(
        monkeypatch,
        [_full_summary("aaa111", "t1"), _full_summary("bbb222", "t2")],
    )
    _patch_samples_unreachable_for(
        monkeypatch, "eval_aaa111", exc=_ServerBusy("no response after 2 attempts")
    )
    result = cli_runner().invoke(ctl_command, ["sample", "list", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert [s["task_id"] for s in payload["samples"]] == ["bbb222"]
    assert "Skipping eval eval_aaa111" in result.stderr
    assert "try again shortly" in result.stderr


def test_sample_list_all_processes_busy_fails_honest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every process busy-skipped → an honest non-zero exit, not 'nothing running'.

    An alive-but-busy eval must never produce the 'No running evals' message
    (or an empty --json envelope with exit 0) that a polling agent would read
    as nothing-to-see.
    """
    _patch_surface(monkeypatch, [], busy_pids=[7])
    result = cli_runner().invoke(ctl_command, ["sample", "list", "--json"])
    assert result.exit_code == 1
    assert "No tasks visible" in result.stderr
    assert "pid 7 busy" in result.stderr
    assert "No running evals" not in result.output


def test_sample_events_all_processes_busy_fails_honest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All-busy `sample events` exits non-zero rather than emitting done:true.

    The empty done:true page would falsely end a polling loop for an eval
    whose events may live on the busy pid.
    """
    _patch_surface(monkeypatch, [], busy_pids=[7])
    result = cli_runner().invoke(
        ctl_command, ["sample", "events", "t1", "s1", "--json"]
    )
    assert result.exit_code == 1
    assert "No tasks visible" in result.stderr
    assert "done" not in result.stdout


def test_scoped_sample_not_found_names_busy_pid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A scoped miss with a busy-skipped process qualifies the not-found error.

    The target may live on the busy process, so the bare 'No running task
    matching' would mislead; the error names the skipped pid instead.
    """
    _patch_surface(
        monkeypatch,
        [_full_summary("bbb222", "t2", pid=8)],
        servers=[_DiscServer(7), _DiscServer(8)],
        busy_pids=[7],
    )
    result = cli_runner().invoke(ctl_command, ["sample", "list", "aaa111", "--json"])
    assert result.exit_code == 1
    assert "No running task matching 'aaa111'" in result.stderr
    assert "among responsive processes" in result.stderr
    assert "pid 7 busy" in result.stderr


def test_scoped_resolution_caveats_partial_discovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A loose match with a busy-skipped process warns it may be incomplete.

    Name matches and short hand-typed id prefixes could collide with a task
    on the busy process, so they carry a stderr caveat; an exact id or a
    prefix of at least the truncated ``task list`` display length can't
    name a different task and stays quiet (the caveat must not cry wolf on
    the routine paste-a-truncated-id workflow).
    """
    task_id = "b7GzXqWm4KTepR2AhcVdNu"  # realistic 22-char shortuuid
    _patch_surface(
        monkeypatch,
        [_full_summary(task_id, "t2", pid=8)],
        samples_by_eval={f"eval_{task_id}": [_sample_row("s1")]},
        servers=[_DiscServer(7), _DiscServer(8)],
        busy_pids=[7],
    )
    runner = cli_runner()

    for loose_query in ("t2", task_id[:4]):
        result = runner.invoke(ctl_command, ["sample", "list", loose_query, "--json"])
        assert result.exit_code == 0, result.output
        assert "among responsive processes only" in result.stderr

    for unique_query in (task_id, task_id[:_SHORT_ID_LEN]):
        result = runner.invoke(ctl_command, ["sample", "list", unique_query, "--json"])
        assert result.exit_code == 0, result.output
        assert "among responsive processes only" not in result.stderr


def test_ambiguous_match_notes_busy_skipped_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ambiguity candidate table is qualified when discovery was partial.

    The busy pid may hold further (possibly the intended) candidates, so
    the table must not present itself as the complete match set.
    """
    _patch_surface(
        monkeypatch,
        [
            _full_summary("aaa111", "gpqa", pid=8),
            _full_summary("bbb222", "gpqa", pid=8),
        ],
        servers=[_DiscServer(7), _DiscServer(8)],
        busy_pids=[7],
    )
    result = cli_runner().invoke(ctl_command, ["sample", "list", "gpqa", "--json"])
    assert result.exit_code == 1
    assert "matches multiple tasks" in result.stderr
    assert "candidates drawn from responsive processes only" in result.stderr


def test_keep_alive_retries_busy_timeout(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """keep/release ride the narrated retrying policy (idempotent latches)."""
    import httpx

    from inspect_ai._cli.ctl import _request_json

    counter = _stub_httpx(
        monkeypatch,
        [httpx.ReadTimeout("slow"), {"ok": True, "keep_alive": True}],
    )
    body = _request_json(
        "/tmp/x.sock",
        "/keep",
        what="keep-alive for pid 7",
        not_found="unsupported",
        mutate="post",
        retry_mutation=True,
    )
    assert body == {"ok": True, "keep_alive": True}
    assert counter["posts"] == 2  # retried once, then succeeded
    assert "retrying" in capsys.readouterr().err


# --- --json error envelope ---------------------------------------------------


def _error_envelope(result: Any) -> dict[str, Any]:
    """Parse the `{"error": {...}}` stdout envelope of a failed --json run."""
    payload = json.loads(result.stdout)
    assert set(payload) == {"error"}
    error = payload["error"]
    # uniform shape: all four fields present on every failure
    assert set(error) == {"kind", "exception", "message", "status"}
    return dict(error)


def test_json_busy_failure_emits_error_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A read that exhausts its busy retries fails with a `busy` envelope.

    The starvation diagnosis (event loop busy — retry, don't declare the
    eval gone) must be a field an agent branches on, not a stderr regex.
    """
    import httpx

    from inspect_ai._cli.ctl import _REQUEST_ATTEMPTS

    monkeypatch.setattr(
        "inspect_ai._cli.ctl.list_discovered_servers", lambda: [_DiscServer(7)]
    )
    _stub_httpx(monkeypatch, [httpx.ReadTimeout("slow")] * _REQUEST_ATTEMPTS)
    result = cli_runner().invoke(ctl_command, ["task", "list", "--json"])
    assert result.exit_code == 1
    error = _error_envelope(result)
    assert error["kind"] == "busy"
    assert error["exception"] == "httpx.ReadTimeout"
    assert error["status"] is None
    assert "gave up" in error["message"]
    # the stderr narration is unchanged (it remains the human channel)
    assert "gave up" in result.stderr


def test_json_all_busy_emits_busy_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The all-processes-busy exit carries the `busy` envelope on --json.

    Distinguishable from the empty success envelope (nothing running) by
    shape, and from 'gone' transport kinds by `kind` — a polling agent
    should retry shortly, not stop.
    """
    _patch_surface(monkeypatch, [], busy_pids=[7])
    result = cli_runner().invoke(ctl_command, ["sample", "list", "--json"])
    assert result.exit_code == 1
    error = _error_envelope(result)
    assert error["kind"] == "busy"
    assert "pid 7 busy" in error["message"]


def test_json_not_found_selector_emits_error_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")], samples_by_eval={})
    result = cli_runner().invoke(ctl_command, ["sample", "list", "nope", "--json"])
    assert result.exit_code == 1
    error = _error_envelope(result)
    assert error["kind"] == "not_found"
    assert "nope" in error["message"]
    assert error["exception"] is None
    assert error["status"] is None


def test_json_ambiguous_selector_envelope_carries_candidates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ambiguity envelope message is self-contained (the table is stderr-only)."""
    _patch_surface(
        monkeypatch,
        [_full_summary("aaa111", "gpqa"), _full_summary("bbb222", "gpqa")],
        samples_by_eval={},
    )
    result = cli_runner().invoke(ctl_command, ["sample", "list", "gpqa", "--json"])
    assert result.exit_code == 1
    error = _error_envelope(result)
    assert error["kind"] == "ambiguous"
    assert "aaa111" in error["message"] and "bbb222" in error["message"]


def test_json_http_404_envelope_carries_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    _stub_httpx(monkeypatch, [(404, {})])
    result = cli_runner().invoke(
        ctl_command, ["sample", "show", "aaa111", "s1", "--json"]
    )
    assert result.exit_code == 1
    error = _error_envelope(result)
    assert error["kind"] == "not_found"
    assert error["status"] == 404
    assert "not found" in error["message"]


def test_json_scoped_unreachable_envelope_kind_connect_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A scoped read against a vanished process reports the transport cause."""
    _patch_surface(
        monkeypatch,
        [_full_summary("aaa111", "t1"), _full_summary("bbb222", "t2")],
    )
    _patch_samples_unreachable_for(monkeypatch, "eval_aaa111")
    result = cli_runner().invoke(ctl_command, ["sample", "list", "aaa111", "--json"])
    assert result.exit_code == 1
    error = _error_envelope(result)
    assert error["kind"] == "connect_error"
    assert error["exception"] == "httpx.ConnectError"
    assert "Failed to read samples for eval eval_aaa111" in error["message"]


def test_json_mutation_failure_emits_error_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mutations get the same envelope shape as reads."""
    monkeypatch.setattr("inspect_ai._cli.ctl.list_discovered_servers", lambda: [])
    result = cli_runner().invoke(ctl_command, ["process", "keep", "--json"])
    assert result.exit_code == 1
    error = _error_envelope(result)
    assert error["kind"] == "not_found"
    assert "No running inspect processes found" in error["message"]


@pytest.mark.parametrize(
    ("kind", "exception", "status"),
    [
        ("connect_timeout", "httpx.ConnectTimeout", None),
        ("read_timeout", "httpx.ReadTimeout", None),
        ("http_error", "httpx.HTTPStatusError", 500),
        ("invalid_response", "json.JSONDecodeError", None),
    ],
)
def test_json_single_shot_mutation_envelope_kinds(
    kind: str,
    exception: str,
    status: int | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The rest of the `kind` vocabulary, pinned through the single-shot path.

    `task log-flush` is a non-idempotent mutation (`_request_json` without
    `retry_mutation`), so a transport failure skips the retry loop and
    classifies directly via `_CtlFailure.from_exception` — the only path that
    can produce `connect_timeout`/`read_timeout`. Since `kind` is the closed
    vocabulary agents branch on, this pins the `_classify` isinstance
    ordering (`ConnectTimeout` before its `TimeoutException` base) plus the
    non-404 `http_error` and undecodable-body kinds.
    """
    import httpx

    failure_by_kind: dict[str, object] = {
        "connect_timeout": httpx.ConnectTimeout("connect timed out"),
        "read_timeout": httpx.ReadTimeout("slow"),
        "http_error": (500, {}),
        "invalid_response": json.JSONDecodeError("Expecting value", "<html>", 0),
    }
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    _stub_httpx(monkeypatch, [failure_by_kind[kind]])
    result = cli_runner().invoke(ctl_command, ["task", "log-flush", "--json"])
    assert result.exit_code == 1
    error = _error_envelope(result)
    assert error["kind"] == kind
    assert error["exception"] == exception
    assert error["status"] == status
    assert "Failed to update log-flush of task aaa111" in error["message"]


def test_json_invalid_cursor_emits_error_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    result = cli_runner().invoke(
        ctl_command,
        ["sample", "events", "aaa111", "s1", "--cursor", "12345", "--json"],
    )
    assert result.exit_code == 1
    error = _error_envelope(result)
    assert error["kind"] == "invalid_request"
    assert "--since-time" in error["message"]


def test_json_unexpected_exception_envelope_with_traceback_on_stderr(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unhandled exception still yields an envelope; the traceback stays on stderr."""

    def boom() -> list[Any]:
        raise RuntimeError("boom")

    monkeypatch.setattr("inspect_ai._cli.ctl.list_discovered_servers", boom)
    result = cli_runner().invoke(ctl_command, ["task", "list", "--json"])
    assert result.exit_code == 1
    error = _error_envelope(result)
    assert error["kind"] == "internal"
    assert error["exception"] == "RuntimeError"
    assert error["message"] == "boom"
    assert "Traceback" in result.stderr


def test_human_failure_output_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without --json, failures keep stderr prose and an empty stdout."""
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")], samples_by_eval={})
    result = cli_runner().invoke(ctl_command, ["sample", "list", "nope"])
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "No running task matching 'nope'" in result.stderr


def test_human_unexpected_exception_not_swallowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without --json, an unhandled exception propagates as before."""

    def boom() -> list[Any]:
        raise RuntimeError("boom")

    monkeypatch.setattr("inspect_ai._cli.ctl.list_discovered_servers", boom)
    result = cli_runner().invoke(ctl_command, ["task", "list"])
    assert result.exit_code != 0
    assert isinstance(result.exception, RuntimeError)


def test_envelope_failures_rejects_runner_without_as_json() -> None:
    """Decorating a runner lacking `as_json` fails at import, not silently.

    Without the guard, such a runner would bind `as_json=False` for every
    call and quietly revert its command to unstructured failures.
    """
    from inspect_ai._cli.ctl import _envelope_failures

    with pytest.raises(TypeError, match="as_json"):

        @_envelope_failures
        def _runner_without_flag(task: str) -> None:  # pragma: no cover
            pass


def test_resolve_scope_completed_target_counts_toward_siblings() -> None:
    """Naming a completed task doesn't suppress the blast-radius note.

    The named target counts even when completed — the retune reaches a
    *different* (active) task, which is exactly what the note exists to say.
    """
    from inspect_ai._cli.ctl import _resolve_scope

    summaries = [
        _full_summary("aaa111", "t1", status="completed"),
        _full_summary("bbb222", "t2", status="running"),
    ]
    scope = _resolve_scope([], summaries, "aaa111")
    assert scope is not None
    assert scope.siblings == 2  # running sibling + the named completed target
