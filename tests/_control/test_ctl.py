"""Unit tests for the `inspect ctl` CLI.

Covers target resolution (id + name matching), the noun-group command
surface (implied `list`, strict verb boundary, hidden aliases), the agent
output contract (envelopes, unconditional task_id, mutation results,
cursor validation), and rendering helpers.
"""

import json
from typing import Any

import click
import pytest
from click.testing import CliRunner

from inspect_ai._cli.ctl import (
    _print_keep_alive_footer,
    _print_samples_table,
    _resolve_target_eval,
    _resolve_target_server,
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

    Each item is either an ``Exception`` to raise (e.g. a ``TimeoutException``)
    or a payload to return from ``response.json()``. Returns a dict whose
    ``"gets"`` entry counts how many requests were attempted.
    """
    counter = {"gets": 0, "posts": 0}
    seq = list(sequence)

    class _Resp:
        def __init__(self, payload: object, status_code: int = 200) -> None:
            self._payload = payload
            self.status_code = status_code

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

        def _next(self, kind: str) -> _Resp:
            counter[kind] += 1
            item = seq.pop(0)
            if isinstance(item, Exception):
                raise item
            return _Resp(item)

        def get(self, path: str, params: object = None) -> _Resp:
            return self._next("gets")

        def post(self, path: str, params: object = None) -> _Resp:
            return self._next("posts")

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


def test_buffer_read_retries_timeout_then_succeeds(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A buffer read (GET) retries a busy eval on timeout, like the other reads."""
    import httpx

    from inspect_ai._cli.ctl import _exec_buffer_config

    counter = _stub_httpx(
        monkeypatch,
        [
            httpx.ReadTimeout("slow"),
            httpx.ReadTimeout("slow"),
            {"log_buffer": 10, "pending": 2, "log_shared": None},
        ],
    )
    config = _exec_buffer_config(
        "/tmp/x.sock", "e1", log_buffer=None, log_shared=None, set_values=False
    )
    assert config == {"log_buffer": 10, "pending": 2, "log_shared": None}
    assert counter["gets"] == 3
    assert counter["posts"] == 0
    assert "retrying" in capsys.readouterr().err


def test_buffer_set_does_not_retry_timeout(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A buffer update (POST) is single-shot — a mutation must not be retried."""
    import httpx

    from inspect_ai._cli.ctl import _exec_buffer_config

    counter = _stub_httpx(monkeypatch, [httpx.ReadTimeout("slow")])
    with pytest.raises(click.exceptions.Exit) as exc_info:
        _exec_buffer_config(
            "/tmp/x.sock", "e1", log_buffer=3, log_shared=None, set_values=True
        )
    assert exc_info.value.exit_code == 1
    assert counter["posts"] == 1  # tried once, no retry
    assert "Failed to update buffer config" in capsys.readouterr().err


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


# --- noun-group surface + agent output contract -----------------------------


class _DiscServer:
    """Discovery entry double (pid / socket_path / started_at)."""

    def __init__(self, pid: int) -> None:
        self.pid = pid
        self.socket_path = f"/tmp/{pid}.sock"
        self.started_at = 100.0


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
) -> None:
    """Stub discovery + the HTTP reads so CLI commands run hermetically."""
    monkeypatch.setattr(
        "inspect_ai._cli.ctl.list_discovered_servers",
        lambda: servers if servers is not None else [_DiscServer(7)],
    )
    monkeypatch.setattr("inspect_ai._cli.ctl._fetch_summaries", lambda s: summaries)
    if samples_by_eval is not None:
        monkeypatch.setattr(
            "inspect_ai._cli.ctl._fetch_samples",
            lambda socket_path, eval_id, active_since=None: (
                123.0,
                samples_by_eval.get(eval_id, []),
            ),
        )


def test_bare_task_noun_implies_list(monkeypatch: pytest.MonkeyPatch) -> None:
    """`ctl task --json` (no verb) runs `list` — with the mirrored option."""
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    result = _runner().invoke(ctl_command, ["task", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
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
    payload = json.loads(result.output)
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
    payload = json.loads(result.output)
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
    payload = json.loads(result.output)
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
    payload = json.loads(result.output)
    assert [(r["task_id"], r["sample_id"]) for r in payload["samples"]] == [
        ("aaa111", "bad"),
        ("bbb222", "retried"),
    ]


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
    payload = json.loads(result.output)
    assert payload["task_id"] == "aaa111"
    assert payload["total_tokens"] == 42  # from the listing row
    assert payload["error"] == {"message": "boom"}  # detail wins on overlap
    assert payload["status"] == "error"
    assert (payload["sample_id"], payload["epoch"]) == ("s1", 1)  # echoed


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


def test_limits_alias_delegates_to_config(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    monkeypatch.setattr(
        "inspect_ai._cli.ctl._exec_limits",
        lambda *a, **k: {
            "max_samples": {"limit": 3, "in_use": 1, "adjustable": True},
            "max_sandboxes": [],
            "adaptive": [],
            "requested": None,
            "warnings": [],
            "dry_run": False,
        },
    )
    monkeypatch.setattr(
        "inspect_ai._cli.ctl._exec_buffer_config",
        lambda *a, **k: {"log_buffer": 10, "pending": 0, "log_shared": None},
    )
    result = _runner().invoke(ctl_command, ["limits", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["knobs"]["max_samples"]["scope"] == "task"
    assert "is now `inspect ctl config`" in result.stderr


def test_process_release_json_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "inspect_ai._cli.ctl.list_discovered_servers", lambda: [_DiscServer(7)]
    )
    monkeypatch.setattr(
        "inspect_ai._cli.ctl._post_to_server",
        lambda socket_path, path: {"ok": True, "keep_alive": False, "changed": True},
    )
    result = _runner().invoke(ctl_command, ["process", "release", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
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
        "inspect_ai._cli.ctl._post_to_server",
        lambda socket_path, path: {"ok": True, "keep_alive": True, "changed": False},
    )
    result = _runner().invoke(ctl_command, ["process", "keep"])
    assert result.exit_code == 0
    assert "already on" in result.output


def test_process_keep_pid_is_positional(monkeypatch: pytest.MonkeyPatch) -> None:
    posted: list[str] = []

    def record(socket_path: Any, path: str) -> dict[str, Any]:
        posted.append(str(socket_path))
        return {"ok": True}

    monkeypatch.setattr(
        "inspect_ai._cli.ctl.list_discovered_servers",
        lambda: [_DiscServer(7), _DiscServer(8)],
    )
    monkeypatch.setattr("inspect_ai._cli.ctl._post_to_server", record)
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
    payload = json.loads(result.output)
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
    payload = json.loads(result.output)
    assert payload["task_id"] == "aaa111"
    assert (payload["sample_id"], payload["epoch"]) == ("s1", 1)


def test_group_option_before_verb_forwards(monkeypatch: pytest.MonkeyPatch) -> None:
    """A mirrored option given at the group level reaches the explicit verb."""
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    result = _runner().invoke(ctl_command, ["task", "--json", "list"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert "as_of" in payload
    assert payload["tasks"][0]["task_id"] == "aaa111"


def test_group_option_forwards_value_and_verb_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    def fake_samples(
        socket_path: Any, eval_id: str, active_since: float | None = None
    ) -> tuple[float, list[dict[str, Any]]]:
        captured["active_since"] = active_since
        return (123.0, [])

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


def test_compose_config_labels_every_knob_with_scope() -> None:
    from inspect_ai._cli.ctl import _compose_config, _DirectiveScope

    scope = _DirectiveScope(
        socket_path="/tmp/7.sock",
        task_id="t1",
        eval_id="e1",
        task="tn",
        header="h",
        siblings=3,
    )
    limits_view = {
        "max_samples": {"limit": 3, "in_use": 1, "adjustable": True},
        "max_sandboxes": [{"type": "docker", "limit": 4, "in_use": 2}],
        "adaptive": [],
        "requested": {"max_samples": 3},
        "warnings": ["w"],
        "dry_run": False,
    }
    buffer_view = {"log_buffer": 10, "pending": 2, "log_shared": None}
    config = _compose_config(
        scope,
        limits_view,
        buffer_view,
        requested_buffer={"log_buffer": 5},
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
        eval_id=None,
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
        None,
        requested_buffer={},
        dry_run=True,
        set_values=True,
        notes=[],
    )
    assert config["target"]["scope"] == "process"
    assert "max_samples" not in config["knobs"]  # process view has no task knob
    assert "log_buffer" not in config["knobs"]
    assert config["applied"] is False and config["dry_run"] is True


def test_log_flush_json_mutation_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    monkeypatch.setattr(
        "inspect_ai._cli.ctl._post_flush", lambda *a, **k: {"flushed": 2}
    )
    result = _runner().invoke(ctl_command, ["task", "log-flush", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["target"]["task_id"] == "aaa111"
    assert payload["applied"] is True and payload["dry_run"] is False
    assert payload["detail"] == {"flushed": 2}
