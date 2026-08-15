"""Unit tests for the `inspect ctl` CLI.

Covers target resolution (id + name matching), the noun-group command
surface (implied `list`, strict verb boundary, hidden aliases), the agent
output contract (envelopes, unconditional task_id, mutation results,
cursor validation), and rendering helpers.
"""

import json
import os
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import anyio
import click
import pytest
from test_helpers.trace import action_record, write_trace_log

from _control.conftest import cli_runner
from inspect_ai._cli.ctl import (
    _KNOB_SCOPE,
    _KNOB_SINCE,
    _SHORT_ID_LEN,
    _ConfigResult,
    _FetchedSummaries,
    _print_errored_samples_footer,
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


def test_tasks_table_shows_refusal_and_retry_columns_only_when_nonzero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Zero is the usual value for both, so a standing pair of 0 columns is clutter.

    Same rule as `errors` / `attempts`: the column earns its width by having
    something to report. The `--json` row always carries both keys.
    """
    _print_human_table([_task_row("aaa111", "t1", refusals=0, http_retries=0)])
    header = capsys.readouterr().out.splitlines()[0]
    assert "refusals" not in header and "http_retries" not in header

    _print_human_table(
        [
            _task_row("aaa111", "t1", refusals=2, http_retries=0),
            _task_row("bbb222", "t2", refusals=0, http_retries=9),
        ]
    )
    lines = capsys.readouterr().out.splitlines()
    assert "refusals" in lines[0] and "http_retries" in lines[0]
    assert "2" in next(ln for ln in lines if ln.startswith("aaa111"))
    assert "9" in next(ln for ln in lines if ln.startswith("bbb222"))


def test_tasks_table_survives_a_server_that_omits_the_counters(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An older server reports neither key; that must read as "nothing to show"."""
    _print_human_table([_task_row("aaa111", "t1", model="openai/gpt-5")])
    header = capsys.readouterr().out.splitlines()[0]
    assert "refusals" not in header and "http_retries" not in header


def test_tasks_table_leaves_an_unreported_count_blank_not_zero(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """In a mixed-version fleet, `0` would assert "none happened" about an unknown.

    Observed live: rows from an older server sat at `0` beside a task that had in
    fact retried many times. Blank is the honest cell, matching how the samples
    table renders an unknown turn count.
    """
    _print_human_table(
        [
            _task_row("aaa111", "t1", http_retries=7),  # this server reports
            _task_row("bbb222", "t2"),  # this one does not
            _task_row("ccc333", "t3", http_retries=0),  # reports, and it is zero
        ]
    )
    lines = capsys.readouterr().out.splitlines()
    header = lines[0]
    assert "http_retries" in header
    # Slice by the header's own column offset. Splitting on whitespace cannot work
    # here: the cell under test is EMPTY on one row, so a split would silently
    # return a neighbouring column's token and the assertion would pass for the
    # wrong reason (the `samples` cell contains spaces too).
    start = header.index("http_retries")
    width = len("http_retries")

    def cell(prefix: str) -> str:
        row = next(ln for ln in lines if ln.startswith(prefix))
        return row[start : start + width].strip()

    assert cell("aaa111") == "7"
    assert cell("bbb222") == "", "an unreported count must not read as zero"
    assert cell("ccc333") == "0"


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


def _activity(a_type: str, started_ago: float, **extra: Any) -> dict[str, Any]:
    import time

    return {
        "type": a_type,
        "count": 1,
        "started_at": time.time() - started_ago,
        "detail": "openai/gpt-5-nano",
        "retries": None,
        "deadline": None,
        "tokens": None,
        "last_progress_at": None,
        **extra,
    }


def test_activity_column_shown_and_rendered_for_generating(
    capsys: pytest.CaptureFixture[str],
) -> None:
    samples = [
        {**_sample(1, "running", {}), "activity": _activity("model", 432)},
        {**_sample(2, "completed", {})},  # no activity → blank cell
    ]
    _print_samples_table(samples)
    lines = capsys.readouterr().out.splitlines()
    assert "activity" in lines[0]
    running_row = next(ln for ln in lines if ln.startswith("1 "))
    # ~432s elapsed (prefix match tolerates the second ticking over mid-test)
    assert "generating 7:1" in running_row
    completed_row = next(ln for ln in lines if ln.startswith("2 "))
    assert "generating" not in completed_row


def test_activity_column_hidden_when_no_activity(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # a running sample with nothing pending (activity null) keeps the
    # common case uncluttered — the column only appears when informative
    samples = [{**_sample(1, "running", {}), "activity": None}]
    _print_samples_table(samples)
    assert "activity" not in capsys.readouterr().out.splitlines()[0]


def test_activity_cell_renders_tool_and_multi_tool() -> None:
    import time

    from inspect_ai._cli.ctl import _format_activity

    # sample `now` after building so elapsed rounds to the intended value
    bash = _activity("tool", 41, detail="bash")
    tools = _activity("tool", 70, detail="bash", count=2)
    now = time.time()
    assert _format_activity(bash, now) == "bash 0:41"
    assert _format_activity(tools, now) == "2 tools 1:10"


def test_activity_cell_renders_retries_and_tokens() -> None:
    import time

    from inspect_ai._cli.ctl import _format_activity

    # sample `now` after building so elapsed rounds to the intended value
    retried = _activity("model", 151, retries=2)
    one_retry = _activity("model", 151, retries=1)
    streamed = _activity("model", 151, tokens=1234)
    now = time.time()
    assert _format_activity(retried, now) == "generating 2:31 (2 retries)"
    assert _format_activity(one_retry, now) == "generating 2:31 (1 retry)"
    # layer-2 streamed tokens render when a newer server reports them
    assert _format_activity(streamed, now) == "generating 2:31 · 1.2k tok"


def test_activity_cell_renders_retry_wait() -> None:
    import time

    from inspect_ai._cli.ctl import _format_activity

    now = time.time()
    wait = _activity("retry_wait", 10, deadline=now + 45)
    assert _format_activity(wait, now) == "retrying in 0:45"
    # `count` is the attempt that just failed — rendered as "after attempt N"
    # so it can't be misread as the upcoming attempt
    later_attempt = _activity("retry_wait", 10, deadline=now + 45, count=3)
    assert _format_activity(later_attempt, now) == "retrying in 0:45 (after attempt 3)"
    # deadline passed (next attempt imminent) → no misleading countdown
    overdue = _activity("retry_wait", 60, deadline=now - 5)
    assert _format_activity(overdue, now) == "retrying"


def test_activity_cell_degrades_for_unknown_type_and_null() -> None:
    import time

    from inspect_ai._cli.ctl import _format_activity

    now = time.time()
    assert _format_activity(None, now) == ""
    # a future activity type from a newer server shows its name, not blank
    assert _format_activity(_activity("compacting", 5), now).startswith("compacting")


def test_sample_detail_includes_activity(
    capsys: pytest.CaptureFixture[str],
) -> None:
    import time

    from inspect_ai._cli.ctl import _print_sample_detail

    detail = {
        "sample_id": "recABC",
        "epoch": 1,
        "status": "running",
        "activity": {
            "type": "model",
            "count": 1,
            "started_at": time.time() - 151,
            "detail": "openai/gpt-5-nano",
            "retries": None,
            "deadline": None,
            "tokens": None,
            "last_progress_at": None,
        },
        "error": None,
        "error_retries": [],
    }
    _print_sample_detail(detail, show_traceback=False)
    header = capsys.readouterr().out.splitlines()[0]
    # ~151s elapsed (prefix match tolerates the second ticking over mid-test)
    assert "generating 2:3" in header


def test_event_summary_renders_pending_model_and_tool() -> None:
    import time

    from inspect_ai._cli.ctl import _event_summary

    started = time.time() - 151
    pending_model = {
        "event": "model",
        "model": "openai/gpt-5-nano",
        "pending": True,
        "timestamp": started,
        # the pending event's placeholder output must not leak into the
        # summary as a finished-looking row
        "tokens": 0,
        "stop_reason": "stop",
    }
    # prefix matches tolerate the second ticking over mid-test (~151s elapsed)
    assert _event_summary(pending_model).startswith(
        "openai/gpt-5-nano · generating 2:3"
    )

    pending_tool = {
        "event": "tool",
        "function": "bash",
        "arguments": "ls /data",
        "pending": True,
        "timestamp": started,
    }
    assert _event_summary(pending_tool).startswith("bash(ls /data) · running 2:3")

    completed_model = {
        "event": "model",
        "model": "openai/gpt-5-nano",
        "pending": None,
        "timestamp": started,
        "tokens": 1840,
        "stop_reason": "stop",
    }
    assert _event_summary(completed_model) == "openai/gpt-5-nano · 1840 tok · stop"


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


def test_sample_detail_withheld_error_renders_marker(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A withheld error renders as an explicit marker, not a blank line.

    A metadata-only detail (no --content) carries each error as an empty dict.
    """
    from inspect_ai._cli.ctl import _print_sample_detail

    detail = {
        "sample_id": 1,
        "epoch": 1,
        "status": "error",
        "retries": 1,
        "error": {},
        "error_retries": [{}],
        "scores": {},
    }
    _print_sample_detail(detail, show_traceback=False)
    out = capsys.readouterr().out
    assert "final error" in out and "prior attempts" in out
    assert out.count("withheld — pass --content") == 2


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
    _print_events(page, content=True, full=False)
    out = capsys.readouterr().out
    assert "event" in out.splitlines()[0]  # table header
    # per-type summaries
    assert "openai/gpt" in out and "bash" in out and "boom" in out
    assert "my-solver" in out and "phase 1 complete" in out
    # footer: count, "more" (not done), and the resume cursor
    assert "4 events" in out
    assert "more" in out
    assert "next: CURSORX" in out
    # a content read carries no metadata-only pointer
    assert "metadata only" not in out


def test_print_events_metadata_rows_and_footer_hint(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Metadata-only rows render structural fields and error presence.

    The footer points at the --content opt-in.
    """
    from inspect_ai._cli.ctl import _print_events

    page = {
        "events": [
            {
                "event": "model",
                "timestamp": 1000.0,
                "model": "openai/gpt",
                "tokens": 42,
                "stop_reason": "stop",
                "has_error": False,
            },
            {
                "event": "tool",
                "timestamp": 1001.0,
                "function": "bash",
                "has_error": True,
            },
        ],
        "next": "CURSORX",
        "done": False,
    }
    _print_events(page, content=False, full=False)
    out = capsys.readouterr().out
    assert "openai/gpt" in out and "42 tok" in out
    assert "bash() → error" in out
    assert "metadata only (pass --content for text)" in out


def test_print_events_footer_response_keyed_on_old_server(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """No "metadata only" hint under content a pre-v6 server returned anyway.

    A pre-v6 server ignores the unknown ``content`` query param and returns
    the old content-bearing projection; the footer keys on the response, so
    it must not caption the text printed right above it as withheld.
    """
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
                "error": None,
            }
        ],
        "next": None,
        "done": True,
    }
    _print_events(page, content=False, full=False)
    out = capsys.readouterr().out
    assert "hello" in out
    assert "metadata only" not in out


def test_print_events_empty_and_done(capsys: pytest.CaptureFixture[str]) -> None:
    from inspect_ai._cli.ctl import _print_events

    _print_events({"events": [], "next": "X", "done": True}, content=True, full=False)
    out = capsys.readouterr().out
    assert "(no events)" in out
    assert "done" in out
    assert "next:" not in out  # a done stream offers no resume cursor


def test_print_events_full_pretty_prints_raw(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Full mode emits raw JSON: nested fields the summary table can't render."""
    from inspect_ai._cli.ctl import _print_events

    page = {
        "events": [
            {
                "event": "model",
                # raw model_dump timestamps are ISO strings, not unix floats
                "timestamp": "2026-07-14T19:10:05+00:00",
                "model": "openai/gpt",
                "output": {"usage": {"total_tokens": 42}, "completion": "hello"},
            }
        ],
        "next": "CURSORX",
        "done": False,
    }
    _print_events(page, content=False, full=True)
    out = capsys.readouterr().out
    # nested raw fields survive (the compact table would have dropped them)
    assert '"total_tokens": 42' in out
    assert '"completion": "hello"' in out
    assert "2026-07-14T19:10:05+00:00" in out
    # the cursor footer still supports polling loops
    assert "1 event" in out
    assert "more" in out
    assert "next: CURSORX" in out


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


def test_errored_samples_footer_points_at_triage_command(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # sums latest-attempt errors across rows (rows without any count as 0)
    summaries: list[dict[str, Any]] = [
        {"samples": {"errored": 2}},
        {"samples": {"errored": 1}},
        {"samples": {}},
    ]
    _print_errored_samples_footer(summaries)
    out = capsys.readouterr().out
    assert "3 samples errored" in out
    assert "inspect ctl sample errors" in out


def test_errored_samples_footer_singular(
    capsys: pytest.CaptureFixture[str],
) -> None:
    _print_errored_samples_footer([{"samples": {"errored": 1}}])
    assert "1 sample errored" in capsys.readouterr().out


def test_errored_samples_footer_absent_without_errors(
    capsys: pytest.CaptureFixture[str],
) -> None:
    # An older server may omit `samples` entirely — treated as no errors.
    _print_errored_samples_footer([{"samples": {"errored": 0}}, {}])
    assert capsys.readouterr().out == ""


def test_footer_reports_paused_tasks(capsys: pytest.CaptureFixture[str]) -> None:
    summaries: list[dict[str, Any]] = [
        {"keep_alive": True, "paused": "task", "quiesced": True},
        {"keep_alive": True, "paused": None},
    ]
    _print_keep_alive_footer(summaries)
    out = capsys.readouterr().out
    assert "paused: 1/2 tasks (1 quiesced)" in out
    # held only by the task latch → advertise only the command that resumes it
    assert "inspect ctl task resume" in out
    assert "inspect ctl model resume" not in out
    assert "inspect ctl process resume" not in out
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


def test_footer_flags_task_paused_with_exit_when_done(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A task-level pause with keep-alive off also never reaches its exit."""
    summaries: list[dict[str, Any]] = [
        {"keep_alive": False, "paused": "task", "quiesced": False}
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


def test_footer_reports_model_paused_sources(
    capsys: pytest.CaptureFixture[str],
) -> None:
    summaries: list[dict[str, Any]] = [
        {
            "keep_alive": True,
            "paused": ["model"],
            "quiesced": False,
            "paused_models": ["mockllm/model"],
        },
        {"keep_alive": True, "paused": None, "paused_models": ["mockllm/model"]},
    ]
    _print_keep_alive_footer(summaries)
    out = capsys.readouterr().out
    assert "paused: 1/2 tasks" in out
    # held only by the model latch → advertise only the command that resumes it
    assert "inspect ctl model resume" in out
    assert "inspect ctl task resume" not in out
    assert "inspect ctl process resume" not in out
    assert "paused models: mockllm/model" in out


def test_footer_reports_latched_model_with_no_paused_rows(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A latched model whose tasks are all still queued has no paused row.

    An unstarted task has no summary, so the per-row `paused` sources can't
    surface the latch — the process-level `paused_models` stamp is what
    keeps it from holding work invisibly.
    """
    summaries: list[dict[str, Any]] = [
        {"keep_alive": True, "paused": None, "paused_models": ["mockllm/model"]}
    ]
    _print_keep_alive_footer(summaries)
    out = capsys.readouterr().out
    assert "paused models: mockllm/model" in out
    assert "inspect ctl model resume" in out


def test_footer_reports_each_holding_latch_when_mixed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Two tasks held by different latches → advertise both resume commands.

    The footer's resume hints are the union of the latches actually holding a
    paused task, in fixed task → model → process order.
    """
    summaries: list[dict[str, Any]] = [
        {"keep_alive": True, "paused": ["task"]},
        {"keep_alive": True, "paused": ["model"], "paused_models": ["mockllm/model"]},
    ]
    _print_keep_alive_footer(summaries)
    out = capsys.readouterr().out
    assert "paused: 2/2 tasks" in out
    assert "inspect ctl task resume" in out
    assert "inspect ctl model resume" in out
    assert "inspect ctl process resume" not in out


def test_format_paused_renders_source_lists() -> None:
    from inspect_ai._cli.ctl import _format_paused

    assert _format_paused({"paused": ["task", "model"]}) == "task+model"
    assert _format_paused({"paused": ["model"], "quiesced": True}) == "model (quiesced)"
    # legacy servers (<= 0.3.250) send a string, with "both" for task+process
    assert _format_paused({"paused": "both"}) == "task+process"
    assert _format_paused({"paused": "task"}) == "task"
    assert _format_paused({"paused": None}) == ""


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
    monkeypatch: pytest.MonkeyPatch,
    sequence: list[object] | dict[str, list[object]],
) -> dict[str, int]:
    """Replace httpx in ctl so each ``client.get`` consumes one ``sequence`` item.

    Each item is either an ``Exception`` to raise (e.g. a ``TimeoutException``),
    a payload to return from ``response.json()``, or a ``(status_code, payload)``
    tuple for a non-200 response. Returns a dict whose ``"gets"`` entry counts
    how many requests were attempted.

    Both the sync and async clients are stubbed: reads go out over the async
    client, while a non-idempotent mutation still takes the sync path.

    Pass a **dict keyed by socket path** whenever more than one target is read
    concurrently — each target then draws from its own queue, so the test does
    not depend on the order the task group happens to start its reads in
    (asyncio schedules them FIFO; trio deliberately randomizes). A bare list is
    one shared queue, fine for a single target's successive attempts.
    """
    counter = {"gets": 0, "posts": 0, "patches": 0}
    shared = None if isinstance(sequence, dict) else list(sequence)
    by_socket = (
        {socket: list(items) for socket, items in sequence.items()}
        if isinstance(sequence, dict)
        else {}
    )

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

    count_key = {"get": "gets", "post": "posts", "patch": "patches"}

    class _Transport:
        """Stands in for httpx's transport, carrying the uds through to _next."""

        def __init__(self, uds: str | None = None, **kwargs: object) -> None:
            self.uds = uds

    def _next(kind: str, uds: str | None) -> _Resp:
        counter[kind] += 1
        item = (shared if shared is not None else by_socket[str(uds)]).pop(0)
        if isinstance(item, Exception):
            raise item
        if isinstance(item, tuple):
            status, payload = item
            return _Resp(payload, status)
        return _Resp(item)

    class _Client:
        def __init__(self, *args: object, **kwargs: object) -> None:
            self.uds = getattr(kwargs.get("transport"), "uds", None)

        def __enter__(self) -> "_Client":
            return self

        def __exit__(self, *args: object) -> None:
            pass

        def get(self, path: str, params: object = None) -> _Resp:
            return _next("gets", self.uds)

        def post(self, path: str, params: object = None) -> _Resp:
            return _next("posts", self.uds)

        def patch(self, path: str, params: object = None) -> _Resp:
            return _next("patches", self.uds)

        def request(self, method: str, path: str, params: object = None) -> _Resp:
            return _next(count_key[method], self.uds)

    class _AsyncClient:
        # only `request` — the async path is reads and idempotent mutations,
        # which all go through it; the one-shot mutation takes the sync client
        def __init__(self, *args: object, **kwargs: object) -> None:
            self.uds = getattr(kwargs.get("transport"), "uds", None)

        async def __aenter__(self) -> "_AsyncClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            pass

        async def request(self, method: str, path: str, params: object = None) -> _Resp:
            return _next(count_key[method], self.uds)

    monkeypatch.setattr("inspect_ai._cli.ctl.httpx.Client", _Client)
    monkeypatch.setattr("inspect_ai._cli.ctl.httpx.HTTPTransport", _Transport)
    monkeypatch.setattr("inspect_ai._cli.ctl.httpx.AsyncClient", _AsyncClient)
    monkeypatch.setattr("inspect_ai._cli.ctl.httpx.AsyncHTTPTransport", _Transport)
    return counter


async def _await_sibling(event: anyio.Event, who: str) -> None:
    """Park until a sibling read completes, failing loudly if none ever does.

    The barrier the concurrency tests are built on: it can only be crossed
    with more than one read in flight, so a fan-out that went back to reading
    one target at a time trips the deadline with a message that says so,
    rather than hanging the suite or surfacing a bare TimeoutError. Two
    seconds is generous — a concurrent fan-out crosses it in one scheduling
    pass, and nothing here waits on real I/O.
    """
    try:
        with anyio.fail_after(2):
            await event.wait()
    except TimeoutError:
        raise AssertionError(
            f"{who} was still the only read in flight after 2s — the fan-out "
            "is issuing its reads one at a time"
        ) from None


def _disc(pid: int) -> "DiscoveredControlServer":
    from pathlib import Path

    return DiscoveredControlServer(
        pid=pid, socket_path=Path(f"/tmp/{pid}.sock"), started_at=0.0
    )


async def test_get_with_retry_retries_timeout_then_succeeds(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A read that times out twice, then succeeds, returns the payload.

    Each timeout prints a status to stderr; the eventual success is returned.
    """
    import httpx

    from inspect_ai._cli.ctl import _get_with_retry_async

    counter = _stub_httpx(
        monkeypatch,
        [httpx.ReadTimeout("slow"), httpx.ReadTimeout("slow"), [{"task_id": "a"}]],
    )
    result = await _get_with_retry_async("/tmp/x.sock", "/tasks", what="Reading tasks")
    assert result == [{"task_id": "a"}]
    assert counter["gets"] == 3
    err = capsys.readouterr().err
    assert err.count("retrying") == 2
    assert "attempt 1/8" in err and "attempt 2/8" in err


async def test_get_with_retry_exhausts_and_exits(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Eight consecutive timeouts exhaust the retries → error + failure status."""
    import httpx

    from inspect_ai._cli.ctl import _REQUEST_ATTEMPTS, _get_with_retry_async

    counter = _stub_httpx(monkeypatch, [httpx.ReadTimeout("slow")] * _REQUEST_ATTEMPTS)
    with pytest.raises(click.exceptions.Exit) as exc_info:
        await _get_with_retry_async(
            "/tmp/x.sock", "/tasks", what="Reading tasks", pid=7
        )
    assert exc_info.value.exit_code == 1
    assert counter["gets"] == _REQUEST_ATTEMPTS
    err = capsys.readouterr().err
    assert f"gave up after {_REQUEST_ATTEMPTS} attempts" in err
    # the terminal busy narration teaches the escalation path, scoped to the
    # target process when the caller knows it
    assert "inspect ctl process anomalies 7" in err


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


async def test_get_with_retry_busy_raises_without_terminal_echo(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A degradable read raises _ServerBusy on exhaustion — no 'gave up' echo.

    The raising caller owns the terminal narration (its skip/omit message);
    a helper-printed 'gave up … busy; try again shortly' right before it
    would double-narrate. Only the shared per-attempt retry lines print.
    """
    import httpx

    from inspect_ai._cli.ctl import _get_with_retry_async, _ServerBusy

    counter = _stub_httpx(monkeypatch, [httpx.ReadTimeout("slow")] * 2)
    with pytest.raises(_ServerBusy):
        await _get_with_retry_async(
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
        {
            "/tmp/7.sock": [httpx.ReadTimeout("slow")] * _DEGRADED_READ_ATTEMPTS,
            "/tmp/8.sock": [[{"task_id": "live"}]],
        },
    )
    fetched = _fetch_summaries([_disc(7), _disc(8)], raise_on_busy=True)
    assert [s["task_id"] for s in fetched.summaries] == ["live"]
    assert fetched.busy_pids == [7]
    err = capsys.readouterr().err
    assert "Skipping pid 7" in err
    assert "try again shortly" in err
    # the skip note teaches the escalation that works against a busy process
    assert "inspect ctl process anomalies 7" in err


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


def test_fetch_summaries_prefix_query_contacts_every_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A prefix (non-exact) query never stops early — ambiguity needs all servers.

    It reads them one at a time all the same: any ``stop_on_task_id`` takes the
    serial branch, since whether a query is an exact id is only knowable from
    the rows. That costs a scoped read the concurrency an unscoped one gets.
    """
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
        content=False,
        full=False,
        since_time=None,
        until=None,
    )
    assert page == {"events": [], "next": None, "done": True}
    assert counter["gets"] == 2
    assert "retrying" in capsys.readouterr().err


async def test_get_with_retry_does_not_retry_connection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-timeout transport error (server gone) is not retried."""
    import httpx

    from inspect_ai._cli.ctl import _get_with_retry_async, _ServerUnreachable

    counter = _stub_httpx(monkeypatch, [httpx.ConnectError("refused")])
    with pytest.raises(_ServerUnreachable):
        await _get_with_retry_async("/tmp/x.sock", "/tasks", what="Reading tasks")
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
        {
            "/tmp/7.sock": [httpx.ConnectError("refused")],
            "/tmp/8.sock": [[{"task_id": "live"}]],
        },
    )
    summaries = _fetch_summaries([_disc(7), _disc(8)]).summaries
    assert [s["task_id"] for s in summaries] == ["live"]
    assert summaries[0]["pid"] == 8
    assert summaries[0]["socket_path"] == "/tmp/8.sock"
    # the skipped server is surfaced, not swallowed
    err = capsys.readouterr().err
    assert "Skipping pid 7" in err


def test_fetch_summaries_unreachable_server_does_not_cancel_in_flight_siblings(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """One read failing mid-fan-out leaves its suspended siblings alone.

    The reason each read captures its own `_ServerUnreachable` instead of
    raising: raised, it would reach the task group and cancel every sibling
    still awaiting a response. Here pid 8's read is parked when pid 7's fails,
    so it is genuinely in the cancellation window — the schedule the
    warn-and-skip tests above never reach, because their stubs finish before a
    sibling starts.
    """
    import httpx

    from inspect_ai._cli.ctl import _fetch_summaries, _ServerUnreachable

    state: dict[str, Any] = {}

    async def fake_get(socket_path: Any, path: str, **kwargs: Any) -> Any:
        if not state:
            state["released"] = anyio.Event()
        pid = int(Path(str(socket_path)).stem)
        if pid == 7:
            raise _ServerUnreachable() from httpx.ConnectError("refused")
        if pid == 8:
            await _await_sibling(state["released"], "the read for pid 8")
            return [{"task_id": "parked"}]
        state["released"].set()
        return [{"task_id": "late"}]

    monkeypatch.setattr("inspect_ai._cli.ctl._get_with_retry_async", fake_get)
    summaries = _fetch_summaries([_disc(7), _disc(8), _disc(9)]).summaries
    assert [s["task_id"] for s in summaries] == ["parked", "late"]
    assert "Skipping pid 7" in capsys.readouterr().err


def test_fetch_summaries_reads_servers_concurrently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The unscoped fan-out issues its per-server reads together.

    Each fake read parks until the *next* server's read has completed, so the
    fetch only returns if they are all in flight at once, and they complete in
    the reverse of discovery order — which the rows must not inherit.
    """
    from inspect_ai._cli.ctl import _fetch_summaries

    pids = [7, 8, 9]
    state: dict[str, Any] = {}

    async def fake_get(socket_path: Any, path: str, **kwargs: Any) -> Any:
        if not state:
            # created up front, by whichever read runs first: a read parks on
            # its successor's event, which must therefore already exist
            state["done"] = [anyio.Event() for _ in pids]
        index = pids.index(int(Path(str(socket_path)).stem))
        if index + 1 < len(pids):
            await _await_sibling(
                state["done"][index + 1], f"the read for pid {pids[index]}"
            )
        state["done"][index].set()
        return [{"task_id": f"task{pids[index]}"}]

    monkeypatch.setattr("inspect_ai._cli.ctl._get_with_retry_async", fake_get)
    summaries = _fetch_summaries([_disc(pid) for pid in pids]).summaries
    assert [s["task_id"] for s in summaries] == ["task7", "task8", "task9"]
    assert [s["pid"] for s in summaries] == pids


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


def test_fetch_summaries_all_busy_narrates_once_per_invocation(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Every process wedged narrates per attempt and fails once — not per process.

    Both halves of the busy narration are per-invocation, because the reads
    are concurrent: they stall in lockstep and reach their deadline together,
    so per-target narration would answer a wedged eval set with a retry line
    per process per attempt and then a "gave up" block per process.
    """
    import httpx

    from inspect_ai._cli.ctl import _REQUEST_ATTEMPTS, _fetch_summaries

    _stub_httpx(
        monkeypatch,
        {
            f"/tmp/{pid}.sock": [httpx.ReadTimeout("slow")] * _REQUEST_ATTEMPTS
            for pid in (7, 8, 9)
        },
    )
    with pytest.raises(click.exceptions.Exit):
        _fetch_summaries([_disc(7), _disc(8), _disc(9)])
    err = capsys.readouterr().err
    assert err.count("the eval may be busy") == _REQUEST_ATTEMPTS
    assert "Reading tasks from 3 processes: no response" in err
    assert err.count("gave up") == 1
    # deterministic: the first busy server in discovery order, not whichever
    # task the scheduler happened to finish first
    assert "Reading tasks from pid 7: gave up" in err
    assert err.count("inspect ctl process anomalies") == 1
    assert "inspect ctl process anomalies 7" in err


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
        async def fake_fetch_samples(
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

        monkeypatch.setattr(
            "inspect_ai._cli.ctl._fetch_samples_async", fake_fetch_samples
        )


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


def test_task_list_human_footer_flags_errored_samples(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary = _full_summary("aaa111", "t1")
    summary["samples"] = {"total": 4, "completed": 4, "errored": 2}
    _patch_surface(monkeypatch, [summary])
    result = cli_runner().invoke(ctl_command, ["task", "list"])
    assert result.exit_code == 0, result.output
    assert "2 samples errored — see `inspect ctl sample errors`" in result.stdout


def test_task_list_json_carries_no_footer_hints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Errored rows must not grow hints in ``--json`` (the agent contract).

    The whole of stdout must parse as the envelope — a footer line
    anywhere would break that — and the counts the footer would restate
    are already in the rows.
    """
    summary = _full_summary("aaa111", "t1")
    summary["samples"] = {"total": 4, "completed": 4, "errored": 2}
    _patch_surface(monkeypatch, [summary])
    result = cli_runner().invoke(ctl_command, ["task", "list", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["tasks"][0]["samples"]["errored"] == 2


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

    async def fake_samples(
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

    monkeypatch.setattr("inspect_ai._cli.ctl._fetch_samples_async", fake_samples)
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

    async def fake_samples(
        socket_path: Any,
        eval_id: str,
        active_since: float | None = None,
        *,
        sample_filter: str | None = None,
        **kwargs: Any,
    ) -> _SamplesPage:
        seen["sample_filter"] = sample_filter
        return _SamplesPage(as_of=123.0, samples=[_sample_row("s1")])

    monkeypatch.setattr("inspect_ai._cli.ctl._fetch_samples_async", fake_samples)
    result = cli_runner().invoke(ctl_command, ["sample", "list", "--json"])
    assert result.exit_code == 0, result.output
    assert seen["sample_filter"] is None


def test_fetch_samples_sends_filter_param(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The wire param is `filter=errors`, and only when requested."""
    from inspect_ai._cli.ctl import _fetch_samples

    seen: dict[str, Any] = {}

    async def fake_get(
        socket_path: Any, path: str, *, params: Any = None, **kwargs: Any
    ) -> Any:
        seen["params"] = params
        return {"as_of": 1.0, "samples": []}

    monkeypatch.setattr("inspect_ai._cli.ctl._get_with_retry_async", fake_get)
    _fetch_samples("/tmp/x.sock", "e1", sample_filter="errors")
    assert seen["params"] == {"filter": "errors"}
    _fetch_samples("/tmp/x.sock", "e1")
    assert seen["params"] == {}


def _capture_fetch_kwargs(
    monkeypatch: pytest.MonkeyPatch,
    page: _SamplesPage | None = None,
) -> list[dict[str, Any]]:
    """Stub the samples read, recording each call's cap/filter kwargs."""
    calls: list[dict[str, Any]] = []
    result = page if page is not None else _SamplesPage(as_of=123.0, samples=[])

    async def fake_samples(
        socket_path: Any,
        eval_id: str,
        active_since: float | None = None,
        **kwargs: Any,
    ) -> _SamplesPage:
        calls.append(dict(kwargs))
        return result

    monkeypatch.setattr("inspect_ai._cli.ctl._fetch_samples_async", fake_samples)
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


def test_sample_list_attempt_budget_splits_scoped_from_fan_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A scoped read rides the full budget; the fan-out takes the degraded one.

    A scoped read fails the command when its eval stays busy, so it's worth
    waiting out; an unscoped one warn-and-skips, where one wedged eval must
    not hold up the rest.
    """
    from inspect_ai._cli.ctl import _REQUEST_ATTEMPTS

    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    calls = _capture_fetch_kwargs(monkeypatch)

    cli_runner().invoke(ctl_command, ["sample", "list", "--json"])
    assert calls[-1]["attempts"] is None  # the degradable default

    cli_runner().invoke(ctl_command, ["sample", "list", "aaa111", "--json"])
    assert calls[-1]["attempts"] == _REQUEST_ATTEMPTS


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

    async def fake_samples(
        socket_path: Any,
        eval_id: str,
        active_since: float | None = None,
        **kwargs: Any,
    ) -> _SamplesPage:
        return pages[eval_id]

    monkeypatch.setattr("inspect_ai._cli.ctl._fetch_samples_async", fake_samples)
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


def test_sample_list_long_idle_points_at_process_anomalies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A running sample idle in the tens of minutes teaches the escalation.

    The idle column shows the stall but not why (a single in-flight action
    emits no transcript event until it returns); the footer points at the
    trace read that shows the why, naming the hosting pid.
    """
    import time

    _patch_surface(
        monkeypatch,
        [_full_summary("aaa111", "t1")],
        samples_by_eval={
            "eval_aaa111": [
                _sample_row(
                    "s1", status="running", last_activity_at=time.time() - 27 * 60
                )
            ]
        },
    )
    result = cli_runner().invoke(ctl_command, ["sample", "list"])
    assert result.exit_code == 0, result.output
    assert "idle 27:0" in result.output
    assert "`inspect ctl process anomalies 7`" in result.output


def test_sample_list_short_idle_no_pointer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An idle below the threshold is normal operation — no escalation noise."""
    import time

    _patch_surface(
        monkeypatch,
        [_full_summary("aaa111", "t1")],
        samples_by_eval={
            "eval_aaa111": [
                _sample_row("s1", status="running", last_activity_at=time.time() - 120)
            ]
        },
    )
    result = cli_runner().invoke(ctl_command, ["sample", "list"])
    assert result.exit_code == 0, result.output
    assert "process anomalies" not in result.output


def test_sample_list_idle_pointer_omitted_on_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The escalation hint is human-only — no prose inside the envelope."""
    import time

    _patch_surface(
        monkeypatch,
        [_full_summary("aaa111", "t1")],
        samples_by_eval={
            "eval_aaa111": [
                _sample_row(
                    "s1", status="running", last_activity_at=time.time() - 27 * 60
                )
            ]
        },
    )
    result = cli_runner().invoke(ctl_command, ["sample", "list", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert [r["sample_id"] for r in payload["samples"]] == ["s1"]
    assert "process anomalies" not in result.stdout


def test_sample_list_idle_pointer_spans_processes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stalls across several processes suggest the bare verb, which reads them all."""
    import time

    stale = time.time() - 30 * 60
    _patch_surface(
        monkeypatch,
        [
            _full_summary("aaa111", "t1", pid=7),
            _full_summary("bbb222", "t2", pid=9),
        ],
        samples_by_eval={
            "eval_aaa111": [
                _sample_row("s1", status="running", last_activity_at=stale)
            ],
            "eval_bbb222": [
                _sample_row("s2", status="running", last_activity_at=stale)
            ],
        },
    )
    result = cli_runner().invoke(ctl_command, ["sample", "list"])
    assert result.exit_code == 0, result.output
    assert (
        "`inspect ctl process anomalies` shows each running process's" in result.output
    )


def test_sample_list_idle_pointer_duplicate_task_id_degrades(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A task_id read from several processes degrades to the bare verb.

    The duplicate-id corner: an old kept-alive attempt shares its task_id
    with the newer process retrying it, and rows carry only the task_id —
    the footer must suggest the verb that reads every process rather than
    risk naming the attempt that has nothing in flight.
    """
    import time

    stale = time.time() - 30 * 60
    newer = _full_summary("aaa111", "t1", pid=9)
    newer["eval_id"] = "eval_new"
    older = _full_summary("aaa111", "t1", pid=7)
    older["eval_id"] = "eval_old"
    _patch_surface(
        monkeypatch,
        [newer, older],  # discovery is newest-first
        samples_by_eval={
            "eval_new": [_sample_row("s1", status="running", last_activity_at=stale)],
            "eval_old": [
                _sample_row("s1", status="error", error="boom", last_activity_at=stale)
            ],
        },
    )
    result = cli_runner().invoke(ctl_command, ["sample", "list"])
    assert result.exit_code == 0, result.output
    assert (
        "`inspect ctl process anomalies` shows each running process's" in result.output
    )


def test_sample_list_scoped_busy_points_at_process_anomalies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The scoped busy failure names the verb that works against a busy pid.

    Stderr only: the --json envelope message stays hint-free (agents branch
    on `kind` and learn the verb from --help).
    """
    from inspect_ai._cli.ctl import _ServerBusy

    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    _patch_samples_unreachable_for(
        monkeypatch,
        "eval_aaa111",
        exc=_ServerBusy("no response after 8 attempts — the eval's event loop is busy"),
    )
    result = cli_runner().invoke(ctl_command, ["sample", "list", "aaa111"])
    assert result.exit_code == 1
    assert "inspect ctl process anomalies 7" in result.stderr

    result = cli_runner().invoke(ctl_command, ["sample", "list", "aaa111", "--json"])
    assert result.exit_code == 1
    error = _error_envelope(result)
    assert "anomalies" not in error["message"]
    assert "inspect ctl process anomalies 7" in result.stderr


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
    """Stub the samples read so one eval's read fails.

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

    async def fake_samples(
        socket_path: Any,
        eval_id: str,
        active_since: float | None = None,
        **kwargs: Any,
    ) -> _SamplesPage:
        if eval_id == gone_eval_id:
            raise failure
        return _SamplesPage(as_of=123.0, samples=[_sample_row("s2")])

    monkeypatch.setattr("inspect_ai._cli.ctl._fetch_samples_async", fake_samples)


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


def test_sample_errors_footer_points_at_content_opt_in(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The human errors view notes withheld messages (rows with `error: None`)."""
    _patch_surface(
        monkeypatch,
        [_full_summary("aaa111", "t1")],
        samples_by_eval={
            "eval_aaa111": [_sample_row("bad", status="error", retries=1, error=None)]
        },
    )
    result = cli_runner().invoke(ctl_command, ["sample", "errors"])
    assert result.exit_code == 0, result.output
    assert "error messages withheld — pass --content to include them" in result.output


def test_sample_errors_footer_response_keyed_on_old_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No "withheld" footer under error text a pre-v6 server returned anyway.

    The stubbed read ignores ``content`` and returns the row's error message
    — exactly what a pre-v6 server does with the unknown query param — so
    the footer must not caption the message printed right above it.
    """
    _patch_surface(
        monkeypatch,
        [_full_summary("aaa111", "t1")],
        samples_by_eval={
            "eval_aaa111": [_sample_row("bad", status="error", error="boom")]
        },
    )
    result = cli_runner().invoke(ctl_command, ["sample", "errors"])
    assert result.exit_code == 0, result.output
    assert "boom" in result.output
    assert "withheld" not in result.output


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
    adds the "try again shortly" + anomalies-escalation hint — no earlier
    skip note has taught it on this path) — costs only the summary fields,
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
    assert ("inspect ctl process anomalies 7" in result.stderr) == busy
    payload = json.loads(result.stdout)
    assert payload["error"] == {"message": "boom"}
    assert "message_count" not in payload


def test_sample_show_busy_detail_read_points_at_pid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The detail read's retry exhaustion scopes the escalation to the pid.

    The resolved target names the hosting process, so the pointer suggests
    reading that process's trace rather than scanning every running one.
    """
    import httpx

    from inspect_ai._cli.ctl import _REQUEST_ATTEMPTS

    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    _stub_httpx(monkeypatch, [httpx.ReadTimeout("slow")] * _REQUEST_ATTEMPTS)
    result = cli_runner().invoke(ctl_command, ["sample", "show", "aaa111", "s1"])
    assert result.exit_code == 1
    assert "gave up" in result.stderr
    assert "inspect ctl process anomalies 7" in result.stderr


def test_config_busy_read_points_at_pid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A directive's retry exhaustion scopes the escalation to the resolved pid.

    The `_DirectiveScope` commands (config here) resolve one target process,
    so the pointer names it rather than suggesting a scan of every process.
    """
    import httpx

    from inspect_ai._cli.ctl import _REQUEST_ATTEMPTS

    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    _stub_httpx(monkeypatch, [httpx.ReadTimeout("slow")] * _REQUEST_ATTEMPTS)
    result = cli_runner().invoke(ctl_command, ["config"])
    assert result.exit_code == 1
    assert "gave up" in result.stderr
    assert "inspect ctl process anomalies 7" in result.stderr


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


def test_samples_alias_accepts_content_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """The alias honors the `--content` opt-in for its rows' error field."""
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    seen: dict[str, Any] = {}

    async def fake_samples(
        socket_path: Any,
        eval_id: str,
        active_since: float | None = None,
        **kwargs: Any,
    ) -> _SamplesPage:
        seen.update(kwargs)
        return _SamplesPage(as_of=123.0, samples=[_sample_row("bad", error="boom")])

    monkeypatch.setattr("inspect_ai._cli.ctl._fetch_samples_async", fake_samples)
    result = cli_runner().invoke(ctl_command, ["samples", "--content", "--json"])
    assert result.exit_code == 0, result.output
    assert seen["content"] is True
    assert "is now `inspect ctl sample list`" in result.stderr


def test_errors_alias_accepts_content_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """The alias honors the `--content` opt-in its withheld footer advertises."""
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    seen: dict[str, Any] = {}

    async def fake_samples(
        socket_path: Any,
        eval_id: str,
        active_since: float | None = None,
        **kwargs: Any,
    ) -> _SamplesPage:
        seen.update(kwargs)
        return _SamplesPage(as_of=123.0, samples=[_sample_row("bad", error="boom")])

    monkeypatch.setattr("inspect_ai._cli.ctl._fetch_samples_async", fake_samples)
    result = cli_runner().invoke(ctl_command, ["errors", "--content", "--json"])
    assert result.exit_code == 0, result.output
    assert seen["content"] is True
    assert "is now `inspect ctl sample errors`" in result.stderr


def test_events_alias_accepts_content_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """The alias honors the `--content` opt-in its metadata footer advertises."""
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    seen: dict[str, Any] = {}

    def fake_events(
        socket_path: Any, eval_id: str, sample_id: str, epoch: int, **kwargs: Any
    ) -> dict[str, Any]:
        seen.update(kwargs)
        return {"events": [], "next": None, "done": True}

    monkeypatch.setattr("inspect_ai._cli.ctl._fetch_sample_events", fake_events)
    result = cli_runner().invoke(
        ctl_command, ["events", "aaa111", "s1", "--content", "--json"]
    )
    assert result.exit_code == 0, result.output
    assert seen["content"] is True
    assert "is now `inspect ctl sample events`" in result.stderr


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
    # the provenance params' gate must not outrun the constant either
    from inspect_ai._cli.ctl import _PROVENANCE_SINCE

    assert _PROVENANCE_SINCE <= CONTROL_API_VERSION


def test_mutation_envelope_help_sketches_actual_keys() -> None:
    """The shared --help sketch names exactly `_mutation_envelope`'s keys.

    Every mutation verb's --json help shows `_MUTATION_ENVELOPE_HELP` so a
    scripted consumer can orient the first parse from --help alone; this
    pins the sketch to the envelope builder so the two can't drift.
    """
    from inspect_ai._cli.ctl import _MUTATION_ENVELOPE_HELP, _mutation_envelope

    envelope = _mutation_envelope(
        {"task_id": "aaa111"}, {"ok": True, "changed": True}, dry_run=False
    )
    assert "{" + ", ".join(envelope.keys()) + "}" in _MUTATION_ENVELOPE_HELP


def test_config_help_sketches_compose_config_keys() -> None:
    """`config --help`'s --json sketch names exactly `_compose_config`'s keys."""
    from inspect_ai._cli.ctl import _compose_config, _DirectiveScope, config_command

    scope = _DirectiveScope(
        socket_path="sock", pid=1, task_id=None, task=None, header="", siblings=0
    )
    view = _compose_config(scope, {}, dry_run=False, set_values=False, notes=[])
    option = next(
        p
        for p in config_command.params
        if isinstance(p, click.Option) and p.name == "as_json"
    )
    assert "{" + ", ".join(view.keys()) + "}" in (option.help or "")


def test_every_json_option_help_sketches_payload_keys() -> None:
    """Every visible ctl command's --json help sketches the payload shape.

    The agent output contract: a scripted consumer should learn each
    command's --json top-level keys from --help, not by parsing a payload
    and failing. A brace in the help is the sketch's marker.
    """

    def visible_commands(
        group: click.Group, prefix: str = ""
    ) -> Iterator[tuple[str, click.Command]]:
        for name, cmd in group.commands.items():
            if cmd.hidden:
                continue
            yield f"{prefix}{name}", cmd
            if isinstance(cmd, click.Group):
                yield from visible_commands(cmd, f"{prefix}{name} ")

    for path, cmd in visible_commands(ctl_command):
        json_options = [
            p for p in cmd.params if isinstance(p, click.Option) and p.name == "as_json"
        ]
        if isinstance(cmd, click.Group) and "list" not in cmd.commands:
            # a group without a bare-noun list default (e.g. `model`) carries
            # no mirrored --json of its own; groups with one must mirror it
            continue
        assert json_options, f"`{path}` has no --json option"
        help_text = json_options[0].help or ""
        assert help_text.startswith("Output as JSON ("), path
        assert "{" in help_text, f"`{path}` --json help has no payload sketch"


def _json_help_sketch_keys(*path: str) -> list[str]:
    """The key list inside a command's --json help `{...}` payload sketch."""
    cmd: click.Command = ctl_command
    for name in path:
        assert isinstance(cmd, click.Group)
        cmd = cmd.commands[name]
    option = next(
        p for p in cmd.params if isinstance(p, click.Option) and p.name == "as_json"
    )
    match = re.search(r"\{([^}]*)\}", option.help or "")
    assert match is not None, f"`{' '.join(path)}` --json help has no payload sketch"
    return [key.strip() for key in match.group(1).split(",")]


def _assert_payload_matches_sketch(payload: dict[str, Any], *path: str) -> None:
    """Assert a --json payload's top-level keys match the command's help sketch.

    An exact ordered match, except when the sketch elides keys with `...` (a
    flat object whose middle rides on the server response): there the keys
    before the `...` must lead the payload in order, and every other sketched
    key must be present (their order isn't guaranteed — a key the server's
    row already carries keeps the row's position on dict merge).
    """
    sketch = _json_help_sketch_keys(*path)
    actual = list(payload.keys())
    label = " ".join(path)
    if "..." in sketch:
        cut = sketch.index("...")
        assert actual[:cut] == sketch[:cut], (
            f"`{label}` payload does not lead with the sketched keys: "
            f"{actual} vs sketch {sketch}"
        )
        missing = set(sketch[cut + 1 :]) - set(actual)
        assert not missing, f"`{label}` payload is missing sketched keys {missing}"
    else:
        assert actual == sketch, (
            f"`{label}` payload keys {actual} != help sketch {sketch}"
        )


def test_task_list_json_payload_matches_help_sketch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    result = cli_runner().invoke(ctl_command, ["task", "list", "--json"])
    assert result.exit_code == 0, result.output
    _assert_payload_matches_sketch(json.loads(result.stdout), "task", "list")


def test_sample_listing_json_payload_matches_help_sketch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`sample list` and `sample errors` share the listing envelope sketch."""
    _patch_surface(
        monkeypatch,
        [_full_summary("aaa111", "t1")],
        samples_by_eval={
            "eval_aaa111": [_sample_row("s1"), _sample_row("bad", error="boom")]
        },
    )
    runner = cli_runner()
    for verb in ("list", "errors"):
        result = runner.invoke(ctl_command, ["sample", verb, "--json"])
        assert result.exit_code == 0, result.output
        _assert_payload_matches_sketch(json.loads(result.stdout), "sample", verb)


def test_sample_show_json_payload_matches_help_sketch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The flat show object leads with the sketch's identity keys.

    The payload's middle is the server's detail response (elided as `...` in
    the sketch); the stubbed detail mirrors the terminal-path response shape
    (``message_count`` included, so no fallback listing fetch fires — the
    detail's own keys are pinned by the server-side tests).
    """
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    detail = {
        "sample_id": "s1",
        "epoch": 1,
        "status": "completed",
        "total_time": 1.0,
        "total_tokens": 5,
        "message_count": 1,
        "retries": 0,
        "error": None,
        "error_retries": [],
        "scores": {},
    }
    monkeypatch.setattr(
        "inspect_ai._cli.ctl._fetch_sample_detail", lambda *a, **k: dict(detail)
    )
    result = cli_runner().invoke(
        ctl_command, ["sample", "show", "aaa111", "s1", "--json"]
    )
    assert result.exit_code == 0, result.output
    _assert_payload_matches_sketch(json.loads(result.stdout), "sample", "show")


def test_sample_events_json_payload_matches_help_sketch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both the served page and the no-evals empty page keep the sketched shape."""
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    monkeypatch.setattr(
        "inspect_ai._cli.ctl._fetch_sample_events",
        lambda *a, **k: {"events": [], "next": None, "done": True},
    )
    runner = cli_runner()
    result = runner.invoke(ctl_command, ["sample", "events", "aaa111", "s1", "--json"])
    assert result.exit_code == 0, result.output
    _assert_payload_matches_sketch(json.loads(result.stdout), "sample", "events")

    _patch_surface(monkeypatch, [])
    result = runner.invoke(ctl_command, ["sample", "events", "aaa111", "s1", "--json"])
    assert result.exit_code == 0, result.output
    _assert_payload_matches_sketch(json.loads(result.stdout), "sample", "events")


def test_sample_messages_json_payload_matches_help_sketch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both the served page and the no-evals empty page keep the sketched shape."""
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    monkeypatch.setattr(
        "inspect_ai._cli.ctl._fetch_sample_messages",
        lambda *a, **k: {"as_of": 1.0, "status": "running", "count": 0, "messages": []},
    )
    runner = cli_runner()
    result = runner.invoke(
        ctl_command, ["sample", "messages", "aaa111", "s1", "--json"]
    )
    assert result.exit_code == 0, result.output
    _assert_payload_matches_sketch(json.loads(result.stdout), "sample", "messages")

    _patch_surface(monkeypatch, [])
    result = runner.invoke(
        ctl_command, ["sample", "messages", "aaa111", "s1", "--json"]
    )
    assert result.exit_code == 0, result.output
    _assert_payload_matches_sketch(json.loads(result.stdout), "sample", "messages")


def test_process_list_json_payload_matches_help_sketch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    result = cli_runner().invoke(ctl_command, ["process", "list", "--json"])
    assert result.exit_code == 0, result.output
    _assert_payload_matches_sketch(json.loads(result.stdout), "process", "list")


def test_config_provenance_sent_with_mutations_on_current_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A config mutation carries a defaulted author (and any --reason).

    The author is resolved client-side (git identity / OS user); a pure read
    sends no provenance (there is nothing to record).
    """
    from inspect_ai._control import CONTROL_API_VERSION

    _patch_surface(
        monkeypatch,
        [_full_summary("aaa111", "t1")],
        servers=[_DiscServer(7, api_version=CONTROL_API_VERSION)],
    )
    sent: dict[str, Any] = {}

    def fake_limits(*args: Any, **kwargs: Any) -> _ConfigResult:
        sent.clear()
        sent.update(kwargs)
        return _ConfigResult(
            view={
                "max_samples": {"limit": 3, "in_use": 1, "adjustable": True},
                "max_sandboxes": [],
                "adaptive": [],
                "requested": {"max_samples": 3},
                "warnings": [],
                "dry_run": False,
            },
            mutated=True,
        )

    monkeypatch.setattr("inspect_ai._cli.ctl._exec_limits", fake_limits)

    result = cli_runner().invoke(
        ctl_command, ["config", "--max-samples", "3", "--reason", "ramp up"]
    )
    assert result.exit_code == 0, result.output
    assert isinstance(sent["author"], str) and sent["author"]
    assert sent["reason"] == "ramp up"

    # an explicit --author wins over the default
    result = cli_runner().invoke(
        ctl_command, ["config", "--max-samples", "3", "--author", "alice"]
    )
    assert result.exit_code == 0, result.output
    assert sent["author"] == "alice"
    assert sent["reason"] is None

    # a pure read resolves no provenance
    result = cli_runner().invoke(ctl_command, ["config"])
    assert result.exit_code == 0, result.output
    assert sent["author"] is None
    assert sent["reason"] is None


def test_config_provenance_gated_on_older_server(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provenance params gate on the server version (see _PROVENANCE_SINCE).

    An older strict server 400s the whole mutation on the unknown params, so
    an explicit --author/--reason hard-errors before sending, while the
    *defaulted* author (which the user never typed) is silently dropped and
    the mutation proceeds without it.
    """
    from inspect_ai._cli.ctl import _PROVENANCE_SINCE

    _patch_surface(
        monkeypatch,
        [_full_summary("aaa111", "t1")],
        servers=[_DiscServer(7, api_version=_PROVENANCE_SINCE - 1)],
    )
    sent: dict[str, Any] = {}

    def fake_limits(*args: Any, **kwargs: Any) -> _ConfigResult:
        sent.clear()
        sent.update(kwargs)
        return _ConfigResult(
            view={
                "max_samples": {"limit": 3, "in_use": 1, "adjustable": True},
                "max_sandboxes": [],
                "adaptive": [],
                "requested": {"max_samples": 3},
                "warnings": [],
                "dry_run": False,
            },
            mutated=True,
        )

    monkeypatch.setattr("inspect_ai._cli.ctl._exec_limits", fake_limits)

    result = cli_runner().invoke(
        ctl_command, ["config", "--max-samples", "3", "--reason", "why"]
    )
    assert result.exit_code == 1
    assert "--reason not supported" in result.stderr
    assert "pid 7 is running an older inspect" in result.stderr
    assert not sent  # the mutation was never sent

    result = cli_runner().invoke(
        ctl_command, ["config", "--max-samples", "3", "--author", "alice"]
    )
    assert result.exit_code == 1
    assert "--author not supported" in result.stderr

    # the defaulted author is dropped rather than failing the retune
    result = cli_runner().invoke(ctl_command, ["config", "--max-samples", "3"])
    assert result.exit_code == 0, result.output
    assert sent["author"] is None
    assert sent["reason"] is None


def test_config_provenance_requires_set_option(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit --author/--reason on a pure read hard-errors pre-send.

    A read records nothing, so the provenance would be silently dropped —
    e.g. a user who types `--reason` but forgets the knob. Erroring (like
    --log-buffer with nothing to apply to) makes the mistake visible.
    """
    from inspect_ai._control import CONTROL_API_VERSION

    _patch_surface(
        monkeypatch,
        [_full_summary("aaa111", "t1")],
        servers=[_DiscServer(7, api_version=CONTROL_API_VERSION)],
    )
    sent: dict[str, Any] = {}

    def fake_limits(*args: Any, **kwargs: Any) -> _ConfigResult:
        sent.clear()
        sent.update(kwargs)
        return _ConfigResult(
            view={
                "max_samples": {"limit": 3, "in_use": 1, "adjustable": True},
                "max_sandboxes": [],
                "adaptive": [],
                "requested": {},
                "warnings": [],
                "dry_run": False,
            },
            mutated=False,
        )

    monkeypatch.setattr("inspect_ai._cli.ctl._exec_limits", fake_limits)

    result = cli_runner().invoke(
        ctl_command, ["config", "--reason", "provider incident"]
    )
    assert result.exit_code == 1
    assert "--reason" in result.stderr
    assert "no set option" in result.stderr
    assert not sent  # the read was never sent

    result = cli_runner().invoke(
        ctl_command, ["config", "--author", "alice", "--reason", "why"]
    )
    assert result.exit_code == 1
    assert "--author / --reason" in result.stderr
    assert not sent


def test_config_provenance_rides_key_only_retune(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A key-only retune is a recorded mutation and carries provenance.

    `--key` changes are recorded in the eval log like any other knob
    (as `config="concurrency"` changes), so an explicit --reason goes
    through and a defaulted author is resolved client-side.
    """
    from inspect_ai._control import CONTROL_API_VERSION

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
                "requested": {"concurrency:my_api": 2},
                "warnings": [],
                "dry_run": False,
            },
            mutated=True,
        )

    monkeypatch.setattr("inspect_ai._cli.ctl._exec_limits", fake_limits)

    result = cli_runner().invoke(
        ctl_command,
        ["config", "--key", "my_api", "2", "--reason", "provider incident"],
    )
    assert result.exit_code == 0, result.output
    assert sent["key"] == ("my_api", 2)
    assert sent["reason"] == "provider incident"
    assert isinstance(sent["author"], str) and sent["author"]


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


def test_print_messages_table_and_footer(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from inspect_ai._cli.ctl import _print_messages

    page = {
        "status": "running",
        "count": 5,
        "messages": [
            {"index": 3, "role": "user", "content": "what is the weather?"},
            {
                "index": 4,
                "role": "assistant",
                "content": "let me check",
                "tool_calls": [{"function": "search", "arguments": "weather"}],
            },
        ],
    }
    _print_messages(page, content=True, full=False)
    out = capsys.readouterr().out
    assert "role" in out.splitlines()[0]  # table header
    assert "what is the weather?" in out and "search" in out
    # footer: shown-of-total, the --all hint (a tail was shown), and status
    assert "2 of 5 messages" in out
    assert "--all" in out
    assert "running" in out
    # a content read carries no metadata-only pointer
    assert "metadata only" not in out


def test_print_messages_metadata_rows_and_footer_hint(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Metadata-only rows render roles / function names / error presence.

    The footer points at the --content opt-in.
    """
    from inspect_ai._cli.ctl import _print_messages

    page = {
        "status": "running",
        "count": 3,
        "messages": [
            {"index": 0, "role": "user"},
            {
                "index": 1,
                "role": "assistant",
                "tool_calls": [{"id": "c1", "function": "search"}],
            },
            {"index": 2, "role": "tool", "function": "search", "has_error": True},
        ],
    }
    _print_messages(page, content=False, full=False)
    out = capsys.readouterr().out
    assert "search" in out and "error" in out
    assert "metadata only (pass --content for text)" in out


def test_print_messages_footer_response_keyed_on_old_server(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """No "metadata only" hint under content a pre-v6 server returned anyway.

    Pre-v6 message projections carry ``content`` on every message; its
    presence means the server ignored the metadata-only request.
    """
    from inspect_ai._cli.ctl import _print_messages

    page = {
        "status": "running",
        "count": 1,
        "messages": [{"index": 0, "role": "user", "content": "hi there"}],
    }
    _print_messages(page, content=False, full=False)
    out = capsys.readouterr().out
    assert "hi there" in out
    assert "metadata only" not in out


def test_print_messages_empty(capsys: pytest.CaptureFixture[str]) -> None:
    from inspect_ai._cli.ctl import _print_messages

    _print_messages(
        {"status": "completed", "count": 0, "messages": []}, content=True, full=False
    )
    out = capsys.readouterr().out
    assert "(no messages)" in out
    # nothing withheld, so no --all hint
    assert "--all" not in out


def test_messages_unseeded_defaults_to_recent_tail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The first messages page is a recent tail, not the whole conversation."""
    captured: dict[str, Any] = {}

    def fake_messages(
        socket_path: Any, eval_id: str, sample_id: str, epoch: int, **kwargs: Any
    ) -> dict[str, Any]:
        captured.clear()
        captured.update(kwargs)
        return {"as_of": 1.0, "status": "running", "count": 0, "messages": []}

    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    monkeypatch.setattr("inspect_ai._cli.ctl._fetch_sample_messages", fake_messages)
    runner = cli_runner()

    result = runner.invoke(
        ctl_command, ["sample", "messages", "aaa111", "s1", "--json"]
    )
    assert result.exit_code == 0, result.output
    assert captured["tail"] == 20

    # --all disables the default tail (whole conversation)
    runner.invoke(ctl_command, ["sample", "messages", "aaa111", "s1", "--all"])
    assert captured["tail"] is None

    # an explicit --tail overrides the default
    runner.invoke(ctl_command, ["sample", "messages", "aaa111", "s1", "--tail", "3"])
    assert captured["tail"] == 3

    # the resolved identifiers are echoed on the page
    result = runner.invoke(
        ctl_command, ["sample", "messages", "aaa111", "s1", "--json"]
    )
    payload = json.loads(result.stdout)
    assert payload["task_id"] == "aaa111"
    assert (payload["sample_id"], payload["epoch"]) == ("s1", 1)


def test_messages_all_and_tail_are_mutually_exclusive() -> None:
    result = cli_runner().invoke(
        ctl_command, ["sample", "messages", "t", "s1", "--all", "--tail", "5"]
    )
    assert result.exit_code != 0
    assert "mutually exclusive" in result.stderr


def test_messages_json_no_servers_echoes_identifiers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The no-running-evals empty page keeps the identifier echo shape."""
    monkeypatch.setattr("inspect_ai._cli.ctl.list_discovered_servers", lambda: [])
    result = cli_runner().invoke(
        ctl_command, ["sample", "messages", "aaa111", "s1", "--json"]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["task_id"] is None
    assert (payload["sample_id"], payload["epoch"]) == ("s1", 1)
    assert payload["messages"] == [] and payload["count"] == 0
    # the envelope shape stays uniform: as_of is present (None — no server
    # stamped a read time)
    assert "as_of" in payload and payload["as_of"] is None


def test_messages_rejects_non_positive_tail() -> None:
    """--tail must be >= 1; a negative/zero window is a usage error."""
    for value in ("-3", "0"):
        result = cli_runner().invoke(
            ctl_command, ["sample", "messages", "t", "s1", "--tail", value]
        )
        assert result.exit_code != 0
        assert "--tail" in result.stderr


def test_messages_missing_route_names_version_skew(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A router 404 (no `error` body) means the server predates the endpoint."""
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    _stub_httpx(monkeypatch, [(404, {"detail": "Not Found"})])
    result = cli_runner().invoke(ctl_command, ["sample", "messages", "aaa111", "s1"])
    assert result.exit_code == 1
    assert "older inspect without the sample messages endpoint" in result.stderr
    assert "not yet been written" not in result.stderr


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

    async def fake_samples(
        socket_path: Any,
        eval_id: str,
        active_since: float | None = None,
        **kwargs: Any,
    ) -> _SamplesPage:
        captured["active_since"] = active_since
        return _SamplesPage(as_of=123.0, samples=[])

    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    monkeypatch.setattr("inspect_ai._cli.ctl._fetch_samples_async", fake_samples)
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
        pid=7,
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
        pid=7,
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
    """--no-terse pins the full rendering (the runner's stdout is not a TTY)."""
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    spy = _RequestSpy({"ok": True, "changed": True, "in_flight": 3})
    monkeypatch.setattr("inspect_ai._cli.ctl._request_json", spy)
    result = cli_runner().invoke(
        ctl_command, ["task", "cancel", "aaa111", "--no-terse"]
    )
    assert result.exit_code == 0, result.output
    assert "·" in result.stdout  # the task header
    assert "Cancel requested" in result.stdout
    assert "3 in-flight samples" in result.stdout


def test_task_cancel_terse_line(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-TTY stdout (the runner's) defaults to one header-free outcome line."""
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    spy = _RequestSpy({"ok": True, "changed": True, "in_flight": 3})
    monkeypatch.setattr("inspect_ai._cli.ctl._request_json", spy)
    result = cli_runner().invoke(ctl_command, ["task", "cancel", "aaa111"])
    assert result.exit_code == 0, result.output
    assert result.stdout == (
        "cancel t1: requested — 3 in-flight samples will be interrupted; "
        "completed samples are kept\n"
    )


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
    result = cli_runner().invoke(ctl_command, ["task", "pause", "aaa111", "--no-terse"])
    assert result.exit_code == 0, result.output
    assert "Pause requested" in result.output
    assert "3 dispatched samples" in result.output


def test_task_pause_terse_line(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    spy = _RequestSpy({"ok": True, "paused": "task", "changed": True, "dispatched": 3})
    monkeypatch.setattr("inspect_ai._cli.ctl._request_json", spy)
    result = cli_runner().invoke(ctl_command, ["task", "pause", "aaa111"])
    assert result.exit_code == 0, result.output
    assert result.stdout == (
        "pause t1: requested — 3 dispatched samples will finish naturally; "
        "no new samples or retry attempts will start\n"
    )


def test_task_resume_human_output_notes_process_latch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A task resume that leaves the task held by the process latch says so."""
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    spy = _RequestSpy({"ok": True, "paused": "process", "changed": True})
    monkeypatch.setattr("inspect_ai._cli.ctl._request_json", spy)
    result = cli_runner().invoke(
        ctl_command, ["task", "resume", "aaa111", "--no-terse"]
    )
    assert result.exit_code == 0, result.output
    assert spy.paths == ["/tasks/aaa111/resume"]
    assert "Resume requested" in result.output
    assert "process is paused" in result.output


def test_task_resume_terse_line_notes_still_held(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The terse resume line still reports the latch that keeps the task held."""
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    spy = _RequestSpy({"ok": True, "paused": "process", "changed": True})
    monkeypatch.setattr("inspect_ai._cli.ctl._request_json", spy)
    result = cli_runner().invoke(ctl_command, ["task", "resume", "aaa111"])
    assert result.exit_code == 0, result.output
    assert result.stdout == (
        "resume t1: requested — queued samples will dispatch again "
        "(still held by process pause — `inspect ctl process resume`)\n"
    )


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
    result = cli_runner().invoke(
        ctl_command, ["task", "resume", "aaa111", "--no-terse"]
    )
    assert result.exit_code == 0, result.output
    assert "Nothing to do: task is not paused." in result.output
    assert "process is paused" in result.output

    terse = cli_runner().invoke(ctl_command, ["task", "resume", "aaa111"])
    assert terse.exit_code == 0, terse.output
    assert terse.stdout == (
        "resume t1: no-op — task is not paused (still held by process pause "
        "— `inspect ctl process resume`)\n"
    )


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


def test_model_pause_json_mutation_envelope(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "inspect_ai._cli.ctl.list_discovered_servers", lambda: [_DiscServer(7)]
    )
    spy = _RequestSpy(
        {
            "ok": True,
            "model": "openai/gpt-5",
            "paused": True,
            "changed": True,
            "tasks": 1,
            "dispatched": 2,
        }
    )
    monkeypatch.setattr("inspect_ai._cli.ctl._request_json", spy)
    result = cli_runner().invoke(
        ctl_command, ["model", "pause", "openai/gpt-5", "--json"]
    )
    assert result.exit_code == 0, result.output
    assert spy.paths == ["/models/pause"]
    # the model rides as a query param — model names contain `/`, which a
    # path segment can't carry
    assert spy.params == [{"model": "openai/gpt-5"}]
    payload = json.loads(result.stdout)
    assert payload["target"] == {"model": "openai/gpt-5", "pid": 7}
    assert payload["applied"] is True and payload["dry_run"] is False
    assert payload["detail"]["tasks"] == 1


def test_model_resume_pid_is_positional(monkeypatch: pytest.MonkeyPatch) -> None:
    posted: list[str] = []

    def record(socket_path: str, path: str, **kwargs: Any) -> dict[str, Any]:
        posted.append(str(socket_path))
        return {"ok": True, "model": "m/x", "paused": False, "changed": True}

    monkeypatch.setattr(
        "inspect_ai._cli.ctl.list_discovered_servers",
        lambda: [_DiscServer(7), _DiscServer(8)],
    )
    monkeypatch.setattr("inspect_ai._cli.ctl._request_json", record)
    result = cli_runner().invoke(ctl_command, ["model", "resume", "m/x", "8"])
    assert result.exit_code == 0, result.output
    assert posted == ["/tmp/8.sock"]


def test_model_pause_multiple_processes_requires_pid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "inspect_ai._cli.ctl.list_discovered_servers",
        lambda: [_DiscServer(7), _DiscServer(8)],
    )
    result = cli_runner().invoke(ctl_command, ["model", "pause", "m/x"])
    assert result.exit_code == 1
    assert "Pass a PID" in result.stderr


def test_model_pause_dry_run_rides_query_param(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "inspect_ai._cli.ctl.list_discovered_servers", lambda: [_DiscServer(7)]
    )
    # `paused` is the actual latch state, still False under a dry-run pause
    spy = _RequestSpy(
        {
            "ok": True,
            "model": "m/x",
            "paused": False,
            "changed": True,
            "dry_run": True,
            "tasks": 0,
            "dispatched": 0,
        }
    )
    monkeypatch.setattr("inspect_ai._cli.ctl._request_json", spy)
    result = cli_runner().invoke(
        ctl_command, ["model", "pause", "m/x", "--dry-run", "--json"]
    )
    assert result.exit_code == 0, result.output
    assert spy.params == [{"model": "m/x", "dry_run": True}]
    payload = json.loads(result.stdout)
    assert payload["applied"] is False and payload["dry_run"] is True


def test_model_pause_noop_human_output(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "inspect_ai._cli.ctl.list_discovered_servers", lambda: [_DiscServer(7)]
    )
    monkeypatch.setattr(
        "inspect_ai._cli.ctl._request_json",
        lambda *a, **k: {
            "ok": True,
            "model": "m/x",
            "paused": True,
            "changed": False,
            "reason": "model already paused",
        },
    )
    result = cli_runner().invoke(ctl_command, ["model", "pause", "m/x"])
    assert result.exit_code == 0, result.output
    assert "Nothing to do" in result.output
    assert "already paused" in result.output


def test_task_resume_notes_model_latch(monkeypatch: pytest.MonkeyPatch) -> None:
    """A task resume that leaves the task held by its model points at the latch."""
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    spy = _RequestSpy(
        {
            "ok": True,
            "paused": ["model"],
            "changed": True,
        }
    )
    monkeypatch.setattr("inspect_ai._cli.ctl._request_json", spy)
    result = cli_runner().invoke(
        ctl_command, ["task", "resume", "aaa111", "--no-terse"]
    )
    assert result.exit_code == 0, result.output
    assert "model is paused" in result.output
    assert "inspect ctl model resume" in result.output


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


def test_sample_requeue_defaults_epoch_for_single_epoch_task(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary = _full_summary("aaa111", "t1")
    summary["epochs"] = 1
    _patch_surface(monkeypatch, [summary])
    spy = _RequestSpy({"ok": True, "sample_id": "s1", "epoch": 1, "changed": True})
    monkeypatch.setattr("inspect_ai._cli.ctl._request_json", spy)
    result = cli_runner().invoke(
        ctl_command, ["sample", "requeue", "aaa111", "s1", "--json"]
    )
    assert result.exit_code == 0, result.output
    assert spy.paths == ["/evals/eval_aaa111/sample/requeue"]
    assert spy.params == [{"sample_id": "s1", "epoch": 1}]
    payload = json.loads(result.stdout)
    assert payload["target"]["sample_id"] == "s1"
    assert payload["target"]["epoch"] == 1
    assert payload["applied"] is True


def test_sample_requeue_requires_epoch_when_multi_epoch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A defaulted epoch on a multi-epoch task resolves to a different sample."""
    summary = _full_summary("aaa111", "t1")
    summary["epochs"] = 3
    _patch_surface(monkeypatch, [summary])
    spy = _RequestSpy({"ok": True, "changed": True})
    monkeypatch.setattr("inspect_ai._cli.ctl._request_json", spy)
    result = cli_runner().invoke(ctl_command, ["sample", "requeue", "aaa111", "s1"])
    assert result.exit_code == 1
    assert "pass EPOCH explicitly" in result.stderr
    assert spy.paths == []  # nothing was sent

    # ...and an explicit epoch goes through
    ok = cli_runner().invoke(ctl_command, ["sample", "requeue", "aaa111", "s1", "2"])
    assert ok.exit_code == 0, ok.output
    assert spy.params == [{"sample_id": "s1", "epoch": 2}]


def test_sample_requeue_dry_run_and_human_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    summary = _full_summary("aaa111", "t1")
    summary["epochs"] = 1
    _patch_surface(monkeypatch, [summary])
    spy = _RequestSpy(
        {
            "ok": True,
            "sample_id": "s1",
            "epoch": 1,
            "changed": True,
            "dry_run": True,
            "resume_from_checkpoint": True,
        }
    )
    monkeypatch.setattr("inspect_ai._cli.ctl._request_json", spy)
    result = cli_runner().invoke(
        ctl_command, ["sample", "requeue", "aaa111", "s1", "--dry-run", "--no-terse"]
    )
    assert result.exit_code == 0, result.output
    assert spy.params == [{"sample_id": "s1", "epoch": 1, "dry_run": True}]
    assert "Would requeue" in result.stdout
    assert "resume from its checkpoint" in result.stdout


def test_sample_requeue_noop_human_output(monkeypatch: pytest.MonkeyPatch) -> None:
    summary = _full_summary("aaa111", "t1")
    summary["epochs"] = 1
    _patch_surface(monkeypatch, [summary])
    spy = _RequestSpy(
        {
            "ok": True,
            "sample_id": "s1",
            "epoch": 1,
            "changed": False,
            "status": "queued",
            "reason": "a re-run is already pending",
        }
    )
    monkeypatch.setattr("inspect_ai._cli.ctl._request_json", spy)
    result = cli_runner().invoke(
        ctl_command, ["sample", "requeue", "aaa111", "s1", "--no-terse"]
    )
    assert result.exit_code == 0, result.output
    assert "Nothing to do" in result.stdout
    assert "a re-run is already pending" in result.stdout

    # in the terse line the no-op names its target — a loop's outcome lines
    # stay attributable without the header (the full no-op leans on it)
    terse = cli_runner().invoke(ctl_command, ["sample", "requeue", "aaa111", "s1"])
    assert terse.exit_code == 0, terse.output
    assert terse.stdout == (
        "requeue t1/s1 (epoch 1): no-op — a re-run is already pending\n"
    )


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
    result = cli_runner().invoke(
        ctl_command, ["sample", "cancel", "aaa111", "s1", "--no-terse"]
    )
    assert result.exit_code == 0, result.output
    assert "already finished" in result.stdout
    assert "status: completed" in result.stdout


def test_sample_mutation_terse_default_and_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Repeated mutations read as one `verb target: outcome` line each.

    The runner's captured stdout is not a TTY, so the terse default applies
    (issue #160: 44 requeues in a loop should be 44 scannable lines, not 44
    task-status banners); an explicit --terse forces the same line and
    --json still wins over it.
    """
    summary = _full_summary("aaa111", "t1")
    summary["epochs"] = 1
    _patch_surface(monkeypatch, [summary])
    spy = _RequestSpy({"ok": True, "sample_id": "s1", "epoch": 1, "changed": True})
    monkeypatch.setattr("inspect_ai._cli.ctl._request_json", spy)

    requeue = cli_runner().invoke(ctl_command, ["sample", "requeue", "aaa111", "s1"])
    assert requeue.exit_code == 0, requeue.output
    assert requeue.stdout == (
        "requeue t1/s1 (epoch 1): accepted — will re-run from the back of "
        "the sample queue\n"
    )

    cancel = cli_runner().invoke(
        ctl_command, ["sample", "cancel", "aaa111", "s1", "--terse"]
    )
    assert cancel.exit_code == 0, cancel.output
    assert cancel.stdout == (
        "cancel t1/s1 (epoch 1): requested — will be scored on the work done so far\n"
    )

    as_json = cli_runner().invoke(
        ctl_command, ["sample", "requeue", "aaa111", "s1", "--terse", "--json"]
    )
    assert as_json.exit_code == 0, as_json.output
    assert json.loads(as_json.stdout)["applied"] is True


def test_use_terse_resolves_by_tty(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neither --terse nor --no-terse given resolves by stdout TTY-ness."""
    from inspect_ai._cli.ctl import _use_terse

    class _Stream:
        def __init__(self, tty: bool) -> None:
            self._tty = tty

        def isatty(self) -> bool:
            return self._tty

    monkeypatch.setattr("sys.stdout", _Stream(tty=True))
    assert _use_terse(None) is False
    assert _use_terse(True) is True

    monkeypatch.setattr("sys.stdout", _Stream(tty=False))
    assert _use_terse(None) is True
    assert _use_terse(False) is False


def test_log_flush_terse_line(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    monkeypatch.setattr(
        "inspect_ai._cli.ctl._post_flush", lambda *a, **k: {"flushed": 2}
    )
    result = cli_runner().invoke(ctl_command, ["task", "log-flush"])
    assert result.exit_code == 0, result.output
    assert result.stdout == "log-flush t1: applied — flushed 2 samples\n"

    monkeypatch.setattr(
        "inspect_ai._cli.ctl._post_flush", lambda *a, **k: {"flushed": 0}
    )
    noop = cli_runner().invoke(ctl_command, ["task", "log-flush"])
    assert noop.exit_code == 0, noop.output
    assert noop.stdout == "log-flush t1: no-op — no buffered samples\n"


def test_config_set_terse_line(monkeypatch: pytest.MonkeyPatch) -> None:
    """A terse config set reports the requested knobs, not the whole view."""
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    _stub_limits(
        monkeypatch, buffer={"log_buffer": 10, "pending": 0, "log_shared": None}
    )
    result = cli_runner().invoke(ctl_command, ["config", "--max-samples", "3"])
    assert result.exit_code == 0, result.output
    assert result.stdout == "config t1: applied — max_samples=3\n"

    dry = cli_runner().invoke(
        ctl_command, ["config", "--max-samples", "3", "--dry-run"]
    )
    assert dry.exit_code == 0, dry.output
    assert dry.stdout == "config t1: dry-run — max_samples=3\n"

    # --model narrows a connections retune — the line must say so
    modeled = cli_runner().invoke(
        ctl_command, ["config", "--max-connections", "9", "--model", "gpt-4"]
    )
    assert modeled.exit_code == 0, modeled.output
    assert modeled.stdout == (
        "config t1: applied — max_connections=9 (models matching 'gpt-4')\n"
    )


def test_config_set_terse_keeps_warnings_and_notes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The terse `applied` claim stays honest.

    Warnings and the process-scope blast-radius note survive as extra lines.
    """
    _patch_surface(
        monkeypatch, [_full_summary("aaa111", "t1"), _full_summary("bbb222", "t2")]
    )
    _stub_limits(monkeypatch)
    result = cli_runner().invoke(ctl_command, ["config", "--max-sandboxes", "4"])
    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    assert lines[0] == "config pid 7: applied — max_sandboxes=4"
    assert any(
        line.startswith("note: ") and "--max-sandboxes" in line for line in lines[1:]
    )


def test_config_view_ignores_terse(monkeypatch: pytest.MonkeyPatch) -> None:
    """A pure view renders the full config block — terse covers only a set."""
    _patch_surface(monkeypatch, [_full_summary("aaa111", "t1")])
    _stub_limits(
        monkeypatch, buffer={"log_buffer": 10, "pending": 0, "log_shared": None}
    )
    result = cli_runner().invoke(ctl_command, ["config", "--terse"])
    assert result.exit_code == 0, result.output
    assert "config:" in result.stdout
    assert "max samples [task]:" in result.stdout


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
    assert scope.pid == 7  # carried for the busy-escalation pointer


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


def test_sample_list_reads_evals_concurrently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unscoped `sample list` issues its per-eval reads together.

    One blocking read per eval in series is what made this command look hung
    on an eval set with many running tasks. Each fake read here parks until
    the *next* eval's read has completed, so the listing only finishes if
    every read is in flight at once, and the completion order is the reverse
    of the target order — which the rows must not inherit.
    """
    tasks = [_full_summary(f"aaa{i}", f"t{i}") for i in range(4)]
    _patch_surface(monkeypatch, tasks)
    state: dict[str, Any] = {}

    async def fake_samples(
        socket_path: Any,
        eval_id: str,
        active_since: float | None = None,
        **kwargs: Any,
    ) -> _SamplesPage:
        if not state:
            # created up front, by whichever read runs first: a read parks on
            # its successor's event, which must therefore already exist
            state["done"] = [anyio.Event() for _ in tasks]
        index = int(eval_id.removeprefix("eval_aaa"))
        if index + 1 < len(tasks):
            await _await_sibling(state["done"][index + 1], f"the read for {eval_id}")
        state["done"][index].set()
        return _SamplesPage(as_of=200.0 - index, samples=[_sample_row(f"s{index}")])

    monkeypatch.setattr("inspect_ai._cli.ctl._fetch_samples_async", fake_samples)
    result = cli_runner().invoke(ctl_command, ["sample", "list", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert [s["sample_id"] for s in payload["samples"]] == ["s0", "s1", "s2", "s3"]
    assert [s["task_id"] for s in payload["samples"]] == [f"aaa{i}" for i in range(4)]
    # the envelope keeps the earliest per-eval as_of, so a later poll can't
    # skip changes that landed while a slower sibling read was still running
    assert payload["as_of"] == 197.0


def test_sample_list_caps_reads_in_flight(monkeypatch: pytest.MonkeyPatch) -> None:
    """The fan-out reads in bounded waves rather than opening one read per eval.

    A fan-out spans every task in the run, so "all at once" scales with the
    eval set: the reads all land on a server sharing the eval's single event
    loop, and a client that runs out of file descriptors reports the evals it
    could not reach as gone. The wave here is held open until it is full, so
    the test fails distinguishably if the cap is never reached (too serial)
    or exceeded (uncapped).
    """
    from inspect_ai._cli.ctl import _MAX_CONCURRENT_READS

    tasks = [
        _full_summary(f"aaa{i}", f"t{i}") for i in range(_MAX_CONCURRENT_READS + 2)
    ]
    _patch_surface(monkeypatch, tasks)
    state: dict[str, Any] = {"in_flight": 0, "peak": 0}

    async def fake_samples(
        socket_path: Any,
        eval_id: str,
        active_since: float | None = None,
        **kwargs: Any,
    ) -> _SamplesPage:
        if "full" not in state:
            state["full"] = anyio.Event()
        state["in_flight"] += 1
        state["peak"] = max(state["peak"], state["in_flight"])
        if state["in_flight"] == _MAX_CONCURRENT_READS:
            state["full"].set()
        try:
            with anyio.fail_after(2):
                await state["full"].wait()
        except TimeoutError:
            raise AssertionError(
                f"only {state['peak']} reads were ever in flight after 2s — "
                f"expected a full wave of {_MAX_CONCURRENT_READS}"
            ) from None
        state["in_flight"] -= 1
        return _SamplesPage(
            as_of=123.0,
            samples=[_sample_row(eval_id.removeprefix("eval_"))],
        )

    monkeypatch.setattr("inspect_ai._cli.ctl._fetch_samples_async", fake_samples)
    result = cli_runner().invoke(ctl_command, ["sample", "list", "--all", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    # every target is still read — the cap paces the fan-out, it doesn't trim it
    assert [s["sample_id"] for s in payload["samples"]] == [t["task_id"] for t in tasks]
    assert state["peak"] == _MAX_CONCURRENT_READS


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
    # the escalation pointer is stderr-only prose — never in the envelope
    assert "anomalies" not in error["message"]
    # the stderr narration is unchanged (it remains the human channel); the
    # pointer names the pid the read targeted rather than the bare verb
    assert "gave up" in result.stderr
    assert "inspect ctl process anomalies 7" in result.stderr


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
    assert "anomalies" not in error["message"]  # no teaching prose in envelopes


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


# --- process anomalies (client-side trace-file read) ------------------------


def _anomalous_records() -> list[dict[str, Any]]:
    """One running Model action, one cancelled Subprocess, one errored Sandbox."""
    start = 1000.0
    return [
        action_record("run1", "Model", "enter", detail="generate", start_time=start),
        action_record("can1", "Subprocess", "enter", detail="bash", start_time=start),
        action_record("can1", "Subprocess", "cancel", detail="bash", duration=5.0),
        action_record("err1", "Sandbox", "enter", detail="exec", start_time=start),
        action_record("err1", "Sandbox", "error", detail="exec", duration=7.0),
    ]


@pytest.fixture
def trace_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the ctl trace-file resolution at a per-test directory."""
    monkeypatch.setattr("inspect_ai._cli.ctl.inspect_trace_dir", lambda: tmp_path)
    return tmp_path


def test_process_anomalies_explicit_pid_json(trace_dir: Path) -> None:
    write_trace_log(trace_dir / "trace-123.log", _anomalous_records())
    result = cli_runner().invoke(ctl_command, ["process", "anomalies", "123", "--json"])
    assert result.exit_code == 0
    envelope = json.loads(result.stdout)
    assert isinstance(envelope["as_of"], float)
    (section,) = envelope["processes"]
    assert section["pid"] == 123
    assert section["trace_file"] == (trace_dir / "trace-123.log").as_posix()
    # all four buckets always present and populated (--all gates only the
    # human rendering), so empty always means "none occurred"
    assert [row["action"] for row in section["running"]] == ["Model"]
    assert [row["action"] for row in section["cancelled"]] == ["Subprocess"]
    assert [row["action"] for row in section["errors"]] == ["Sandbox"]
    assert section["timeouts"] == []


def test_process_anomalies_json_payload_matches_help_sketch(trace_dir: Path) -> None:
    write_trace_log(trace_dir / "trace-123.log", _anomalous_records())
    result = cli_runner().invoke(ctl_command, ["process", "anomalies", "123", "--json"])
    assert result.exit_code == 0
    _assert_payload_matches_sketch(json.loads(result.stdout), "process", "anomalies")


def test_process_anomalies_dead_pid_reads_gz(
    trace_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A pid with no live process still resolves via the gzipped post-mortem file."""
    import gzip

    monkeypatch.setattr("inspect_ai._cli.ctl.pid_alive", lambda _pid: False)
    with gzip.open(trace_dir / "trace-124.log.gz", "wt") as f:
        for record in _anomalous_records():
            f.write(json.dumps(record) + "\n")
    result = cli_runner().invoke(ctl_command, ["process", "anomalies", "124", "--json"])
    assert result.exit_code == 0
    (section,) = json.loads(result.stdout)["processes"]
    assert section["trace_file"].endswith("trace-124.log.gz")
    assert [row["action"] for row in section["running"]] == ["Model"]


def test_process_anomalies_dead_pid_durations_date_to_last_write(
    trace_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Post-mortem running durations use the trace file's last write, not now.

    An action in flight when the process died must not accrue wall-clock
    time since (an overnight death would otherwise show it "running" for
    hours); the file's mtime approximates the time of death.
    """
    monkeypatch.setattr("inspect_ai._cli.ctl.pid_alive", lambda _pid: False)
    trace_file = trace_dir / "trace-125.log"
    write_trace_log(trace_file, _anomalous_records())  # running since t=1000.0
    os.utime(trace_file, (1180.0, 1180.0))

    result = cli_runner().invoke(ctl_command, ["process", "anomalies", "125", "--json"])
    assert result.exit_code == 0
    assert "last write" in result.stderr
    (section,) = json.loads(result.stdout)["processes"]
    assert section["as_of"] == pytest.approx(1180.0)
    assert section["running"][0]["duration"] == pytest.approx(180.0)

    # the human table dates durations the same way
    result = cli_runner().invoke(ctl_command, ["process", "anomalies", "125"])
    assert result.exit_code == 0
    assert "180.00s" in result.stdout


def test_process_anomalies_live_pid_durations_date_to_read(
    trace_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A live pid's running durations date to when its file was read.

    The section as_of is stamped after the read (so an ``enter`` record that
    lands mid-read can't yield a negative duration); the envelope as_of is
    stamped before the reads (cursor semantics), so section >= envelope.
    """
    monkeypatch.setattr("inspect_ai._cli.ctl.pid_alive", lambda _pid: True)
    write_trace_log(trace_dir / "trace-126.log", _anomalous_records())
    result = cli_runner().invoke(ctl_command, ["process", "anomalies", "126", "--json"])
    assert result.exit_code == 0
    envelope = json.loads(result.stdout)
    (section,) = envelope["processes"]
    assert section["as_of"] >= envelope["as_of"]
    assert section["running"][0]["duration"] == pytest.approx(section["as_of"] - 1000.0)


def test_process_anomalies_missing_trace_file_errors(trace_dir: Path) -> None:
    result = cli_runner().invoke(ctl_command, ["process", "anomalies", "999"])
    assert result.exit_code != 0
    # names the path it looked for and teaches the direct-file fallback
    assert "trace-999.log" in result.stderr
    assert "inspect trace anomalies" in result.stderr

    result = cli_runner().invoke(ctl_command, ["process", "anomalies", "999", "--json"])
    assert result.exit_code != 0
    assert json.loads(result.stdout)["error"]["kind"] == "not_found"


def test_process_anomalies_widens_over_running_processes(
    trace_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_trace_log(trace_dir / "trace-7.log", _anomalous_records())
    write_trace_log(trace_dir / "trace-8.log", _anomalous_records())
    monkeypatch.setattr(
        "inspect_ai._cli.ctl.list_discovered_servers",
        lambda: [_FakeServer(7), _FakeServer(8)],
    )
    result = cli_runner().invoke(ctl_command, ["process", "anomalies", "--json"])
    assert result.exit_code == 0
    envelope = json.loads(result.stdout)
    assert [p["pid"] for p in envelope["processes"]] == [7, 8]

    # human output renders one labeled section per pid
    result = cli_runner().invoke(ctl_command, ["process", "anomalies"])
    assert result.exit_code == 0
    assert "pid 7" in result.stdout and "pid 8" in result.stdout


def test_process_anomalies_widen_skips_missing_trace_file(
    trace_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_trace_log(trace_dir / "trace-8.log", _anomalous_records())
    monkeypatch.setattr(
        "inspect_ai._cli.ctl.list_discovered_servers",
        lambda: [_FakeServer(7), _FakeServer(8)],
    )
    result = cli_runner().invoke(ctl_command, ["process", "anomalies", "--json"])
    assert result.exit_code == 0
    assert [p["pid"] for p in json.loads(result.stdout)["processes"]] == [8]
    assert "no trace file found for pid 7" in result.stderr


def test_process_anomalies_tolerates_truncated_final_line(trace_dir: Path) -> None:
    """A truncated final line (hard kill, or caught mid-write) is skipped.

    The intact prefix holds the answer the read exists for — the verb must
    report it rather than fail on the partial record.
    """
    trace_file = trace_dir / "trace-123.log"
    write_trace_log(trace_file, _anomalous_records())
    with open(trace_file, "a") as f:
        f.write('{"timestamp": "2026-07-16T12:0')
    result = cli_runner().invoke(ctl_command, ["process", "anomalies", "123", "--json"])
    assert result.exit_code == 0
    (section,) = json.loads(result.stdout)["processes"]
    assert [row["action"] for row in section["running"]] == ["Model"]


def test_process_anomalies_widen_skips_unreadable_trace_file(
    trace_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One pid's unreadable trace file doesn't abort the other sections."""
    (trace_dir / "trace-7.log.gz").write_bytes(b"not gzip")
    write_trace_log(trace_dir / "trace-8.log", _anomalous_records())
    monkeypatch.setattr(
        "inspect_ai._cli.ctl.list_discovered_servers",
        lambda: [_FakeServer(7), _FakeServer(8)],
    )
    result = cli_runner().invoke(ctl_command, ["process", "anomalies", "--json"])
    assert result.exit_code == 0
    assert [p["pid"] for p in json.loads(result.stdout)["processes"]] == [8]
    assert "could not read" in result.stderr


def test_process_anomalies_explicit_pid_read_failure_errors(
    trace_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An explicit pid whose file is unreadable fails loudly, not silently empty.

    Both output modes follow the terminal-error contract: ``--json`` emits
    the ``internal`` envelope; human mode echoes self-contained stderr prose
    and exits 1 rather than surfacing a raw traceback.
    """
    monkeypatch.setattr("inspect_ai._cli.ctl.pid_alive", lambda _pid: False)
    (trace_dir / "trace-124.log.gz").write_bytes(b"not gzip")

    result = cli_runner().invoke(ctl_command, ["process", "anomalies", "124", "--json"])
    assert result.exit_code == 1
    error = json.loads(result.stdout)["error"]
    assert error["kind"] == "internal"
    assert "trace-124.log.gz" in error["message"]

    result = cli_runner().invoke(ctl_command, ["process", "anomalies", "124"])
    assert result.exit_code == 1
    assert result.stdout == ""
    assert "Could not read trace file" in result.stderr
    assert isinstance(result.exception, SystemExit)


def test_process_anomalies_widen_skips_corrupt_gz_stream(
    trace_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mid-stream gz corruption is skipped like any other unreadable file.

    A corrupted deflate stream raises ``zlib.error`` — neither ``OSError``
    (the ``b"not gzip"`` header case) nor ``ValueError`` — so this pins the
    warn-and-skip contract to "unreadable file", not a closed exception list.
    """
    import gzip
    import zlib

    from inspect_ai._util.trace import read_trace_file

    data = "".join(json.dumps(r) + "\n" for r in _anomalous_records() * 200).encode()
    corrupted = bytearray(gzip.compress(data, mtime=0))
    corrupted[11] ^= 0xFF  # flip a bit just past the 10-byte gzip header
    corrupt_file = trace_dir / "trace-7.log.gz"
    corrupt_file.write_bytes(bytes(corrupted))
    # guard: the corruption must surface as zlib.error, otherwise this test
    # degenerates into the BadGzipFile case covered above
    with pytest.raises(zlib.error):
        read_trace_file(corrupt_file)

    write_trace_log(trace_dir / "trace-8.log", _anomalous_records())
    monkeypatch.setattr(
        "inspect_ai._cli.ctl.list_discovered_servers",
        lambda: [_FakeServer(7), _FakeServer(8)],
    )
    result = cli_runner().invoke(ctl_command, ["process", "anomalies", "--json"])
    assert result.exit_code == 0
    assert [p["pid"] for p in json.loads(result.stdout)["processes"]] == [8]
    assert "could not read" in result.stderr


def test_process_anomalies_human_gates_errors_behind_all(trace_dir: Path) -> None:
    write_trace_log(trace_dir / "trace-123.log", _anomalous_records())
    result = cli_runner().invoke(ctl_command, ["process", "anomalies", "123"])
    assert result.exit_code == 0
    assert "pid 123" in result.stdout
    assert "Running Actions" in result.stdout
    assert "Cancelled Actions" in result.stdout
    assert "Error Actions" not in result.stdout

    result = cli_runner().invoke(ctl_command, ["process", "anomalies", "123", "--all"])
    assert "Error Actions" in result.stdout


def test_process_anomalies_no_running_processes(
    trace_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("inspect_ai._cli.ctl.list_discovered_servers", lambda: [])
    result = cli_runner().invoke(ctl_command, ["process", "anomalies"])
    assert result.exit_code == 0
    assert "No running inspect processes found" in result.stdout
    assert "Pass a PID" in result.stdout

    result = cli_runner().invoke(ctl_command, ["process", "anomalies", "--json"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["processes"] == []


def test_process_anomalies_filter(trace_dir: Path) -> None:
    write_trace_log(trace_dir / "trace-123.log", _anomalous_records())
    result = cli_runner().invoke(
        ctl_command, ["process", "anomalies", "123", "--filter", "bash", "--json"]
    )
    assert result.exit_code == 0
    (section,) = json.loads(result.stdout)["processes"]
    assert section["running"] == []
    assert [row["action"] for row in section["cancelled"]] == ["Subprocess"]


def test_process_anomalies_accepts_group_level_json(trace_dir: Path) -> None:
    """The group-mirrored `--json` forwards to the anomalies verb."""
    write_trace_log(trace_dir / "trace-123.log", _anomalous_records())
    result = cli_runner().invoke(ctl_command, ["process", "--json", "anomalies", "123"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["processes"][0]["pid"] == 123
