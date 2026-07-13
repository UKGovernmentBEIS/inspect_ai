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
from click.testing import CliRunner

from inspect_ai._cli.ctl import (
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


def _runner() -> CliRunner:
    """A CliRunner that captures stderr separately across click versions.

    click < 8.2 mixes stderr into output unless ``mix_stderr=False``; click
    >= 8.2 removed the parameter and always captures stderr separately.
    """
    try:
        return CliRunner(mix_stderr=False)  # type: ignore[call-arg]
    except TypeError:
        return CliRunner()


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
    result = _runner().invoke(
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
        monkeypatch.setattr(
            "inspect_ai._cli.ctl._fetch_samples",
            lambda socket_path, eval_id, active_since=None, **kwargs: _SamplesPage(
                as_of=123.0,
                samples=samples_by_eval.get(eval_id, []),
            ),
        )


def test_bare_task_noun_implies_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """`ctl task --json` (no verb) runs `list` — with the mirrored option."""
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    result = _runner().invoke(ctl_command, ["task", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert "as_of" in payload
    assert payload["tasks"][0]["task_id"] == "aaa111"


def test_task_list_explicit_matches_bare(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    runner = _runner()
    bare = runner.invoke(ctl_command, ["task", "--json"]).output
    explicit = runner.invoke(ctl_command, ["task", "list", "--json"]).output
    assert json.loads(bare)["tasks"] == json.loads(explicit)["tasks"]


def test_sample_selector_in_verb_slot_teaches() -> None:
    """The implied-list default never fires past a positional; the error teaches."""
    result = _runner().invoke(ctl_command, ["sample", "my-task"])
    assert result.exit_code != 0
    assert "sample list my-task" in result.stderr
    # ...and points the old `ctl sample TASK SID` invocation at `sample show`
    assert "sample show my-task" in result.stderr


def test_bare_sample_noun_empty_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    """`ctl sample --json` with nothing running emits an empty envelope."""
    _patch_surface(monkeypatch, [], samples_by_eval={})
    result = _runner().invoke(ctl_command, ["sample", "--json"])
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
    result = _runner().invoke(ctl_command, ["sample", "list", "--json"])
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
    result = _runner().invoke(ctl_command, ["sample", "list", "aaa111", "--json"])
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
    result = _runner().invoke(ctl_command, ["sample", "errors", "--json"])
    payload = json.loads(result.stdout)
    assert [(r["task_id"], r["sample_id"]) for r in payload["samples"]] == [
        ("aaa111", "bad"),
        ("bbb222", "retried"),
    ]


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
    result = _runner().invoke(ctl_command, ["sample", "list", "--json"])
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
    result = _runner().invoke(ctl_command, ["sample", "list", "--json"])
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
    result = _runner().invoke(ctl_command, ["sample", "list"])
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
    result = _runner().invoke(ctl_command, ["sample", "errors"])
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
    result = _runner().invoke(ctl_command, ["sample", "list", "aaa111", "--json"])
    assert result.exit_code == 1
    assert "Failed to read samples for eval eval_aaa111" in result.stderr


def test_sample_show_merges_summary_row_and_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`show` reports the full sample summary, not just the error detail."""
    _patch_surface(
        monkeypatch,
        [_full_summary("aaa111", "t1")],
        samples_by_eval={"eval_aaa111": [_sample_row("s1", total_tokens=42)]},
    )
    detail = {
        "sample_id": "s1",
        "epoch": 1,
        "status": "error",
        "retries": 0,
        "error": {"message": "boom"},
        "error_retries": [],
        "scores": {},
    }
    monkeypatch.setattr(
        "inspect_ai._cli.ctl._fetch_sample_detail", lambda *a, **k: detail
    )
    result = _runner().invoke(ctl_command, ["sample", "show", "aaa111", "s1", "--json"])
    payload = json.loads(result.stdout)
    assert payload["task_id"] == "aaa111"
    assert payload["total_tokens"] == 42  # from the listing row
    assert payload["error"] == {"message": "boom"}  # detail wins on overlap
    assert payload["status"] == "error"
    assert (payload["sample_id"], payload["epoch"]) == ("s1", 1)  # echoed


def test_sample_show_listing_unreachable_keeps_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`show` still answers from the fetched detail if the listing read fails.

    The process exiting between the detail read and the supplemental listing
    read costs only the summary fields (timing / tokens / messages), not the
    authoritative detail already in hand.
    """
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    _patch_samples_unreachable_for(monkeypatch, "eval_aaa111")
    detail = {
        "sample_id": "s1",
        "epoch": 1,
        "status": "error",
        "retries": 0,
        "error": {"message": "boom"},
        "error_retries": [],
        "scores": {},
    }
    monkeypatch.setattr(
        "inspect_ai._cli.ctl._fetch_sample_detail", lambda *a, **k: detail
    )
    result = _runner().invoke(ctl_command, ["sample", "show", "aaa111", "s1", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["error"] == {"message": "boom"}
    assert "total_tokens" not in payload  # the listing row never arrived
    assert "Could not read the samples listing for eval eval_aaa111" in result.stderr


def test_sample_show_busy_listing_keeps_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A busy eval (listing retries exhausted) doesn't discard the detail.

    The listing read opts into _ServerBusy on retry exhaustion, which the
    same except-_ServerUnreachable fallback covers; the detail already in
    hand must still be rendered.
    """
    from inspect_ai._cli.ctl import _ServerBusy

    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    _patch_samples_unreachable_for(
        monkeypatch,
        "eval_aaa111",
        exc=_ServerBusy("no response after 2 attempts — the eval's event loop is busy"),
    )
    detail = {
        "sample_id": "s1",
        "epoch": 1,
        "status": "error",
        "retries": 0,
        "error": {"message": "boom"},
        "error_retries": [],
        "scores": {},
    }
    monkeypatch.setattr(
        "inspect_ai._cli.ctl._fetch_sample_detail", lambda *a, **k: detail
    )
    result = _runner().invoke(ctl_command, ["sample", "show", "aaa111", "s1", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["error"] == {"message": "boom"}
    assert "Could not read the samples listing" in result.stderr
    assert "busy" in result.stderr


def test_old_flat_spellings_hidden_from_help() -> None:
    result = _runner().invoke(ctl_command, ["--help"])
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
    result = _runner().invoke(ctl_command, ["tasks", "--json"])
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
        knobs = (
            "max_samples",
            "max_sandboxes",
            "max_connections",
            "log_buffer",
            "log_shared",
        )
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
    result = _runner().invoke(ctl_command, ["limits", "--json"])
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
    result = _runner().invoke(ctl_command, ["config", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert "log_buffer" not in payload["knobs"]
    assert any("log_buffer" in w for w in payload["warnings"])

    human = _runner().invoke(ctl_command, ["config"])
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
    result = _runner().invoke(ctl_command, ["config", "--log-buffer", "2"])
    assert result.exit_code == 1
    assert "has no sample buffer" in result.stderr
    assert "still applied" not in result.stderr  # no limits knob was set

    both = _runner().invoke(
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
    result = _runner().invoke(
        ctl_command, ["config", "--log-buffer", "2", "--max-samples", "5"]
    )
    assert result.exit_code == 1
    assert "has no sample buffer" in result.stderr
    assert "still applied" not in result.stderr
    assert "! max_samples is not adjustable" in result.stderr
    # the buffer warning restates the headline error and is not repeated
    assert "! log_buffer" not in result.stderr


def test_config_task_knob_with_only_orphan_task_says_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A just-starting attempt (no task id yet) gets retry guidance.

    Not the impossible 'pass a task id to choose one' over a table whose id
    cell is blank.
    """
    _patch_surface(monkeypatch, [_full_summary("", "t1", status="running")])
    result = _runner().invoke(ctl_command, ["config", "--max-samples", "3"])
    assert result.exit_code == 1
    assert "hasn't finished registering yet" in result.stderr
    assert "retry in a moment" in result.stderr
    assert "pass a task id" not in result.stderr


def test_config_task_knob_with_only_pre_task_id_logs_says_unaddressable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_surface(monkeypatch, [_full_summary("", "t1", status="completed")])
    result = _runner().invoke(ctl_command, ["config", "--max-samples", "3"])
    assert result.exit_code == 1
    assert "predate task ids" in result.stderr
    assert "pass a task id" not in result.stderr


def test_config_help_scope_tags_derive_from_knob_table() -> None:
    """Every knob's --help entry carries the scope from _KNOB_SCOPE.

    The help tags, the JSON "scope" fields, and the human render labels all
    derive from that one table; this pins the help side (the JSON side is
    pinned by test_compose_config_labels_every_knob_with_scope).
    """
    from inspect_ai._cli.ctl import _KNOB_SCOPE

    out = _runner().invoke(ctl_command, ["config", "--help"]).output
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
    from inspect_ai._cli.ctl import _KNOB_SCOPE
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

    result = _runner().invoke(ctl_command, ["config", "--max-samples", "3"])
    assert result.exit_code == 1
    assert "--max-samples not supported" in result.stderr
    assert "pid 7 is running an older inspect" in result.stderr
    assert "restart the eval" in result.stderr

    # the gate covers dry runs too: a dry-run PATCH on an older server would
    # report a success-shaped view that omits the unknown knobs
    dry = _runner().invoke(ctl_command, ["config", "--max-samples", "3", "--dry-run"])
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
    result = _runner().invoke(
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
    result = _runner().invoke(ctl_command, ["config", "--max-samples", "3", "--json"])
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
    result = _runner().invoke(ctl_command, ["config", "--max-samples", "3", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["applied"] is True


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
    result = _runner().invoke(ctl_command, ["config", "--log-shared", "0"])
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
    result = _runner().invoke(ctl_command, ["process", "release", "--json"])
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
    result = _runner().invoke(ctl_command, ["process", "keep"])
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
    result = _runner().invoke(ctl_command, ["process", "keep", "8"])
    assert result.exit_code == 0, result.output
    assert posted == ["/tmp/8.sock"]


def test_process_list_json(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_surface(
        monkeypatch,
        [_full_summary("aaa111", "t1"), _full_summary("bbb222", "t2", pid=8)],
        servers=[_DiscServer(7), _DiscServer(8)],
    )
    result = _runner().invoke(ctl_command, ["process", "list", "--json"])
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
    runner = _runner()

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


def test_events_json_no_servers_echoes_identifiers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The no-running-evals empty page keeps the identifier echo shape."""
    monkeypatch.setattr("inspect_ai._cli.ctl.list_discovered_servers", lambda: [])
    result = _runner().invoke(
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
    result = _runner().invoke(ctl_command, ["task", "--json", "list"])
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
    runner = _runner()

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
    result = _runner().invoke(
        ctl_command, ["sample", "--active-since", "5.0", "show", "t", "s1"]
    )
    assert result.exit_code != 0
    assert "sample show" in result.stderr and "does not accept" in result.stderr
    assert "sample list --active-since" in result.stderr


def test_events_cursor_that_looks_like_timestamp_errors() -> None:
    result = _runner().invoke(
        ctl_command, ["sample", "events", "t", "s1", "--cursor", "1751900000.5"]
    )
    assert result.exit_code == 1
    assert "did you mean --since-time" in result.stderr


def test_events_garbage_cursor_errors() -> None:
    result = _runner().invoke(
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
    ts = _runner().invoke(
        ctl_command, ["sample", "events", "t", "s1", "--since", "1751900000"]
    )
    assert ts.exit_code == 1
    assert "use --since-time" in ts.stderr

    cur = _runner().invoke(
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
    result = _runner().invoke(ctl_command, ["task", "log-flush", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["target"]["task_id"] == "ccc333"


def test_log_flush_multiple_active_tasks_shows_candidate_table(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_surface(
        monkeypatch,
        [_full_summary("aaa111", "t1"), _full_summary("bbb222", "t2")],
    )
    result = _runner().invoke(ctl_command, ["task", "log-flush"])
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
    result = _runner().invoke(ctl_command, ["task", "log-flush", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["target"]["task_id"] == "aaa111"
    assert payload["applied"] is True and payload["dry_run"] is False
    assert payload["detail"] == {"flushed": 2}


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
    assert "log buffer [task]:       per task (pass a task to view/set)" in out
    assert "shared sync [task]:      per task (pass a task to view/set)" in out


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
    result = _runner().invoke(ctl_command, ["keep", "8"])
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
    result = _runner().invoke(ctl_command, ["sample", "list", "--json"])
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
    result = _runner().invoke(ctl_command, ["sample", "list", "--json"])
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
    result = _runner().invoke(ctl_command, ["sample", "events", "t1", "s1", "--json"])
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
    result = _runner().invoke(ctl_command, ["sample", "list", "aaa111", "--json"])
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
    runner = _runner()

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
    result = _runner().invoke(ctl_command, ["sample", "list", "gpqa", "--json"])
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
