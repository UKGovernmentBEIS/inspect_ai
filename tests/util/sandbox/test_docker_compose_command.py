import pytest

from inspect_ai.util._sandbox.docker import compose as compose_module
from inspect_ai.util._sandbox.docker.compose import compose_command
from inspect_ai.util._sandbox.docker.util import ComposeProject
from inspect_ai.util._subprocess import ExecResult

ATTACH_FAILED = ExecResult(
    success=False,
    returncode=1,
    stdout="",
    stderr="error attaching stdout stream: write unix /run/docker.sock->@: broken pipe",
)
OK = ExecResult(success=True, returncode=0, stdout="done", stderr="")
ORDINARY_FAILURE = ExecResult(
    success=False, returncode=2, stdout="", stderr="cat: nope: No such file"
)
# A command's own stderr mentioning the dockerd message mid-line, or with a
# different exit status, must not be mistaken for the CLI dying.
LOOKALIKE_FAILURES = [
    ExecResult(
        success=False,
        returncode=1,
        stdout="",
        stderr="deploy: error attaching stdout stream to logger",
    ),
    ExecResult(
        success=False,
        returncode=2,
        stdout="",
        stderr="error attaching stdout stream: something else",
    ),
]

PROJECT = ComposeProject(name="test", config=None, sample_id=None, epoch=None, env=None)

EXEC = ["exec", "default", "true"]


def _stub_subprocess(
    monkeypatch: pytest.MonkeyPatch,
    results: list[ExecResult[str] | Exception],
) -> list[dict[str, object]]:
    """Replace the compose module's subprocess() with one that replays `results`.

    Each entry is returned in turn, or raised if it is an exception. Returns the
    list of keyword arguments each call received.
    """
    calls: list[dict[str, object]] = []
    remaining = list(results)

    async def fake_subprocess(args: list[str], **kwargs: object) -> ExecResult[str]:
        calls.append(kwargs)
        outcome = remaining.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(compose_module, "subprocess", fake_subprocess)
    return calls


async def test_compose_command_retries_when_dockerd_attach_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A compose CLI killed by a failed exec attach is retried, not reported.

    The CLI exits before running the command (and before reading its stdin),
    so the caller should see the retried command's result.
    """
    calls = _stub_subprocess(monkeypatch, [ATTACH_FAILED, OK])
    result = await compose_command(EXEC, project=PROJECT, timeout=10, input="payload")
    assert result is OK
    assert len(calls) == 2
    assert all(call["input"] == "payload" for call in calls)


async def test_compose_command_returns_attach_failure_when_retries_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _stub_subprocess(
        monkeypatch, [ATTACH_FAILED, ATTACH_FAILED, ATTACH_FAILED, OK]
    )
    result = await compose_command(EXEC, project=PROJECT, timeout=10)
    assert result is ATTACH_FAILED
    assert len(calls) == 3


async def test_compose_command_attach_failure_honours_timeout_retry_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _stub_subprocess(monkeypatch, [ATTACH_FAILED, OK])
    result = await compose_command(
        EXEC, project=PROJECT, timeout=10, timeout_retry=False
    )
    assert result is ATTACH_FAILED
    assert len(calls) == 1


@pytest.mark.parametrize("failure", [ORDINARY_FAILURE, *LOOKALIKE_FAILURES])
async def test_compose_command_does_not_retry_other_failures(
    failure: ExecResult[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = _stub_subprocess(monkeypatch, [failure, OK])
    result = await compose_command(EXEC, project=PROJECT, timeout=10)
    assert result is failure
    assert len(calls) == 1


async def test_compose_command_retries_timeouts_with_a_shrinking_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _stub_subprocess(monkeypatch, [TimeoutError(), TimeoutError(), OK])
    result = await compose_command(EXEC, project=PROJECT, timeout=100)
    assert result is OK
    assert [call["timeout"] for call in calls] == [100, 60, 30]


async def test_compose_command_raises_when_timeout_retries_are_exhausted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _stub_subprocess(
        monkeypatch, [TimeoutError(), TimeoutError(), TimeoutError(), OK]
    )
    with pytest.raises(TimeoutError, match="timed out after 10 seconds"):
        await compose_command(EXEC, project=PROJECT, timeout=10)
    assert len(calls) == 3


async def test_compose_command_timeout_honours_timeout_retry_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _stub_subprocess(monkeypatch, [TimeoutError(), OK])
    with pytest.raises(TimeoutError, match="timed out after 10 seconds"):
        await compose_command(EXEC, project=PROJECT, timeout=10, timeout_retry=False)
    assert len(calls) == 1


async def test_compose_command_timeouts_and_attach_failures_share_the_retry_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _stub_subprocess(
        monkeypatch, [TimeoutError(), ATTACH_FAILED, TimeoutError(), OK]
    )
    with pytest.raises(TimeoutError):
        await compose_command(EXEC, project=PROJECT, timeout=10)
    assert len(calls) == 3
