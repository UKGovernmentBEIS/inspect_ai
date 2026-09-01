"""A dead sandbox must not look like ordinary command output.

`docker compose exec` reports "the command ran and failed" and "docker
never ran your command" identically: non-zero exit, output in the streams.
`bash()` hands stderr straight to the model, so the second case reached the
model as though it were the command's own output, and the sample ran on to
its message limit against a sandbox that could not execute anything —
logged as `status: success, error: None` (#4709).

The cases below are the real strings docker emits for each way of breaking
a container, taken from the reproduction in that issue.
"""

import pytest
from test_helpers.utils import skip_if_no_docker

from inspect_ai.util import ExecResult
from inspect_ai.util._sandbox.docker.docker import DockerSandboxEnvironment
from inspect_ai.util._sandbox.docker.failure import (
    InjectedWrapper,
    classify_exec_failure,
)
from inspect_ai.util._sandbox.docker.util import ComposeProject
from inspect_ai.util._sandbox.environment import SandboxUnavailableError

# what `exec` injects for `bash(timeout=N)`: GNU `timeout` in front of `bash`
WRAPPER = InjectedWrapper(binary="timeout", target="bash")

# --- the four ways a model wrecks its container (issue #4709 repro) --------

# `pkill -9 -f 'tail -f /dev/null'` — killed the container's main process
KILL_WORKLOAD = ExecResult(
    success=False, returncode=1, stdout="", stderr='service "default" is not running'
)

# `rm -rf /bin /usr/bin` — the binary runc cannot start is Inspect's own
# `timeout` wrapper, not anything the model named.
#
# Captured from docker 29.6.2: the CLI reports this on *stdout*, with CRLF
# line endings, and leaves stderr empty. Guarding on "output on stdout means
# a process in the container produced it" therefore misses this entirely,
# which is what the end-to-end test below caught.
RM_BIN = ExecResult(
    success=False,
    returncode=127,
    stdout=(
        "OCI runtime exec failed: exec failed: unable to start container "
        'process: exec: "timeout": executable file not found in $PATH\r\n'
    ),
    stderr="",
)

# `chmod 000 /bin/sh /bin/bash` — GNU timeout launched but could not exec
# its target. Note the capital P and that this is on stderr: the sniff in
# `DockerSandboxEnvironment.exec` looked for lowercase, in stdout, so it
# missed this case entirely.
CHMOD_SHELL = ExecResult(
    success=False,
    returncode=126,
    stdout="",
    stderr="timeout: failed to run command ‘bash’: Permission denied",
)

# deliberately NOT classified — see the exclusion test below
DAEMON_UNREACHABLE = ExecResult(
    success=False,
    returncode=1,
    stdout="",
    stderr=(
        "Cannot connect to the Docker daemon at unix:///var/run/docker.sock. "
        "Is the docker daemon running?"
    ),
)


@pytest.mark.parametrize(
    "result",
    [
        pytest.param(KILL_WORKLOAD, id="kill_workload"),
        pytest.param(RM_BIN, id="rm_bin"),
    ],
)
def test_unrunnable_sandbox_recognised(result: ExecResult[str]) -> None:
    error = classify_exec_failure(result, wrapper=WRAPPER)
    assert error is not None
    assert (result.stdout or result.stderr).strip() in str(error)


# --- must not fire on the model's own output -------------------------------
#
# The streams here are attacker-controlled: whatever the model runs writes
# them. Misreading a command's output as a dead sandbox aborts a healthy
# sample, which is strictly worse than the bug being fixed — a wasted
# sample is at least recoverable by reading the transcript.


@pytest.mark.parametrize(
    "result",
    [
        # ordinary non-zero exits, which models produce constantly
        pytest.param(
            ExecResult(success=False, returncode=1, stdout="", stderr=""),
            id="grep_no_match",
        ),
        pytest.param(
            ExecResult(
                success=False,
                returncode=127,
                stdout="",
                stderr="bash: line 1: frobnicate: command not found",
            ),
            id="model_ran_missing_command",
        ),
        # the command printed docker's own error text
        pytest.param(
            ExecResult(
                success=False,
                returncode=1,
                stdout="checking services...",
                stderr='service "default" is not running',
            ),
            id="phrase_on_stderr_but_command_produced_stdout",
        ),
        pytest.param(
            ExecResult(
                success=False,
                returncode=3,
                stdout="",
                stderr="nginx.service - A high performance web server\nis not running",
            ),
            id="phrase_not_first_line",
        ),
        # a command that succeeded ran, whatever it printed
        pytest.param(
            ExecResult(
                success=True,
                returncode=0,
                stdout="",
                stderr='service "default" is not running',
            ),
            id="exit_zero",
        ),
    ],
)
def test_model_output_is_not_a_sandbox_failure(result: ExecResult[str]) -> None:
    assert classify_exec_failure(result, wrapper=WRAPPER) is None


@pytest.mark.parametrize(
    "result",
    [
        # docker's own message is a single line and nothing else, so a
        # command that prints the phrase and then keeps going is not it
        pytest.param(
            ExecResult(
                success=False,
                returncode=1,
                stdout="",
                stderr='service "web" is not running\nretrying in 5s\n',
            ),
            id="phrase_then_more_output",
        ),
        # a docker-in-docker model driving the daemon it was given. these
        # wordings only ever come from a bare `docker exec`, never from the
        # `compose exec` we issue, so matching them would only ever misread
        # a model's own output
        pytest.param(
            ExecResult(
                success=False,
                returncode=1,
                stdout="",
                stderr="Error response from daemon: No such container: web",
            ),
            id="dind_no_such_container",
        ),
        pytest.param(
            ExecResult(
                success=False,
                returncode=1,
                stdout="",
                stderr="Error response from daemon: container 8153c is not running",
            ),
            id="dind_container_not_running",
        ),
    ],
)
def test_dind_and_multiline_output_are_not_sandbox_failures(
    result: ExecResult[str],
) -> None:
    assert classify_exec_failure(result, wrapper=WRAPPER) is None


# docker's own messages never vary: known wording as the whole line, known
# exit code, one line only. anything looser is model-producible, so shapes
# that merely resemble docker's are rejected even where the resemblance is
# close. pinned so a future loosening is deliberate.
@pytest.mark.parametrize(
    "result",
    [
        pytest.param(
            ExecResult(
                success=False,
                returncode=1,
                stdout="",
                stderr='service "x" is not running today, try again later',
            ),
            id="service_phrase_with_suffix",
        ),
        pytest.param(
            ExecResult(
                success=False,
                returncode=2,
                stdout="",
                stderr='service "x" is not running',
            ),
            id="service_phrase_wrong_exit_code",
        ),
        pytest.param(
            ExecResult(
                success=False,
                returncode=1,
                stdout=(
                    "OCI runtime exec failed: exec failed: unable to start "
                    'container process: exec: "timeout": executable file not '
                    "found in $PATH"
                ),
                stderr="",
            ),
            id="runc_not_found_wrong_exit_code",
        ),
        pytest.param(
            ExecResult(
                success=False,
                returncode=127,
                stdout=(
                    "OCI runtime exec failed: exec failed: unable to start "
                    'container process: exec: "timeout": executable file not '
                    "found in $PATH\nplus a second line"
                ),
                stderr="",
            ),
            id="runc_not_found_multiline",
        ),
        pytest.param(
            ExecResult(
                success=False,
                returncode=126,
                stdout="",
                stderr=(
                    "timeout: failed to run command ‘bash’: Permission denied\n"
                    "and some trailing chatter"
                ),
            ),
            id="wrapper_message_multiline",
        ),
    ],
)
def test_docker_like_shapes_are_rejected(result: ExecResult[str]) -> None:
    assert classify_exec_failure(result, wrapper=WRAPPER) is None


@pytest.mark.parametrize(
    "named",
    [
        pytest.param("./myscript", id="unrelated_binary"),
        # the quoted name must equal the target exactly — a substring match
        # would let a model's `timeout 5 ./bash_helper.sh` pass for `bash`
        pytest.param("/bash_helper.sh", id="target_is_substring_of_named"),
    ],
)
def test_wrapper_message_must_name_our_target(named: str) -> None:
    """A model running its own `timeout` is not our wrapper failing.

    `exec` only ever hands the wrapper the caller's own command, so a message
    quoting anything else came from the model's process, and its output
    belongs to the model.
    """
    model_ran_timeout = ExecResult(
        success=False,
        returncode=126,
        stdout="",
        stderr=f"timeout: failed to run command ‘{named}’: Permission denied",
    )
    assert classify_exec_failure(model_ran_timeout, wrapper=WRAPPER) is None


def test_accepted_collision_inner_compose_stopped_service() -> None:
    """Pins the one collision that is accepted rather than excluded.

    A model running `docker compose exec` against a stopped service of its
    own inner compose project emits exactly the wording we match, on a single
    line, sole stream. Nothing in the result tells it apart from our own
    compose exec failing, so it classifies. Accepted because the model's real
    output is embedded in the tool error and the sample continues; excluding
    the wording entirely would lose the kill_workload case.
    """
    inner_compose = ExecResult(
        success=False,
        returncode=1,
        stdout="",
        stderr='service "web" is not running',
    )
    assert isinstance(
        classify_exec_failure(inner_compose, wrapper=WRAPPER),
        SandboxUnavailableError,
    )


def test_busybox_wrapper_wording_recognised() -> None:
    """Busybox `timeout` words this differently from GNU.

    Verified on alpine:3.20 with bash installed and only `/bin/bash` chmod'ed,
    so busybox itself (and therefore `timeout`) survives to report.
    """
    busybox = ExecResult(
        success=False,
        returncode=126,
        stdout="",
        stderr="timeout: can't execute 'bash': Permission denied",
    )
    assert isinstance(classify_exec_failure(busybox, wrapper=WRAPPER), PermissionError)


def test_daemon_unreachable_is_deliberately_not_classified() -> None:
    """An unreachable daemon is left alone, on purpose.

    A docker-in-docker eval whose inner daemon is down has the model's own
    `docker ...` command emit this verbatim, and nothing in the result tells
    that apart from our own CLI failing to reach the host daemon. Since an
    unreachable host daemon is loudly visible anyway (every sample fails at
    once), the ambiguity isn't worth taking on.
    """
    assert classify_exec_failure(DAEMON_UNREACHABLE, wrapper=WRAPPER) is None


# --- exit 126 and 127 mean different things depending on who reported ------
#
# These four collide on exit code and differ only in the message's reporter
# and the binary it names. Getting the discrimination wrong in either
# direction is a regression: too broad and an ordinary permission error stops
# reaching the model (`test_bash_chmodless_script`) or a caller's typo ends
# the sample; too narrow and a wrecked container goes unnoticed again.
# Strings captured from docker 29.6.2.


@pytest.mark.parametrize(
    "result,wrapper,expected",
    [
        # runc refused to exec a file the *caller* named. self_check's
        # test_exec_permission_error requires this to stay a PermissionError
        pytest.param(
            ExecResult(
                success=False,
                returncode=126,
                stdout=(
                    "OCI runtime exec failed: exec failed: unable to start "
                    'container process: exec: "/etc/passwd": permission denied'
                ),
                stderr="",
            ),
            None,
            PermissionError,
            id="runc_refused_caller_binary",
        ),
        # a *shell* reporting the model's own script is not executable. this
        # is ordinary output the model needs to see, not an error
        pytest.param(
            ExecResult(
                success=False,
                returncode=126,
                stdout="",
                stderr="bash: line 1: /tmp/myscript: Permission denied",
            ),
            WRAPPER,
            type(None),
            id="shell_refused_model_script",
        ),
        # same, on stdout. the old sniff (126 + lowercase "permission denied"
        # in stdout, any reporter) turned this into a PermissionError; now it
        # is ordinary output unless runc or our wrapper reported it. pins the
        # narrowing so it stays deliberate.
        pytest.param(
            ExecResult(
                success=False,
                returncode=126,
                stdout="sh: 1: ./run.sh: permission denied",
                stderr="",
            ),
            WRAPPER,
            type(None),
            id="old_sniff_shape_no_longer_matches",
        ),
        # the binary runc cannot find is one the caller named — their
        # problem, and an ordinary result as it has always been
        pytest.param(
            ExecResult(
                success=False,
                returncode=127,
                stdout=(
                    "OCI runtime exec failed: exec failed: unable to start "
                    'container process: exec: "nosuchbinary123": executable '
                    "file not found in $PATH"
                ),
                stderr="",
            ),
            WRAPPER,
            type(None),
            id="runc_missing_caller_binary",
        ),
        # the binary runc cannot find is the wrapper *we* injected, so the
        # provider could not reach the caller's command
        pytest.param(
            RM_BIN, WRAPPER, SandboxUnavailableError, id="runc_missing_wrapper"
        ),
        # our wrapper launched but could not exec the shell
        pytest.param(CHMOD_SHELL, WRAPPER, PermissionError, id="wrapper_refused_shell"),
    ],
)
def test_launch_failures_discriminated_by_reporter(
    result: ExecResult[str], wrapper: InjectedWrapper | None, expected: type
) -> None:
    assert isinstance(classify_exec_failure(result, wrapper=wrapper), expected)


# --- the provider raises rather than returning -----------------------------


def _sandbox() -> DockerSandboxEnvironment:
    return DockerSandboxEnvironment(
        service="default",
        project=ComposeProject(
            name="test", config=None, sample_id=1, epoch=1, env=None
        ),
        working_dir="/",
    )


FAKE_DIAGNOSTICS = 'Container diagnostics for service "default":\n(fake diagnostics)'


def _stub_dead_container_probes(
    monkeypatch: pytest.MonkeyPatch, service_dead: bool
) -> None:
    """Stub the docker probes the dead-container paths run.

    These tests must never touch a real docker daemon.
    """

    async def fake_service_dead(*args: object, **kwargs: object) -> bool:
        return service_dead

    async def fake_diagnostics(*args: object, **kwargs: object) -> str:
        return FAKE_DIAGNOSTICS

    monkeypatch.setattr(
        "inspect_ai.util._sandbox.docker.docker.service_dead", fake_service_dead
    )
    monkeypatch.setattr(
        "inspect_ai.util._sandbox.docker.docker.sandbox_unavailable_diagnostics",
        fake_diagnostics,
    )


def _capture_warnings(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Record warnings logged by the docker module.

    Not caplog: once any eval has run in the process, inspect's init_logger
    sets propagate=False on the inspect_ai logger, so records never reach
    caplog's root handler (passes file-only, fails in a full-suite run).
    """
    warnings: list[str] = []
    monkeypatch.setattr(
        "inspect_ai.util._sandbox.docker.docker.logger.warning",
        lambda msg, *args, **kwargs: warnings.append(str(msg)),
    )
    return warnings


async def _exec_returning(
    monkeypatch: pytest.MonkeyPatch,
    result: ExecResult[str],
    timeout: int | None = 30,
    service_dead: bool = False,
) -> ExecResult[str]:
    async def fake_compose_exec(*args: object, **kwargs: object) -> ExecResult[str]:
        return result

    monkeypatch.setattr(
        "inspect_ai.util._sandbox.docker.docker.compose_exec", fake_compose_exec
    )
    _stub_dead_container_probes(monkeypatch, service_dead)
    # timeout=None is `bash()`'s default, and is what decides whether a
    # wrapper is injected ahead of the command
    return await _sandbox().exec(["bash", "-c", "echo hi"], timeout=timeout)


@pytest.mark.parametrize(
    "result",
    [
        pytest.param(KILL_WORKLOAD, id="kill_workload"),
        pytest.param(RM_BIN, id="rm_bin"),
    ],
)
async def test_exec_raises_when_docker_could_not_run_the_command(
    monkeypatch: pytest.MonkeyPatch,
    result: ExecResult[str],
) -> None:
    warnings = _capture_warnings(monkeypatch)
    with pytest.raises(SandboxUnavailableError):
        await _exec_returning(monkeypatch, result)
    # a dead container logs evidence of why it died (#264). logged, not
    # embedded in the error: error text reaches the model as tool output
    assert FAKE_DIAGNOSTICS in warnings


async def test_exec_raises_permission_error_for_unlaunchable_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(PermissionError):
        await _exec_returning(monkeypatch, CHMOD_SHELL)


async def test_exec_returns_daemon_unreachable_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert await _exec_returning(monkeypatch, DAEMON_UNREACHABLE) == DAEMON_UNREACHABLE


async def test_exec_returns_ordinary_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failed = ExecResult(success=False, returncode=1, stdout="", stderr="")
    assert await _exec_returning(monkeypatch, failed) == failed


# --- a container dying mid-command produces a silent failure ---------------
#
# docker reports nothing when the container dies while the command runs:
# signal-death exit code, both streams empty. that is also the shape of a
# command killed inside a healthy container, so the two are told apart by
# asking compose whether the container is positively dead (#264). ordinary
# silent failures (`grep -q` without a match) have small exit codes and
# never pay the check.


async def test_silent_signal_death_with_dead_container_raises_and_logs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    warnings = _capture_warnings(monkeypatch)
    died_mid_command = ExecResult(success=False, returncode=137, stdout="", stderr="")
    with pytest.raises(SandboxUnavailableError) as excinfo:
        await _exec_returning(monkeypatch, died_mid_command, service_dead=True)
    assert "exited with code 137" in str(excinfo.value)
    assert FAKE_DIAGNOSTICS in warnings


async def test_silent_small_exit_code_never_checks_the_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # even against a genuinely dead container, a silent small-code failure is
    # returned as-is: paying a docker CLI call on every `grep -q` miss is the
    # cost this gate exists to avoid, and the next exec raises anyway
    grep_no_match = ExecResult(success=False, returncode=1, stdout="", stderr="")
    assert (
        await _exec_returning(monkeypatch, grep_no_match, service_dead=True)
        == grep_no_match
    )


async def test_silent_signal_death_in_running_container_is_an_ordinary_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # e.g. the kernel OOM-killed the command but the container survived
    killed_command = ExecResult(success=False, returncode=137, stdout="", stderr="")
    assert (
        await _exec_returning(monkeypatch, killed_command, service_dead=False)
        == killed_command
    )


async def test_diagnostics_logged_once_per_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # a dead sandbox fails every subsequent exec; the post-mortem is logged
    # for the first only
    async def fake_compose_exec(*args: object, **kwargs: object) -> ExecResult[str]:
        return KILL_WORKLOAD

    warnings = _capture_warnings(monkeypatch)
    monkeypatch.setattr(
        "inspect_ai.util._sandbox.docker.docker.compose_exec", fake_compose_exec
    )
    _stub_dead_container_probes(monkeypatch, service_dead=True)
    sandbox = _sandbox()
    for _ in range(2):
        with pytest.raises(SandboxUnavailableError):
            await sandbox.exec(["echo", "hi"], timeout=30)
    assert warnings == [FAKE_DIAGNOSTICS]


async def test_silent_success_never_checks_the_container(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # a command that succeeded ran, whatever it printed; the dead check
    # must not fire (it costs a docker CLI call per exec)
    ok = ExecResult(success=True, returncode=0, stdout="", stderr="")

    async def fake_compose_exec(*args: object, **kwargs: object) -> ExecResult[str]:
        return ok

    async def exploding_check(*args: object, **kwargs: object) -> bool:
        raise AssertionError("service_dead must not be called for successful execs")

    monkeypatch.setattr(
        "inspect_ai.util._sandbox.docker.docker.compose_exec", fake_compose_exec
    )
    monkeypatch.setattr(
        "inspect_ai.util._sandbox.docker.docker.service_dead", exploding_check
    )
    assert await _sandbox().exec(["true"], timeout=30) == ok


async def test_no_wrapper_leaves_runc_launch_failures_unclassified(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without an injected wrapper, the runc cases are not recognised.

    `bash()` defaults to `timeout=None`, and with no wrapper the binary runc
    names is the caller's own (`bash`), which is indistinguishable from a
    caller asking for a binary that was never there. Both of the runc-reported
    cases in #4709 therefore behave exactly as they did before the fix in that
    configuration. Recognising them anyway would mean raising whenever any
    exec'd binary is absent, which breaks callers that run a binary precisely
    to find out whether it exists (`sandbox_with(on_path=True)`,
    `exec(["which", ...])`).
    """
    no_wrapper_rm_bin = ExecResult(
        success=False,
        returncode=127,
        stdout=(
            "OCI runtime exec failed: exec failed: unable to start container "
            'process: exec: "bash": executable file not found in $PATH\r\n'
        ),
        stderr="",
    )
    assert classify_exec_failure(no_wrapper_rm_bin, wrapper=None) is None
    assert (
        await _exec_returning(monkeypatch, no_wrapper_rm_bin, timeout=None)
        == no_wrapper_rm_bin
    )


async def test_empty_cmd_with_timeout_does_not_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # a caller error, but it returned an ExecResult before this change and
    # must not become an IndexError while building the wrapper
    result = ExecResult(success=False, returncode=1, stdout="", stderr="usage: ...")

    async def fake_compose_exec(*args: object, **kwargs: object) -> ExecResult[str]:
        return result

    monkeypatch.setattr(
        "inspect_ai.util._sandbox.docker.docker.compose_exec", fake_compose_exec
    )
    assert await _sandbox().exec([], timeout=30) == result


# --- end to end, against a container actually broken by the model ----------
#
# The tests above pin the classification; this one is the issue's own
# reproduction, and the only check here that would have failed before the
# fix without referring to anything the fix introduced. Slow, and needs
# docker, so it is not what CI relies on.


@skip_if_no_docker
@pytest.mark.slow
@pytest.mark.parametrize(
    "destroy",
    [
        pytest.param(
            "pkill -9 -f 'tail -f /dev/null'; echo killed", id="kill_workload"
        ),
        pytest.param("rm -rf /bin /usr/bin; echo wiped", id="rm_bin"),
    ],
)
def test_broken_sandbox_is_reported_as_a_tool_error(destroy: str) -> None:
    from inspect_ai import Task, eval
    from inspect_ai.agent import react
    from inspect_ai.dataset import Sample
    from inspect_ai.model import ChatMessageTool, ModelOutput, get_model
    from inspect_ai.tool import bash

    def tool_call(command: str) -> ModelOutput:
        return ModelOutput.for_tool_call(
            model="mockllm/model",
            tool_name="bash",
            tool_arguments={"command": command},
        )

    log = eval(
        Task(
            dataset=[Sample(input="do stuff", target="done")],
            solver=react(tools=[bash(timeout=30)]),
            sandbox="docker",
        ),
        model=get_model(
            "mockllm/model",
            custom_outputs=[tool_call(destroy)]
            + [tool_call(f"echo step-{i}") for i in range(8)]
            + [
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="submit",
                    tool_arguments={"answer": "done"},
                )
            ],
        ),
        message_limit=40,
        display="none",
        retry_on_error=0,
    )[0]

    assert log.samples
    sample = log.samples[0]
    tool_messages = [m for m in sample.messages if isinstance(m, ChatMessageTool)]

    # every call after the destroy is reported as a failure rather than as
    # command output. before the fix each of these had error=None and carried
    # docker's own message as though the command had produced it, which is
    # what made a dead sandbox indistinguishable from a working one.
    assert len(tool_messages) > 1
    assert all(
        m.error is not None and m.error.type == "sandbox_unavailable"
        for m in tool_messages[1:]
    )

    # the sample itself is untouched: whether an unusable sandbox should end
    # a sample is a separate decision (#4709) and is not taken here
    assert sample.error is None


@skip_if_no_docker
@pytest.mark.slow
def test_non_tool_callers_get_a_raise_not_a_failed_result() -> None:
    """Outside the tool loop the sample does end, and that is a real change.

    `call_tool` turns SandboxUnavailableError into a tool error, but nothing
    else does. A scorer, solver or setup script execing into a container the
    model killed now gets an exception where it previously got an ExecResult
    carrying docker's message, and that ends the sample. (Whether it also ends
    the *run* is `fail_on_error`'s business, which defaults to True; this test
    sets it False to isolate the sample-level effect.) Pinned here because the
    tool-loop behaviour above reads as though nothing else changed.
    """
    from inspect_ai import Task, eval
    from inspect_ai.dataset import Sample
    from inspect_ai.model import get_model
    from inspect_ai.scorer import Score, Target, accuracy, scorer
    from inspect_ai.solver import Generate, TaskState, solver
    from inspect_ai.util import sandbox

    @solver
    def kill_the_sandbox():
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            await sandbox().exec(
                ["bash", "-c", "pkill -9 -f 'tail -f /dev/null'; echo killed"],
                timeout=30,
            )
            return state

        return solve

    @scorer(metrics=[accuracy()])
    def exec_scorer():
        async def score(state: TaskState, target: Target) -> Score:
            result = await sandbox().exec(["echo", "scoring"], timeout=30)
            return Score(value="C" if result.success else "I")

        return score

    log = eval(
        Task(
            dataset=[Sample(input="x", target="done")],
            solver=kill_the_sandbox(),
            scorer=exec_scorer(),
            sandbox="docker",
        ),
        model=get_model("mockllm/model"),
        display="none",
        retry_on_error=0,
        fail_on_error=False,
    )[0]

    assert log.samples
    assert log.samples[0].error is not None
    assert "SandboxUnavailable" in str(log.samples[0].error.message)


@skip_if_no_docker
@pytest.mark.slow
def test_unlaunchable_shell_reaches_the_model_as_a_tool_error() -> None:
    """The container survives `chmod 000 /bin/sh`, so the sample does too.

    `read_file`/`write_file` go through `compose cp` and still work, as do
    execs of anything that isn't the shell. The model is told the call
    failed instead of the sample being ended.
    """
    from inspect_ai import Task, eval
    from inspect_ai.agent import react
    from inspect_ai.dataset import Sample
    from inspect_ai.model import ChatMessageTool, ModelOutput, get_model
    from inspect_ai.tool import bash

    def tool_call(command: str) -> ModelOutput:
        return ModelOutput.for_tool_call(
            model="mockllm/model",
            tool_name="bash",
            tool_arguments={"command": command},
        )

    log = eval(
        Task(
            dataset=[Sample(input="do stuff", target="done")],
            solver=react(tools=[bash(timeout=30)]),
            sandbox="docker",
        ),
        model=get_model(
            "mockllm/model",
            custom_outputs=[
                tool_call("chmod 000 /bin/sh /bin/bash; echo chmodded"),
                tool_call("echo step-0"),
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="submit",
                    tool_arguments={"answer": "done"},
                ),
            ],
        ),
        message_limit=40,
        display="none",
        retry_on_error=0,
    )[0]

    assert log.samples
    sample = log.samples[0]
    tool_messages = [m for m in sample.messages if isinstance(m, ChatMessageTool)]
    # the call after the chmod: previously error=None, with GNU timeout's
    # "Permission denied" delivered as though it were command output
    assert tool_messages[1].error is not None
    assert tool_messages[1].error.type == "permission"
