import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from textwrap import dedent
from typing import Any, Awaitable, Callable, Sequence, cast
from unittest.mock import patch

import anyio
import pytest
from pydantic import JsonValue
from test_helpers.utils import skip_if_no_docker

from inspect_ai import Task, eval
from inspect_ai._util.error import PrerequisiteError
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.util import sandbox
from inspect_ai.util._background import background
from inspect_ai.util._sandbox._framework_directory import (
    _SCRIPT,
    _SHELL,
    _USER_MISMATCH_MARKER,
    _VERIFIED_MARKER,
    _VIOLATION_MARKER,
    FrameworkDirectoryError,
)
from inspect_ai.util._sandbox.environment import SandboxEnvironment
from inspect_ai.util._sandbox.limits import OutputLimitExceededError
from inspect_ai.util._sandbox.service import (
    SERVICE_REQUEST_READ_OUTPUT_LIMIT,
    SERVICES_DIR,
    SandboxService,
    is_sandbox_service_command,
    sandbox_service,
)
from inspect_ai.util._subprocess import ExecResult


@pytest.mark.slow
@skip_if_no_docker
@pytest.mark.parametrize(
    "user, handle_requests",
    [("root", True), ("nonroot", True), (None, True), (None, False)],
)
def test_sandbox_service(user: str | None, handle_requests: bool):
    store = _eval_service_solver(math_service(user, handle_requests), COMPOSE)
    assert store.get("result") == 8


COMPOSE = str(Path(__file__).parent / "compose.sandbox-service.yaml")
"""Compose file whose default user is root, with a `nonroot` user available."""


@solver
def math_service(
    user: str | None,
    handle_requests: bool,
    prepare: Callable[[], Awaitable[None]] | None = None,
) -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        if prepare is not None:
            await prepare()

        # generate a script that will exercise the service and copy it to the sandbox
        run_script = "run.py"
        run_script_code = dedent("""
        import asyncio

        async def run():
            # wait for service to come up
            import os
            service_dir = "/var/tmp/sandbox-services/math_service"
            while not os.path.exists(f"{service_dir}/math_service.py"):
                await asyncio.sleep(0.1)

            # import service
            import sys
            sys.path.append(service_dir)
            from math_service import call_math_service, call_math_service_async

            # call service
            result = await call_math_service_async("add", x=10, y=5)
            result = call_math_service("subtract", x=result, y=7)
            await call_math_service_async("finish", result=result)

        asyncio.run(run())
        """)
        # run the math service in the background
        background(run_math_service, state, user, handle_requests)

        # run a script in the sandbox that talks to the service
        await sandbox().write_file(run_script, run_script_code)
        script_error = ""
        try:
            result = await sandbox().exec(["python3", run_script], user=user)
            if not result.success:
                script_error = f"Error running script '{run_script}': {result.stderr}"
        except Exception as e:
            script_error = f"Exception in script: {str(e)}"
        if script_error:
            print(script_error)

        return state

    return solve


async def run_math_service(
    state: TaskState, user: str | None, handle_requests: bool = True
) -> None:
    finished = False

    async def add(x: int, y: int) -> int:
        return x + y

    async def subtract(x: int, y: int) -> int:
        return x - y

    async def finish(result: int) -> None:
        nonlocal finished
        finished = True
        state.store.set("result", result)

    if handle_requests:
        await sandbox_service(
            name="math_service",
            methods=[add, subtract, finish],
            until=lambda: finished,
            sandbox=sandbox(),
            user=user,
        )
    else:
        handle_service_requests = await sandbox_service(
            name="math_service",
            methods=[add, subtract, finish],
            until=lambda: finished,
            sandbox=sandbox(),
            user=user,
            handle_requests=False,
        )
        while not finished:
            await handle_service_requests()
            await anyio.sleep(0.1)


@pytest.mark.slow
@skip_if_no_docker
def test_sandbox_service_rejects_malicious_queue_names_and_ids() -> None:
    log = eval(
        Task(solver=sandbox_service_security_regression()),
        model="mockllm/model",
        sandbox=(
            "docker",
            str(Path(__file__).parent / "compose.sandbox-service.yaml"),
        ),
    )[0]
    assert log.status == "success"
    assert log.samples
    sample = log.samples[0]
    assert sample.store.get("shell_marker_created") is False
    assert sample.store.get("escaped_response_created") is False
    assert sample.store.get("invalid_filename_removed") is True
    assert sample.store.get("response_id") == "safe-request"


@solver
def sandbox_service_security_regression() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        async def noop() -> None:
            return None

        handle_requests = await sandbox_service(
            name="security_service",
            methods={"noop": noop},
            until=lambda: False,
            sandbox=sandbox(),
            handle_requests=False,
        )

        service_dir = f"{SERVICES_DIR}/security_service"
        requests_dir = f"{service_dir}/requests"
        responses_dir = f"{service_dir}/responses"
        invalid_filename = "x; touch sandbox-service-marker; .json"
        invalid_request = f"{requests_dir}/{invalid_filename}"
        escaped_response = "/tmp/sandbox-service-response.json"

        await sandbox().write_file(invalid_request, "{}")
        await sandbox().write_file(
            f"{requests_dir}/safe-request.json",
            json.dumps(
                {
                    "id": "/tmp/sandbox-service-response",
                    "method": "noop",
                    "params": {},
                }
            ),
        )

        await handle_requests()

        shell_marker = await sandbox().exec(["test", "-e", "sandbox-service-marker"])
        escaped = await sandbox().exec(["test", "-e", escaped_response])
        invalid_exists = await sandbox().exec(["test", "-e", invalid_request])
        response = json.loads(
            await sandbox().read_file(f"{responses_dir}/safe-request.json")
        )

        state.store.set("shell_marker_created", shell_marker.success)
        state.store.set("escaped_response_created", escaped.success)
        state.store.set("invalid_filename_removed", not invalid_exists.success)
        state.store.set("response_id", response["id"])
        return state

    return solve


@dataclass
class FakeExecResult:
    success: bool = True
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


_VERIFIED = FakeExecResult(stderr=f"{_VERIFIED_MARKER}\n")
"""A framework-directory helper result: verified, nothing else to report."""

_USER_MISMATCH = FakeExecResult(
    success=False,
    returncode=6,
    stderr=f"{_USER_MISMATCH_MARKER}: running as uid 1000, expected uid 0\n",
)


def _violation(message: str) -> FakeExecResult:
    return FakeExecResult(
        success=False, returncode=3, stderr=f"{_VIOLATION_MARKER}: {message}\n"
    )


@dataclass(frozen=True)
class HelperCall:
    """A framework-directory helper invocation, decoded from its argv."""

    path: str
    user: str | None
    expected_uid: str
    create: bool
    shared: bool
    cmd: tuple[str, ...]
    """The wrapped command (empty when only ensuring the directory)."""


def _decode_helper(cmd: list[str], user: str | None) -> HelperCall | None:
    """Decode a helper invocation; None for any other command."""
    if cmd[:3] != [_SHELL, "-c", _SCRIPT]:
        return None
    _, expected_uid, create, _repair, shared, parent, leaf, *wrapped = cmd[3:]
    return HelperCall(
        path=f"{parent.rstrip('/')}/{leaf}",
        user=user,
        expected_uid=expected_uid,
        create=create == "1",
        shared=shared == "1",
        cmd=tuple(wrapped),
    )


def _assert_no_shell_interpolation(calls: list[list[str]]) -> None:
    """Any shell invocation must be the fixed helper script; data travels in argv."""
    for cmd in calls:
        if len(cmd) > 2 and cmd[1] == "-c":
            assert cmd[:3] == [_SHELL, "-c", _SCRIPT], cmd


HelperPolicy = Callable[[HelperCall], FakeExecResult]


@dataclass
class _StartSandbox:
    """Fake sandbox for `start()`: every command must be a helper invocation.

    `policy` decides each helper call's result (verified by default); the decoded
    calls are recorded in `calls` and the raw exec arguments in `execs`.
    """

    policy: HelperPolicy = lambda call: _VERIFIED
    calls: list[HelperCall] = field(default_factory=list)
    execs: list[dict[str, Any]] = field(default_factory=list)

    async def exec(
        self,
        cmd: list[str],
        *,
        user: str | None = None,
        input: str | None = None,
        timeout: int | None = None,
        concurrency: bool = True,
    ) -> ExecResult[str]:
        self.execs.append(
            {"cmd": cmd, "user": user, "input": input, "concurrency": concurrency}
        )
        call = _decode_helper(cmd, user)
        assert call is not None, f"start() ran a command outside the helper: {cmd}"
        self.calls.append(call)
        return cast(ExecResult[str], self.policy(call))


def _service(fake: object, **kwargs: Any) -> SandboxService:
    return SandboxService(sandbox=cast(SandboxEnvironment, fake), **kwargs)


async def test_every_start_command_is_hidden_from_the_transcript() -> None:
    """Service housekeeping is not a transcript event, the shared-parent probe included."""
    fake = _StartSandbox()
    await _service(fake, name="svc", user="agent").start()
    assert all(is_sandbox_service_command(e["cmd"]) for e in fake.execs)
    assert not is_sandbox_service_command(["ls", "-la", "/var/tmp"])
    assert not is_sandbox_service_command(["stat", "/var/tmp", "/etc"])


async def test_start_prepares_every_directory_through_the_helper() -> None:
    fake = _StartSandbox()
    service = _service(fake, name="svc", user="agent")

    await service.start()

    svc = f"{SERVICES_DIR}/svc"
    reset = ("rm", "-rf", "--", "requests", "responses")
    assert [(c.path, c.user, c.create, c.shared, c.cmd) for c in fake.calls] == [
        (SERVICES_DIR, "root", True, True, ()),
        (svc, "agent", True, False, ()),
        (svc, "agent", False, False, reset),
        (f"{svc}/requests", "agent", True, False, ()),
        (f"{svc}/responses", "agent", True, False, ()),
        (svc, "agent", False, False, ("tee", "--", "svc.py")),
    ]
    # the shared parent is prepared as root, and that must really be uid 0
    assert fake.calls[0].expected_uid == "0"
    assert all(e["concurrency"] is False for e in fake.execs)
    assert "def call_svc(" in (fake.execs[-1]["input"] or "")
    assert service._requests_dir == f"{svc}/requests"
    assert service._responses_dir == f"{svc}/responses"


async def test_start_with_instance_verifies_name_before_instance() -> None:
    """<name> must itself be a private directory, not a helper-made 0755 parent."""
    fake = _StartSandbox()
    service = _service(fake, name="multi", user="agent", instance="inst1")

    await service.start()

    inst = f"{SERVICES_DIR}/multi/inst1"
    assert [c.path for c in fake.calls if c.create] == [
        SERVICES_DIR,
        f"{SERVICES_DIR}/multi",
        inst,
        f"{inst}/requests",
        f"{inst}/responses",
    ]
    assert [c.path for c in fake.calls if c.cmd] == [inst, inst]


def _raise_no_root() -> FakeExecResult:
    raise PermissionError("this provider cannot exec as root")


@pytest.mark.parametrize(
    "root_failure",
    [
        pytest.param(lambda: _USER_MISMATCH, id="uid-mismatch-verdict"),
        pytest.param(_raise_no_root, id="provider-raises"),
    ],
)
async def test_start_prepares_shared_parent_as_service_user_when_root_unavailable(
    root_failure: Callable[[], FakeExecResult],
) -> None:
    def policy(call: HelperCall) -> FakeExecResult:
        return root_failure() if call.user == "root" else _VERIFIED

    fake = _StartSandbox(policy)
    service = _service(fake, name="svc", user="agent")

    await service.start()

    assert [(c.path, c.user, c.shared) for c in fake.calls[:3]] == [
        (SERVICES_DIR, "root", True),
        (SERVICES_DIR, "agent", True),
        (f"{SERVICES_DIR}/svc", "agent", False),
    ]
    assert fake.calls[1].expected_uid == ""


async def test_start_does_not_retry_shared_parent_after_a_violation() -> None:
    fake = _StartSandbox(
        lambda call: _violation(f"{SERVICES_DIR} is owned by uid 1000, expected uid 0")
    )
    service = _service(fake, name="svc", user="agent")

    with pytest.raises(FrameworkDirectoryError, match="owned by uid 1000"):
        await service.start()

    assert [(c.path, c.user) for c in fake.calls] == [(SERVICES_DIR, "root")]


async def test_start_propagates_service_dir_violation_and_writes_nothing() -> None:
    svc = f"{SERVICES_DIR}/squatted"

    def policy(call: HelperCall) -> FakeExecResult:
        if call.path == svc:
            return _violation(f"{svc} is owned by uid 1000, expected uid 1001")
        return _VERIFIED

    fake = _StartSandbox(policy)
    service = _service(fake, name="squatted", user="agent")

    with pytest.raises(FrameworkDirectoryError) as excinfo:
        await service.start()

    assert not isinstance(excinfo.value, PrerequisiteError)
    assert svc in str(excinfo.value)
    assert "owned by uid 1000, expected uid 1001" in str(excinfo.value)
    assert [c.path for c in fake.calls] == [SERVICES_DIR, svc]
    assert not service._requests_dir and not service._responses_dir


async def test_start_aborts_when_queue_reset_fails() -> None:
    def policy(call: HelperCall) -> FakeExecResult:
        if call.cmd[:2] == ("rm", "-rf"):
            return FakeExecResult(
                success=False,
                returncode=1,
                stderr=f"{_VERIFIED_MARKER}\nrm: cannot remove 'requests': Permission denied\n",
            )
        return _VERIFIED

    fake = _StartSandbox(policy)
    service = _service(fake, name="svc", user="agent")

    with pytest.raises(RuntimeError, match="Permission denied"):
        await service.start()

    assert len(fake.calls) == 3
    assert fake.calls[-1].cmd[:2] == ("rm", "-rf")
    assert not service._requests_dir and not service._responses_dir


@dataclass
class _RequestReadSandbox:
    """Fake sandbox for exercising the request-read failure paths of _handle_request.

    - ``cat``: raises ``OutputLimitExceededError`` if ``raise_on_cat`` (the k8s
      style), otherwise returns ``cat_stdout`` (use a non-JSON tail to model a
      provider that silently truncates an oversized read, e.g. docker/local).
    - ``wc -c``: returns ``file_size`` (the on-disk size check).
    - queue listing (``find``): returns ``list_stdout`` (NUL-delimited paths).
    - ``tee`` (run through the framework-directory helper, decoded into
      ``helper_calls``): recorded in ``writes`` under the file's full path.
    - ``rm``: recorded in ``removed``.
    """

    cat_stdout: str = ""
    raise_on_cat: bool = False
    file_size: int = 0
    list_stdout: str = ""
    limit_str: str = "10 MiB"
    writes: dict[str, str] = field(default_factory=dict)
    removed: list[str] = field(default_factory=list)
    calls: list[list[str]] = field(default_factory=list)
    helper_calls: list[HelperCall] = field(default_factory=list)

    async def exec(
        self,
        cmd: list[str],
        *,
        user: str | None = None,
        input: str | None = None,
        timeout: int | None = None,
        concurrency: bool = True,
    ) -> ExecResult[str]:
        self.calls.append(cmd)
        call = _decode_helper(cmd, user)
        if call is not None:
            self.helper_calls.append(call)
            if call.cmd[:1] == ("tee",):
                self.writes[f"{call.path}/{call.cmd[-1]}"] = input or ""
            return cast(ExecResult[str], _VERIFIED)
        if cmd[0] == "find":
            return cast(ExecResult[str], FakeExecResult(stdout=self.list_stdout))
        if cmd[0] == "cat":
            if self.raise_on_cat:
                raise OutputLimitExceededError(
                    limit_str=self.limit_str, truncated_output=None
                )
            return cast(ExecResult[str], FakeExecResult(stdout=self.cat_stdout))
        if cmd[0] == "wc":
            return cast(
                ExecResult[str],
                FakeExecResult(stdout=f"{self.file_size} {cmd[-1]}\n"),
            )
        if cmd[0] == "rm":
            self.removed.append(cmd[-1])
            return cast(ExecResult[str], FakeExecResult())
        return cast(ExecResult[str], FakeExecResult())


def _service_with_dirs(
    fake: object, name: str = "bridge_model_service"
) -> SandboxService:
    service = SandboxService(name=name, sandbox=cast(SandboxEnvironment, fake))
    service._requests_dir = f"{SERVICES_DIR}/{name}/requests"
    service._responses_dir = f"{SERVICES_DIR}/{name}/responses"
    return service


async def test_handle_request_oversized_raise_writes_error_and_removes_file() -> None:
    """A provider that RAISES on overflow (k8s) -> error response + removal."""
    request_id = "11111111-2222-3333-4444-555555555555"
    fake = _RequestReadSandbox(raise_on_cat=True)
    service = _service_with_dirs(fake)
    request_file = f"{service._requests_dir}/{request_id}.json"

    await service._handle_request(request_file)

    response_path = f"{service._responses_dir}/{request_id}.json"
    assert response_path in fake.writes
    response = json.loads(fake.writes[response_path])
    assert response["id"] == request_id
    assert response["result"] is None
    assert "10 MiB" in response["error"]
    assert request_file in fake.removed
    assert fake.calls[0] == ["cat", "--", request_file]
    _assert_no_shell_interpolation(fake.calls)


async def test_write_response_goes_through_the_verified_responses_dir() -> None:
    fake = _RequestReadSandbox()
    service = _service_with_dirs(fake)
    request_file = f"{service._requests_dir}/req-1.json"

    await service._write_response(request_file, "req-1", {"ok": True})

    (call,) = fake.helper_calls
    assert (call.path, call.user, call.cmd) == (
        service._responses_dir,
        None,
        ("tee", "--", "req-1.json"),
    )
    assert json.loads(fake.writes[f"{service._responses_dir}/req-1.json"]) == {
        "id": "req-1",
        "result": {"ok": True},
        "error": None,
    }
    assert fake.removed == [request_file]
    _assert_no_shell_interpolation(fake.calls)


async def test_handle_request_oversized_truncated_writes_error_and_removes_file() -> (
    None
):
    """A provider that silently TRUNCATES on overflow (docker/local) -> graceful.

    The truncated tail fails to parse; the on-disk size (> read limit) reveals it
    as oversized rather than a partial write, so it is discarded with an error
    response instead of being retried forever.
    """
    request_id = "22222222-3333-4444-5555-666666666666"
    fake = _RequestReadSandbox(
        raise_on_cat=False,
        cat_stdout="truncated-tail-that-is-not-valid-json}]}",
        file_size=SERVICE_REQUEST_READ_OUTPUT_LIMIT + 1,
    )
    service = _service_with_dirs(fake)
    request_file = f"{service._requests_dir}/{request_id}.json"

    await service._handle_request(request_file)

    response_path = f"{service._responses_dir}/{request_id}.json"
    assert response_path in fake.writes
    response = json.loads(fake.writes[response_path])
    assert response["id"] == request_id
    assert response["result"] is None
    assert request_file in fake.removed
    assert ["wc", "-c", "--", request_file] in fake.calls


async def test_handle_request_incomplete_write_is_retried() -> None:
    """Incomplete-write file is retried; the warning logs metadata, not the payload."""
    secret = "SENSITIVE-PAYLOAD-DO-NOT-LOG"
    fake = _RequestReadSandbox(
        raise_on_cat=False,
        cat_stdout=f'{{"id": "x", "params": {{"k": "{secret}"',  # partial JSON
        file_size=64,  # well under the read limit -> not an oversized read
    )
    service = _service_with_dirs(fake)
    request_file = f"{service._requests_dir}/incomplete.json"

    # patch the module logger so the assertion doesn't depend on log propagation
    with patch("inspect_ai.util._sandbox.service.logger") as mock_logger:
        await service._handle_request(request_file)

    # no response written and the file left in place for the next poll
    assert fake.writes == {}
    assert fake.removed == []
    # a warning was logged with metadata but never the payload itself
    logged = " ".join(str(c.args[0]) for c in mock_logger.warning.call_args_list)
    assert request_file in logged
    assert secret not in logged


async def test_handle_request_oversized_uses_filename_id() -> None:
    """Oversized requests use the validated filename, not partial JSON, as the id."""
    fake = _RequestReadSandbox(raise_on_cat=True)
    service = _service_with_dirs(fake)
    request_file = f"{service._requests_dir}/orphan.json"

    await service._handle_request(request_file)

    response_path = f"{service._responses_dir}/orphan.json"
    response = json.loads(fake.writes[response_path])
    assert response["id"] == "orphan"
    assert response["result"] is None
    assert request_file in fake.removed


async def test_handle_request_valid_call_uses_argv() -> None:
    request_id = "safe-request_1.0"
    request_data = {
        "id": request_id,
        "method": "add",
        "params": {"x": 2, "y": 3},
    }
    fake = _RequestReadSandbox(cat_stdout=json.dumps(request_data))
    service = _service_with_dirs(fake)

    async def add(x: int, y: int) -> int:
        return x + y

    service.add_method("add", add)
    request_file = f"{service._requests_dir}/{request_id}.json"

    await service._handle_request(request_file)

    response_path = f"{service._responses_dir}/{request_id}.json"
    response = json.loads(fake.writes[response_path])
    assert response == {"id": request_id, "result": 5, "error": None}
    assert fake.calls[0] == ["cat", "--", request_file]
    assert ["rm", "-f", "--", request_file] in fake.calls
    _assert_no_shell_interpolation(fake.calls)


@pytest.mark.parametrize(
    "request_data_id",
    [
        "",
        ".",
        "..",
        "../x",
        "/tmp/x",
        "a/b",
        r"a\b",
        "_hidden",
        "-option",
        "has space",
        "line\nbreak",
        "'quoted'",
        "semi;colon",
        "$(touch marker)",
        "glob*",
        "a" * 129,
        None,
        1,
    ],
)
async def test_handle_request_rejects_invalid_body_id(
    request_data_id: object,
) -> None:
    request_id = "safe-request"
    request_data = {
        "id": request_data_id,
        "method": "run",
        "params": {},
    }
    fake = _RequestReadSandbox(cat_stdout=json.dumps(request_data))
    service = _service_with_dirs(fake)
    called = False

    async def run() -> None:
        nonlocal called
        called = True

    service.add_method("run", run)
    request_file = f"{service._requests_dir}/{request_id}.json"

    await service._handle_request(request_file)

    assert not called
    assert set(fake.writes) == {f"{service._responses_dir}/{request_id}.json"}
    response = json.loads(next(iter(fake.writes.values())))
    assert response["id"] == request_id
    assert response["result"] is None
    assert "invalid" in response["error"]
    assert request_file in fake.removed


async def test_handle_request_rejects_mismatched_body_id() -> None:
    request_id = "filename-id"
    fake = _RequestReadSandbox(
        cat_stdout=json.dumps({"id": "different-id", "method": "run", "params": {}})
    )
    service = _service_with_dirs(fake)
    request_file = f"{service._requests_dir}/{request_id}.json"

    await service._handle_request(request_file)

    response_path = f"{service._responses_dir}/{request_id}.json"
    response = json.loads(fake.writes[response_path])
    assert response["id"] == request_id
    assert response["result"] is None
    assert "does not match" in response["error"]
    assert request_file in fake.removed


async def test_handle_request_rejects_non_object_payload() -> None:
    request_id = "safe-request"
    fake = _RequestReadSandbox(cat_stdout=json.dumps(["not", "an", "object"]))
    service = _service_with_dirs(fake)
    request_file = f"{service._requests_dir}/{request_id}.json"

    await service._handle_request(request_file)

    response_path = f"{service._responses_dir}/{request_id}.json"
    response = json.loads(fake.writes[response_path])
    assert response["id"] == request_id
    assert response["result"] is None
    assert "not a dict" in response["error"]
    assert request_file in fake.removed


async def test_handle_request_discards_shell_metacharacter_filename_as_argv() -> None:
    fake = _RequestReadSandbox()
    service = _service_with_dirs(fake)
    request_file = f"{service._requests_dir}/x;touch marker;.json"

    await service._handle_request(request_file)

    assert fake.writes == {}
    assert fake.removed == [request_file]
    assert fake.calls == [["rm", "-f", "--", request_file]]


async def test_handle_request_ignores_path_outside_request_dir() -> None:
    fake = _RequestReadSandbox()
    service = _service_with_dirs(fake)

    await service._handle_request("/tmp/outside.json")

    assert fake.calls == []
    assert fake.writes == {}
    assert fake.removed == []


async def test_handle_requests_lists_paths_without_shell_interpolation() -> None:
    request_id = "listed-request"
    fake = _RequestReadSandbox(
        cat_stdout=json.dumps({"id": request_id, "method": "run", "params": {}})
    )
    service = _service_with_dirs(fake)
    request_file = f"{service._requests_dir}/{request_id}.json"
    fake.list_stdout = f"{request_file}\0"

    async def run() -> str:
        return "ok"

    service.add_method("run", run)

    await service.handle_requests()

    assert fake.calls[0] == [
        "find",
        service._requests_dir,
        "-maxdepth",
        "1",
        "-name",
        "*.json",
        "-type",
        "f",
        "-print0",
    ]
    _assert_no_shell_interpolation(fake.calls)
    response_path = f"{service._responses_dir}/{request_id}.json"
    assert json.loads(fake.writes[response_path])["result"] == "ok"


class _RealListingSandbox(_RequestReadSandbox):
    """Variant of _RequestReadSandbox that runs the queue listing for real.

    The canned fake always reports the listing as successful, which hides the
    listing command's actual exit-status behavior; running it against a real
    directory lets tests observe what the sandbox would.
    """

    async def exec(
        self,
        cmd: list[str],
        *,
        user: str | None = None,
        input: str | None = None,
        timeout: int | None = None,
        concurrency: bool = True,
    ) -> ExecResult[str]:
        if cmd[0] == "find":
            self.calls.append(cmd)
            completed = subprocess.run(cmd, capture_output=True, text=True)
            return cast(
                ExecResult[str],
                FakeExecResult(
                    success=completed.returncode == 0,
                    returncode=completed.returncode,
                    stdout=completed.stdout,
                    stderr=completed.stderr,
                ),
            )
        return await super().exec(
            cmd, user=user, input=input, timeout=timeout, concurrency=concurrency
        )


@pytest.mark.skipif(shutil.which("find") is None, reason="find not available")
async def test_handle_requests_survives_stray_non_file_entry(tmp_path: Path) -> None:
    """A stray non-regular `*.json` entry must not starve the request queue.

    Sandbox code owns the requests dir and can freely create a directory or
    dangling symlink named `*.json` there; valid queued requests must still be
    handled when one is present.
    """
    request_id = "listed-request"
    fake = _RealListingSandbox(
        cat_stdout=json.dumps({"id": request_id, "method": "run", "params": {}})
    )
    service = _service_with_dirs(fake)
    requests_dir = tmp_path / "requests"
    requests_dir.mkdir()
    service._requests_dir = str(requests_dir)
    (requests_dir / f"{request_id}.json").touch()
    # non-regular entry that globs after the valid request
    (requests_dir / "zzz.json").mkdir()

    async def run() -> str:
        return "ok"

    service.add_method("run", run)

    await service.handle_requests()

    response_path = f"{service._responses_dir}/{request_id}.json"
    assert response_path in fake.writes, (
        "valid request was dropped because the listing script reported failure"
    )
    assert json.loads(fake.writes[response_path])["result"] == "ok"


@pytest.mark.parametrize(
    "bad_name",
    [
        "",
        ".",
        "..",
        "../etc",
        "/tmp/service",
        "foo/bar",
        "foo-bar",
        "foo bar",
        "foo;bar",
        "foo\nbar",
        "9service",
        "a" * 129,
    ],
)
def test_sandbox_service_rejects_invalid_name(bad_name: str) -> None:
    fake = _StartSandbox()
    with pytest.raises(ValueError, match="invalid service name"):
        SandboxService(
            name=bad_name,
            sandbox=cast(SandboxEnvironment, fake),
            user="agent",
        )


@pytest.mark.parametrize(
    "bad_instance",
    [
        "",
        ".",
        "..",
        "../etc",
        "/tmp/instance",
        "foo/bar",
        "_hidden",
        "-option",
        "foo bar",
        "foo;bar",
        "foo\nbar",
        "a" * 129,
    ],
)
def test_sandbox_service_rejects_invalid_instance(bad_instance: str) -> None:
    """Invalid instance filename tokens are rejected."""
    fake = _StartSandbox()
    with pytest.raises(ValueError, match="invalid instance"):
        SandboxService(
            name="x",
            sandbox=cast(SandboxEnvironment, fake),
            user="agent",
            instance=bad_instance,
        )


NONROOT_COMPOSE = str(Path(__file__).parent / "compose.sandbox-service-nonroot.yaml")
"""Compose file whose default user is `nonroot` (root exec is still available)."""


def _eval_service_solver(solver: Solver, compose: str) -> dict[str, Any]:
    log = eval(Task(solver=solver), model="mockllm/model", sandbox=("docker", compose))[
        0
    ]
    assert log.status == "success", log.error
    assert log.samples
    return log.samples[0].store


@pytest.mark.slow
@skip_if_no_docker
@pytest.mark.parametrize("user", [None, "root"])
def test_sandbox_service_with_nonroot_default_user(user: str | None) -> None:
    """The shared parent is prepared as root even when the default user is not."""
    store = _eval_service_solver(math_service(user, True), NONROOT_COMPOSE)
    assert store.get("result") == 8


@pytest.mark.slow
@skip_if_no_docker
def test_sandbox_service_nonroot_after_root_service() -> None:
    """A root service leaves a shared parent any user can use; nonroot then starts."""

    async def prepare() -> None:
        await SandboxService("setup_service", sandbox(), user="root").start()

    store = _eval_service_solver(math_service("nonroot", True, prepare), COMPOSE)
    assert store.get("result") == 8


@solver
def start_service_and_inspect(
    name: str, user: str | None, prepare: Sequence[tuple[str | None, str]] = ()
) -> Solver:
    """Run `prepare` scripts (as the given users), start a service, record the outcome.

    The store receives the startup error (or None), a probe request's response when
    startup succeeded, `stat` output for every path of interest (None if absent) and
    the entries of `/tmp/decoy`, a directory tests point planted symlinks at.
    """

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        for prepare_user, script in prepare:
            prep = await sandbox().exec(["sh", "-c", script], user=prepare_user)
            assert prep.success, prep.stderr

        service = SandboxService(name, sandbox(), user=user)
        service.add_method("noop", _noop)
        try:
            await service.start()
            state.store.set("error", None)
        except Exception as ex:
            state.store.set("error", f"{type(ex).__name__}: {ex}")

        service_dir = f"{SERVICES_DIR}/{name}"
        if state.store.get("error") is None:
            await sandbox().write_file(
                f"{service_dir}/requests/probe.json",
                json.dumps({"id": "probe", "method": "noop", "params": {}}),
            )
            await service.handle_requests()
            response = await sandbox().read_file(f"{service_dir}/responses/probe.json")
            state.store.set("response", json.loads(response))

        shapes: dict[str, str | None] = {}
        for path in [
            SERVICES_DIR,
            service_dir,
            f"{service_dir}/requests",
            f"{service_dir}/responses",
            f"{service_dir}/responses/stale.json",
            f"{service_dir}/{name}.py",
        ]:
            result = await sandbox().exec(["stat", "-c", "%F %U %a", path], user="root")
            shapes[path] = result.stdout.strip() if result.success else None
        state.store.set("shapes", shapes)
        decoy = await sandbox().exec(["ls", "-A", "/tmp/decoy"], user="root")
        state.store.set("decoy", decoy.stdout.split() if decoy.success else None)
        return state

    return solve


async def _noop() -> None:
    return None


_DECOY = "mkdir -p /tmp/decoy && chmod 777 /tmp/decoy && touch /tmp/decoy/sentinel"
_SHARED_PARENT = f"mkdir -p -m 1777 {SERVICES_DIR}"


@pytest.mark.slow
@skip_if_no_docker
def test_sandbox_service_directories_are_private_to_the_service_user() -> None:
    store = _eval_service_solver(
        start_service_and_inspect("svc", None), NONROOT_COMPOSE
    )
    assert store["error"] is None
    assert store["response"]["id"] == "probe"
    svc = f"{SERVICES_DIR}/svc"
    assert store["shapes"] == {
        SERVICES_DIR: "directory root 1777",
        svc: "directory nonroot 700",
        f"{svc}/requests": "directory nonroot 700",
        f"{svc}/responses": "directory nonroot 700",
        f"{svc}/responses/stale.json": None,
        f"{svc}/svc.py": "regular file nonroot 600",
    }


@pytest.mark.slow
@skip_if_no_docker
@pytest.mark.parametrize(
    "plant, fragment",
    [
        pytest.param("mkdir -m 755 {svc}", "owned by uid 0", id="other-uid"),
        pytest.param("ln -s /tmp/decoy {svc}", "is a symbolic link", id="symlink"),
        pytest.param("touch {svc}", "is not a directory", id="file"),
    ],
)
def test_sandbox_service_refuses_planted_service_dir(plant: str, fragment: str) -> None:
    """An entry another user pre-created at the service path fails startup, untouched."""
    svc = f"{SERVICES_DIR}/planted"
    prepare = [("root", f"{_SHARED_PARENT} && {_DECOY} && {plant.format(svc=svc)}")]
    store = _eval_service_solver(
        start_service_and_inspect("planted", None, prepare), NONROOT_COMPOSE
    )
    assert store["error"] is not None
    assert store["error"].startswith("FrameworkDirectoryError:")
    assert "cannot be trusted" in store["error"]
    assert fragment in store["error"]
    shapes = store["shapes"]
    assert shapes[f"{svc}/requests"] is None
    assert shapes[f"{svc}/responses"] is None
    assert shapes[f"{svc}/planted.py"] is None
    assert store["decoy"] == ["sentinel"]


@pytest.mark.slow
@skip_if_no_docker
def test_sandbox_service_refuses_nonconforming_shared_parent() -> None:
    """A pre-existing shared parent in the wrong shape is refused, not repaired."""
    prepare = [("root", f"mkdir -p {SERVICES_DIR} && chmod 755 {SERVICES_DIR}")]
    store = _eval_service_solver(
        start_service_and_inspect("svc", None, prepare), NONROOT_COMPOSE
    )
    assert store["error"] is not None
    assert "has mode 755, expected 1777" in store["error"]
    assert store["shapes"][SERVICES_DIR] == "directory root 755"
    assert store["shapes"][f"{SERVICES_DIR}/svc"] is None


@pytest.mark.slow
@skip_if_no_docker
def test_sandbox_service_resets_redirected_queue_without_following_it() -> None:
    """Queue reset replaces a redirected queue name and clears stale contents.

    The target of the planted symlink must be untouched: the reset unlinks the
    name inside the verified service directory rather than following it.
    """
    svc = f"{SERVICES_DIR}/svc"
    prepare = [
        ("root", f"{_SHARED_PARENT} && {_DECOY}"),
        (
            None,
            f"mkdir -m 700 {svc} && ln -s /tmp/decoy {svc}/requests && "
            f"mkdir -m 700 {svc}/responses && echo stale > {svc}/responses/stale.json",
        ),
    ]
    store = _eval_service_solver(
        start_service_and_inspect("svc", None, prepare), NONROOT_COMPOSE
    )
    assert store["error"] is None
    assert store["response"]["id"] == "probe"
    assert store["decoy"] == ["sentinel"]
    assert store["shapes"][f"{svc}/requests"] == "directory nonroot 700"
    assert store["shapes"][f"{svc}/responses"] == "directory nonroot 700"
    assert store["shapes"][f"{svc}/responses/stale.json"] is None


@dataclass
class _QueueSandbox:
    """Fake sandbox backed by an in-memory request/response queue."""

    files: dict[str, str] = field(default_factory=dict)

    def default_polling_interval(self) -> float:
        return 0.01

    async def exec(
        self,
        cmd: list[str],
        *,
        user: str | None = None,
        input: str | None = None,
        timeout: int | None = None,
        concurrency: bool = True,
    ) -> ExecResult[str]:
        call = _decode_helper(cmd, user)
        if call is not None:
            if call.cmd[:1] == ("tee",):
                self.files[f"{call.path}/{call.cmd[-1]}"] = input or ""
            return cast(ExecResult[str], _VERIFIED)
        if cmd[0] == "find":
            hits = [
                path
                for path in self.files
                if path.startswith(f"{cmd[1]}/") and path.endswith(".json")
            ]
            return cast(ExecResult[str], FakeExecResult(stdout="\0".join(sorted(hits))))
        if cmd[0] == "cat":
            return cast(
                ExecResult[str], FakeExecResult(stdout=self.files.get(cmd[-1], ""))
            )
        if cmd[0] == "rm":
            self.files.pop(cmd[-1], None)
            return cast(ExecResult[str], FakeExecResult())
        return cast(ExecResult[str], FakeExecResult())


def _enqueue(
    fake: _QueueSandbox, service: SandboxService, rid: str, method: str
) -> None:
    fake.files[f"{service._requests_dir}/{rid}.json"] = json.dumps(
        {"id": rid, "method": method, "params": {}}
    )


async def test_slow_request_does_not_block_later_requests() -> None:
    """A request still in flight must not stop the queue being served.

    Model generation retries indefinitely by default, so a single rate-limited
    request can occupy the service for a very long time. If serving the queue
    waits for it, every later request goes unanswered and the service never
    recovers.
    """
    fake = _QueueSandbox()
    service = _service_with_dirs(fake)

    release = anyio.Event()
    served: list[str] = []

    async def slow() -> JsonValue:
        await release.wait()
        return "slow"

    async def quick() -> JsonValue:
        served.append("quick")
        return "quick"

    service.add_method("slow", slow)
    service.add_method("quick", quick)

    async with anyio.create_task_group() as tg:
        _enqueue(fake, service, "req-slow", "slow")
        # bounded: without `tg` threaded through, this call would wait for
        # `slow` to finish before returning -- which never happens, since
        # `release` is only set below, after this call returns -- turning a
        # regression into a hang instead of a fast failure.
        with anyio.fail_after(5):
            await service.handle_requests(tg)
        await anyio.sleep(0.05)

        assert "req-slow" in service._in_flight, "slow request did not start"

        _enqueue(fake, service, "req-quick", "quick")
        with anyio.fail_after(5):
            await service.handle_requests(tg)
        await anyio.sleep(0.05)

        assert served == ["quick"], (
            "later request was not served while one was in flight"
        )
        assert "req-slow" in service._in_flight, (
            "slow request must still be in flight while the quick one is served"
        )
        assert f"{service._responses_dir}/req-quick.json" in fake.files

        release.set()
        await anyio.sleep(0.05)
        assert f"{service._responses_dir}/req-slow.json" in fake.files
        tg.cancel_scope.cancel()


async def test_in_flight_request_is_not_dispatched_twice() -> None:
    """A request file stays on disk until answered, so polls must not re-run it."""
    fake = _QueueSandbox()
    service = _service_with_dirs(fake)

    release = anyio.Event()
    starts: list[str] = []

    async def slow() -> JsonValue:
        starts.append("slow")
        await release.wait()
        return "slow"

    service.add_method("slow", slow)

    async with anyio.create_task_group() as tg:
        _enqueue(fake, service, "req-slow", "slow")
        for _ in range(3):
            # bounded: without `tg` threaded through on every call, the first
            # call here would wait for `slow` to finish -- which never
            # happens until `release` is set below -- turning a regression
            # into a hang instead of a fast failure.
            with anyio.fail_after(5):
                await service.handle_requests(tg)
            await anyio.sleep(0.02)

        assert starts == ["slow"], f"request dispatched {len(starts)} times"

        release.set()
        await anyio.sleep(0.05)
        tg.cancel_scope.cancel()


@dataclass
class _DelayedWriteSandbox(_QueueSandbox):
    """`_QueueSandbox` that delays writing service response files.

    Used to simulate a request whose `_write_response()` is still in flight
    when `until()` becomes true, so a regression test can assert the
    response is still written (and the request file removed) after the poll
    loop stops, instead of the write being cancelled mid-flight.
    """

    write_delay: float = 0.05

    async def exec(
        self,
        cmd: list[str],
        *,
        user: str | None = None,
        input: str | None = None,
        timeout: int | None = None,
        concurrency: bool = True,
    ) -> ExecResult[str]:
        call = _decode_helper(cmd, user)
        if (
            call is not None
            and call.cmd[:1] == ("tee",)
            and call.path.endswith("/responses")
        ):
            await anyio.sleep(self.write_delay)
        return await super().exec(
            cmd, user=user, input=input, timeout=timeout, concurrency=concurrency
        )


async def test_normal_exit_drains_in_flight_response_write() -> None:
    """`until()` becoming true must not cancel the write that made it true.

    A request handler can flip `until()` (e.g. by setting a flag the caller
    watches) before its own response has finished being written. If the poll
    loop cancels its task group as soon as it notices `until()`, it can kill
    that very write -- and the sandbox caller, which just polls the response
    file with no timeout, is left blocked forever. The loop must drain
    already-dispatched handlers instead.
    """
    fake = _DelayedWriteSandbox()
    name = "finisher_service"
    request_id = "req-finisher"
    request_file = f"{SERVICES_DIR}/{name}/requests/{request_id}.json"
    response_file = f"{SERVICES_DIR}/{name}/responses/{request_id}.json"
    fake.files[request_file] = json.dumps(
        {"id": request_id, "method": "finish", "params": {}}
    )

    finished = anyio.Event()

    async def finish() -> JsonValue:
        # flips until() while _write_response() for this very call is still
        # in flight (delayed by _DelayedWriteSandbox)
        finished.set()
        return "done"

    # bounded: if the loop drained forever (or the fix regressed to hanging
    # some other way) this turns it into a fast failure instead of a hang.
    with anyio.fail_after(5):
        await sandbox_service(
            name=name,
            methods=[finish],
            until=finished.is_set,
            sandbox=cast(SandboxEnvironment, fake),
            polling_interval=0.01,
        )

    assert response_file in fake.files, (
        "response write was cancelled instead of drained on normal exit"
    )
    assert json.loads(fake.files[response_file])["result"] == "done"
    assert request_file not in fake.files, "request file was not removed"


async def test_stuck_handler_is_cancelled_after_grace_period() -> None:
    """A handler stuck in user/model code must not hold the service open forever.

    Draining in-flight handlers on normal exit must be bounded: an unrelated
    request whose handler never returns must not stop `sandbox_service()`
    from returning once the grace period elapses, and a fast in-flight
    response (the one whose completion made `until()` true) must still be
    written before that happens.
    """
    fake = _QueueSandbox()
    service_name = "grace_service"
    stuck_id = "req-stuck"
    finish_id = "req-finish"
    fake.files[f"{SERVICES_DIR}/{service_name}/requests/{stuck_id}.json"] = json.dumps(
        {"id": stuck_id, "method": "stuck", "params": {}}
    )
    fake.files[f"{SERVICES_DIR}/{service_name}/requests/{finish_id}.json"] = json.dumps(
        {"id": finish_id, "method": "finish", "params": {}}
    )

    finished = anyio.Event()
    stuck_cancelled = False

    async def stuck() -> JsonValue:
        nonlocal stuck_cancelled
        try:
            await anyio.sleep_forever()
            return "unreachable"
        except anyio.get_cancelled_exc_class():
            stuck_cancelled = True
            raise

    async def finish() -> JsonValue:
        finished.set()
        return "done"

    grace = 0.1
    with patch("inspect_ai.util._sandbox.service.NORMAL_EXIT_DRAIN_TIMEOUT", grace):
        # bounded well past the grace period: proves the service returns
        # once the grace period elapses instead of waiting on the stuck
        # handler forever.
        with anyio.fail_after(grace + 5):
            await sandbox_service(
                name=service_name,
                methods=[stuck, finish],
                until=finished.is_set,
                sandbox=cast(SandboxEnvironment, fake),
                polling_interval=0.01,
            )

    assert stuck_cancelled, "stuck handler was not cancelled after the grace period"
    response_file = f"{SERVICES_DIR}/{service_name}/responses/{finish_id}.json"
    assert response_file in fake.files, (
        "in-flight response was not written before the grace period forced cancellation"
    )
    assert json.loads(fake.files[response_file])["result"] == "done"
