"""Unit tests for `inspect ctl` target resolution (id + name matching)."""

from typing import Any

import click
import pytest

from inspect_ai._cli.ctl import _print_samples_table, _resolve_target_eval


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
