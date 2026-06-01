"""Unit tests for `inspect ctl` target resolution (id + name matching)."""

import click
import pytest

from inspect_ai._cli.ctl import _resolve_target_eval


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
