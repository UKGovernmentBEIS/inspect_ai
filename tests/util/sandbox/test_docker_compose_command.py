import pytest

from inspect_ai.util._sandbox.docker import compose as compose_module
from inspect_ai.util._sandbox.docker.compose import compose_command
from inspect_ai.util._sandbox.docker.util import ComposeProject
from inspect_ai.util._subprocess import ExecResult, SubprocessRun

OK = SubprocessRun(
    result=ExecResult(success=True, returncode=0, stdout="done", stderr=""),
    stdin_written=True,
)
ORDINARY_FAILURE = SubprocessRun(
    result=ExecResult(
        success=False, returncode=2, stdout="", stderr="cat: nope: No such file"
    ),
    stdin_written=True,
)
# The compose CLI exiting before it read its stdin (dockerd failed the exec
# attach). Its exit status and output are not a reliable signal of this: the
# CLI may report the exec's (unstarted) exit code 0 with empty output, or a
# failure of its own.
ATTACH_FAILURES = [
    SubprocessRun(
        result=ExecResult(success=True, returncode=0, stdout="", stderr=""),
        stdin_written=False,
    ),
    SubprocessRun(
        result=ExecResult(
            success=False,
            returncode=1,
            stdout="",
            stderr="error attaching stdout stream: write unix /run/docker.sock->@: broken pipe",
        ),
        stdin_written=False,
    ),
]
ATTACH_FAILED = ATTACH_FAILURES[0]

PROJECT = ComposeProject(name="test", config=None, sample_id=None, epoch=None, env=None)

EXEC = ["exec", "default", "true"]


def _stub_run_subprocess(
    monkeypatch: pytest.MonkeyPatch,
    outcomes: list[SubprocessRun[str] | Exception],
) -> list[dict[str, object]]:
    """Replace the compose module's run_subprocess() with one replaying `outcomes`.

    Each entry is returned in turn, or raised if it is an exception. Returns the
    list of keyword arguments each call received.
    """
    calls: list[dict[str, object]] = []
    remaining = list(outcomes)

    async def fake_run_subprocess(
        args: list[str], **kwargs: object
    ) -> SubprocessRun[str]:
        calls.append(kwargs)
        outcome = remaining.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(compose_module, "run_subprocess", fake_run_subprocess)
    return calls


@pytest.mark.parametrize("attach_failed", ATTACH_FAILURES)
async def test_compose_command_retries_when_cli_exits_before_reading_stdin(
    attach_failed: SubprocessRun[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A compose CLI that exits before consuming `input` is re-run, not believed.

    This is the signal dockerd's intermittent exec-attach failure leaves
    behind; the CLI's exit status and output do not identify it.
    """
    calls = _stub_run_subprocess(monkeypatch, [attach_failed, OK])
    result = await compose_command(EXEC, project=PROJECT, timeout=10, input="payload")
    assert result is OK.result
    assert len(calls) == 2
    assert all(call["input"] == "payload" for call in calls)


async def test_compose_command_returns_last_result_when_stdin_retries_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warnings: list[str] = []
    monkeypatch.setattr(compose_module.logger, "warning", warnings.append)
    calls = _stub_run_subprocess(
        monkeypatch, [ATTACH_FAILED, ATTACH_FAILED, ATTACH_FAILED, OK]
    )
    result = await compose_command(EXEC, project=PROJECT, timeout=10, input="payload")
    assert result is ATTACH_FAILED.result
    assert len(calls) == 3
    assert len(warnings) == 1
    assert "giving up after 3 attempt(s)" in warnings[0]


async def test_compose_command_stdin_retry_honours_timeout_retry_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _stub_run_subprocess(monkeypatch, [ATTACH_FAILED, OK])
    result = await compose_command(
        EXEC, project=PROJECT, timeout=10, timeout_retry=False, input="payload"
    )
    assert result is ATTACH_FAILED.result
    assert len(calls) == 1


async def test_compose_command_does_not_retry_without_a_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _stub_run_subprocess(monkeypatch, [ATTACH_FAILED, OK])
    result = await compose_command(EXEC, project=PROJECT, timeout=None, input="payload")
    assert result is ATTACH_FAILED.result
    assert len(calls) == 1


@pytest.mark.parametrize("outcome", [OK, ORDINARY_FAILURE])
async def test_compose_command_does_not_retry_when_stdin_was_written(
    outcome: SubprocessRun[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A command whose stdin was written ran; its result stands whatever it is."""
    calls = _stub_run_subprocess(monkeypatch, [outcome, OK])
    result = await compose_command(EXEC, project=PROJECT, timeout=10, input="payload")
    assert result is outcome.result
    assert len(calls) == 1


async def test_compose_command_retries_timeouts_with_a_shrinking_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _stub_run_subprocess(monkeypatch, [TimeoutError(), TimeoutError(), OK])
    result = await compose_command(EXEC, project=PROJECT, timeout=100)
    assert result is OK.result
    assert [call["timeout"] for call in calls] == [100, 60, 30]


async def test_compose_command_raises_when_timeout_retries_are_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _stub_run_subprocess(
        monkeypatch, [TimeoutError(), TimeoutError(), TimeoutError(), OK]
    )
    with pytest.raises(TimeoutError, match="timed out after 10 seconds"):
        await compose_command(EXEC, project=PROJECT, timeout=10)
    assert len(calls) == 3


async def test_compose_command_timeout_honours_timeout_retry_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _stub_run_subprocess(monkeypatch, [TimeoutError(), OK])
    with pytest.raises(TimeoutError, match="timed out after 10 seconds"):
        await compose_command(EXEC, project=PROJECT, timeout=10, timeout_retry=False)
    assert len(calls) == 1


async def test_compose_command_timeouts_and_stdin_failures_share_the_retry_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _stub_run_subprocess(
        monkeypatch, [TimeoutError(), ATTACH_FAILED, TimeoutError(), OK]
    )
    with pytest.raises(TimeoutError):
        await compose_command(EXEC, project=PROJECT, timeout=10, input="payload")
    assert len(calls) == 3
