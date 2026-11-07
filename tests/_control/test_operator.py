"""Tests for operator targets: the registry, its routes and the `sample agent` verbs.

Covers ``inspect_ai._control.operator`` (``operator_group()`` and the two
route handlers), the routes ``GET /evals/<id>/sample/agents`` and
``POST /evals/<id>/sample/agent/<action>``, and ``inspect ctl sample agent``,
whose requests go through the CLI's real HTTP layer to the real app.
"""

import json
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import anyio
import boto3
import httpx
import pytest
from botocore.exceptions import EndpointConnectionError, NoCredentialsError

from _control.conftest import cli_runner
from inspect_ai import Task, eval_async
from inspect_ai._cli.ctl import ctl_command
from inspect_ai._cli.ctl._fetch import _FetchedSummaries
from inspect_ai._control.operator import (
    OperatorAgent,
    OperatorAgentInfo,
    OperatorGroupInfo,
    OperatorOutcome,
    operator_group,
)
from inspect_ai.dataset import Sample
from inspect_ai.log._samples import _sample_active, sample_active
from inspect_ai.solver import Generate, TaskState, solver
from inspect_ai.util._display import init_display_type

# ---------------------------------------------------------------------------
# Test registrants
# ---------------------------------------------------------------------------


@dataclass
class _Agent:
    """An operator agent that records each call and answers a set outcome."""

    name: str
    outcome: OperatorOutcome = field(
        default_factory=lambda: OperatorOutcome(changed=True, detail="done")
    )
    calls: list[tuple[Any, ...]] = field(default_factory=list)

    def info(self) -> OperatorAgentInfo:
        return OperatorAgentInfo(
            name=self.name,
            state="running",
            status=None,
            activity="in_turn",
            paused=False,
            actions={
                "message": None,
                "pause": None,
                "resume": None,
                "stop": "has ended",
            },
        )

    def message(self, text: str, *, interrupt: bool, dry_run: bool) -> OperatorOutcome:
        self.calls.append(("message", text, interrupt, dry_run))
        return self.outcome

    def pause(self, *, dry_run: bool) -> OperatorOutcome:
        self.calls.append(("pause", dry_run))
        return self.outcome

    def resume(self, *, dry_run: bool) -> OperatorOutcome:
        self.calls.append(("resume", dry_run))
        return self.outcome

    def stop(self, *, dry_run: bool) -> OperatorOutcome:
        self.calls.append(("stop", dry_run))
        return self.outcome


@dataclass
class _Group:
    """An operator group that records each call and answers a set outcome."""

    name: str
    members: dict[str, _Agent] = field(default_factory=dict)
    outcome: OperatorOutcome = field(
        default_factory=lambda: OperatorOutcome(changed=True, detail="done")
    )
    calls: list[tuple[Any, ...]] = field(default_factory=list)

    @property
    def agents(self) -> dict[str, OperatorAgent]:
        return dict(self.members)

    def info(self) -> OperatorGroupInfo:
        return OperatorGroupInfo(
            name=self.name,
            state="running",
            stop=None,
            paused=False,
            agents=[agent.info() for agent in self.members.values()],
        )

    def pause(self, *, dry_run: bool) -> OperatorOutcome:
        self.calls.append(("pause", dry_run))
        return self.outcome

    def resume(self, *, dry_run: bool) -> OperatorOutcome:
        self.calls.append(("resume", dry_run))
        return self.outcome

    def stop(self, *, dry_run: bool) -> OperatorOutcome:
        self.calls.append(("stop", dry_run))
        return self.outcome


def _group(name: str, *agents: str) -> _Group:
    return _Group(name, {agent: _Agent(agent) for agent in agents})


class _FakeSample:
    """The slice of ``ActiveSample`` the registry and routes read."""

    class _Sample:
        def __init__(self, id: str) -> None:
            self.id = id

    def __init__(self, *, eval_id: str = "e1", sample_id: str = "s1") -> None:
        self.eval_id = eval_id
        self.sample = self._Sample(sample_id)
        self.epoch = 1
        self.operator_groups: dict[str, Any] = {}


@contextmanager
def _in_sample(sample: _FakeSample) -> Iterator[None]:
    token = _sample_active.set(cast(Any, sample))
    try:
        yield
    finally:
        _sample_active.reset(token)


@pytest.fixture
def sample(monkeypatch: pytest.MonkeyPatch) -> _FakeSample:
    """A live sample ``e1``/``s1`` (epoch 1) the routes can find."""
    fake = _FakeSample()
    monkeypatch.setattr("inspect_ai.log._samples.active_samples", lambda: [fake])
    return fake


def _app() -> Any:
    from inspect_ai._control.server import ControlServer

    return ControlServer(run_id="test")._build_app()


# ---------------------------------------------------------------------------
# operator_group()
# ---------------------------------------------------------------------------


def test_operator_group_registers_and_unregisters() -> None:
    fake = _FakeSample()
    group = _group("swarm", "a", "b")
    with _in_sample(fake):
        with operator_group("swarm", group):
            assert fake.operator_groups == {"swarm": group}
        assert fake.operator_groups == {}

        # removed when the block raises, too
        with pytest.raises(RuntimeError):
            with operator_group("swarm", group):
                raise RuntimeError("boom")
        assert fake.operator_groups == {}


def test_operator_group_refuses_a_duplicate_group_name() -> None:
    fake = _FakeSample()
    first = _group("swarm", "a")
    with _in_sample(fake), operator_group("swarm", first):
        with pytest.raises(ValueError, match="operator group named 'swarm'"):
            with operator_group("swarm", _group("swarm", "b")):
                pass
        assert fake.operator_groups == {"swarm": first}


def test_operator_group_refuses_an_agent_in_two_groups() -> None:
    fake = _FakeSample()
    first = _group("swarm", "a", "b")
    with _in_sample(fake), operator_group("swarm", first):
        with pytest.raises(ValueError, match="'b' of group 'swarm:a'.*group 'swarm'"):
            with operator_group("swarm:a", _group("swarm:a", "b", "c")):
                pass
        assert fake.operator_groups == {"swarm": first}


def test_operator_group_outside_a_sample_does_nothing() -> None:
    assert sample_active() is None
    with operator_group("swarm", _group("swarm", "a")):
        pass


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


async def test_agents_route_lists_groups(sample: _FakeSample) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()), base_url="http://localhost"
    ) as client:
        empty = await client.get("/evals/e1/sample/agents", params={"sample_id": "s1"})
        assert empty.status_code == 200, empty.text
        assert empty.json()["groups"] == []

        sample.operator_groups["swarm"] = _group("swarm", "a")
        listed = await client.get(
            "/evals/e1/sample/agents", params={"sample_id": "s1", "epoch": 1}
        )
        body = listed.json()
        assert body["sample_id"] == "s1" and body["epoch"] == 1
        assert body["groups"] == [
            {
                "name": "swarm",
                "state": "running",
                "stop": None,
                "paused": False,
                "agents": [
                    {
                        "name": "a",
                        "state": "running",
                        "status": None,
                        "activity": "in_turn",
                        "paused": False,
                        "actions": {
                            "message": None,
                            "pause": None,
                            "resume": None,
                            "stop": "has ended",
                        },
                    }
                ],
            }
        ]

        missing = await client.get(
            "/evals/e1/sample/agents", params={"sample_id": "s9"}
        )
        assert missing.status_code == 404
        assert missing.json() == {"error": "sample s9 (epoch 1) not found"}


async def test_agent_action_routes_reach_the_target(sample: _FakeSample) -> None:
    group = _group("swarm", "a")
    sample.operator_groups["swarm"] = group
    agent = group.members["a"]
    url = "/evals/e1/sample/agent"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()), base_url="http://localhost"
    ) as client:
        message = await client.post(
            f"{url}/message",
            params={"sample_id": "s1", "epoch": 1, "agent": "a", "interrupt": True},
            json={"text": "look at the logs\nfirst"},
        )
        assert message.status_code == 200, message.text
        assert message.json() == {
            "ok": True,
            "sample_id": "s1",
            "epoch": 1,
            "changed": True,
            "dry_run": False,
            "target": {"group": "swarm", "agent": "a"},
            "detail": "done",
        }
        plain = await client.post(
            f"{url}/message",
            params={"sample_id": "s1", "epoch": 1, "agent": "a", "dry_run": True},
            json={"text": "hi"},
        )
        assert plain.status_code == 200, plain.text
        for action in ("pause", "resume", "stop"):
            response = await client.post(
                f"{url}/{action}", params={"sample_id": "s1", "epoch": 1, "agent": "a"}
            )
            assert response.status_code == 200, response.text
            grouped = await client.post(
                f"{url}/{action}",
                params={
                    "sample_id": "s1",
                    "epoch": 1,
                    "group": "swarm",
                    "dry_run": True,
                },
            )
            assert grouped.status_code == 200, grouped.text
            assert grouped.json()["target"] == {"group": "swarm"}

    assert agent.calls == [
        ("message", "look at the logs\nfirst", True, False),
        ("message", "hi", False, True),
        ("pause", False),
        ("resume", False),
        ("stop", False),
    ]
    assert group.calls == [("pause", True), ("resume", True), ("stop", True)]


async def test_agent_action_route_passes_refusal_and_no_change(
    sample: _FakeSample,
) -> None:
    group = _group("swarm", "a", "b")
    group.members["a"].outcome = OperatorOutcome(
        changed=False, detail="", refused="it has ended"
    )
    group.members["b"].outcome = OperatorOutcome(changed=False, detail="already paused")
    sample.operator_groups["swarm"] = group
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()), base_url="http://localhost"
    ) as client:
        refused = await client.post(
            "/evals/e1/sample/agent/pause",
            params={"sample_id": "s1", "epoch": 1, "agent": "a"},
        )
        assert refused.status_code == 409
        assert refused.json()["error"] == "it has ended"

        repeat = await client.post(
            "/evals/e1/sample/agent/pause",
            params={"sample_id": "s1", "epoch": 1, "agent": "b"},
        )
        assert repeat.status_code == 200
        assert repeat.json()["changed"] is False
        assert repeat.json()["detail"] == "already paused"


@pytest.mark.parametrize(
    "action,params,body,error",
    [
        ("pause", {"agent": "a"}, None, "epoch is required"),
        ("pause", {"epoch": 1}, None, "exactly one of agent and group"),
        (
            "pause",
            {"epoch": 1, "agent": "a", "group": "swarm"},
            None,
            "exactly one of agent and group",
        ),
        ("message", {"epoch": 1, "group": "swarm"}, {"text": "x"}, "not a group"),
        ("pause", {"epoch": 1, "agent": "a", "interrupt": True}, None, "interrupt"),
        ("stop", {"epoch": 1, "agent": "a", "interrupt": False}, None, "interrupt"),
        ("message", {"epoch": 1, "agent": "a"}, {"text": ""}, "non-empty text"),
        ("message", {"epoch": 1, "agent": "a"}, {"text": " \n"}, "non-empty text"),
        ("message", {"epoch": 1, "agent": "a"}, None, "non-empty text"),
        ("message", {"epoch": 1, "agent": "a"}, {"txt": "x"}, "request body"),
        ("message", {"epoch": 1, "agent": "a"}, {"text": 3}, "request body"),
        ("message", {"epoch": 1, "agent": "a"}, ["x"], "request body"),
        ("pause", {"epoch": 1, "agent": "a"}, {"text": "x"}, "takes no request body"),
        ("explode", {"epoch": 1, "agent": "a"}, None, "action must be one of"),
    ],
)
async def test_agent_action_route_rejects_bad_requests(
    sample: _FakeSample,
    action: str,
    params: dict[str, Any],
    body: Any,
    error: str,
) -> None:
    group = _group("swarm", "a")
    sample.operator_groups["swarm"] = group
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()), base_url="http://localhost"
    ) as client:
        response = await client.post(
            f"/evals/e1/sample/agent/{action}",
            params={"sample_id": "s1", **params},
            json=body,
        )
    assert response.status_code == 400, response.text
    assert error in response.json()["error"]
    assert group.calls == [] and group.members["a"].calls == []


async def test_agent_action_route_404_names_the_targets(sample: _FakeSample) -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()), base_url="http://localhost"
    ) as client:

        async def pause(**params: Any) -> httpx.Response:
            return await client.post(
                "/evals/e1/sample/agent/pause",
                params={"sample_id": "s1", "epoch": 1, **params},
            )

        none = await pause(agent="a")
        assert none.status_code == 404
        assert none.json()["error"] == (
            "no agent 'a' in sample s1 (epoch 1); the sample has no addressable agents"
        )

        sample.operator_groups["swarm"] = _group("swarm", "a", "b")
        sample.operator_groups["swarm:a"] = _group("swarm:a", "c")
        agent = await pause(agent="z")
        assert agent.status_code == 404
        assert agent.json()["error"] == (
            "no agent 'z' in sample s1 (epoch 1); agents: a, b, c"
        )
        group = await pause(group="swarm:z")
        assert group.status_code == 404
        assert group.json()["error"] == (
            "no group 'swarm:z' in sample s1 (epoch 1); groups: swarm, swarm:a"
        )
        missing = await client.post(
            "/evals/e1/sample/agent/pause",
            params={"sample_id": "s9", "epoch": 1, "agent": "a"},
        )
        assert missing.status_code == 404
        assert missing.json() == {"error": "sample s9 (epoch 1) not found"}


async def test_agent_action_route_refuses_an_agent_in_two_groups(
    sample: _FakeSample,
) -> None:
    """A group whose agents changed after registration cannot make a name ambiguous."""
    first = _group("swarm", "a")
    second = _group("swarm:x", "b")
    sample.operator_groups.update({"swarm": first, "swarm:x": second})
    second.members["a"] = _Agent("a")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app()), base_url="http://localhost"
    ) as client:
        response = await client.post(
            "/evals/e1/sample/agent/stop",
            params={"sample_id": "s1", "epoch": 1, "agent": "a"},
        )
    assert response.status_code == 409
    assert "more than one group (swarm, swarm:x)" in response.json()["error"]
    assert first.members["a"].calls == [] and second.members["a"].calls == []


@solver
def _register_and_probe(seen: dict[str, Any]) -> Any:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        active = sample_active()
        assert active is not None
        group = _group("swarm", "worker")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=_app()), base_url="http://localhost"
        ) as client:
            params: dict[str, str | int] = {
                "sample_id": str(active.sample.id),
                "epoch": active.epoch,
            }
            url = f"/evals/{active.eval_id}/sample"
            with operator_group("swarm", group):
                listed = await client.get(f"{url}/agents", params=params)
                seen["listed"] = [g["name"] for g in listed.json()["groups"]]
                stopped = await client.post(
                    f"{url}/agent/stop", params={**params, "agent": "worker"}
                )
                seen["stopped"] = stopped.status_code
            after = await client.get(f"{url}/agents", params=params)
            seen["after"] = after.json()["groups"]
        seen["calls"] = group.members["worker"].calls
        return state

    return solve


async def test_operator_group_in_a_running_sample() -> None:
    """A group registered in a real sample is listed and acted on, then removed."""
    init_display_type("none")
    seen: dict[str, Any] = {}
    logs = await eval_async(
        Task(dataset=[Sample(id="s1", input="x")], solver=_register_and_probe(seen)),
        model="mockllm/model",
        ctl_server=False,
    )
    assert logs[0].status == "success"
    assert seen == {
        "listed": ["swarm"],
        "stopped": 200,
        "after": [],
        "calls": [("stop", False)],
    }


# ---------------------------------------------------------------------------
# CLI: `inspect ctl sample agent`, over the CLI's real HTTP layer
# ---------------------------------------------------------------------------


def _summary(epochs: int = 1) -> dict[str, Any]:
    return {
        "task_id": "t1",
        "task": "mytask",
        "eval_id": "e1",
        "socket_path": "/tmp/7.sock",
        "pid": 7,
        "status": "running",
        "samples": {},
        "started_at": 100.0,
        "keep_alive": False,
        "epochs": epochs,
    }


class _Server:
    """Routes the CLI's HTTP requests to the control app in process.

    ``after_response`` runs once the app has answered and before the client
    gets the response; raising from it simulates a response that is lost
    after the server applied the request.
    """

    def __init__(self, app: Any) -> None:
        self.app = app
        self.requests: list[httpx.Request] = []
        self.after_response: Callable[[httpx.Request], None] | None = None

    async def _send(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        response = await httpx.ASGITransport(app=self.app).handle_async_request(request)
        content = await response.aread()
        if self.after_response is not None:
            self.after_response(request)
        return httpx.Response(
            response.status_code, headers=response.headers, content=content
        )

    def sync_transport(self, **kwargs: Any) -> httpx.BaseTransport:
        server = self

        class _Sync(httpx.BaseTransport):
            def handle_request(self, request: httpx.Request) -> httpx.Response:
                request.read()
                return anyio.run(server._send, request)

        return _Sync()

    def async_transport(self, **kwargs: Any) -> httpx.AsyncBaseTransport:
        server = self

        class _Async(httpx.AsyncBaseTransport):
            async def handle_async_request(
                self, request: httpx.Request
            ) -> httpx.Response:
                await request.aread()
                return await server._send(request)

        return _Async()


@pytest.fixture
def server(monkeypatch: pytest.MonkeyPatch) -> _Server:
    """The control app behind the CLI, with one running task ``t1``."""
    fake = _Server(_app())
    monkeypatch.setattr(httpx, "HTTPTransport", fake.sync_transport)
    monkeypatch.setattr(httpx, "AsyncHTTPTransport", fake.async_transport)
    monkeypatch.setattr("inspect_ai._cli.ctl._http.list_discovered_servers", lambda: [])
    monkeypatch.setattr(
        "inspect_ai._cli.ctl._fetch._fetch_summaries",
        lambda servers, **kwargs: _FetchedSummaries([_summary()], []),
    )
    return fake


def _invoke(*args: str, input: str | bytes | None = None) -> Any:
    return cli_runner().invoke(ctl_command, ["sample", "agent", *args], input=input)


def test_cli_list(server: _Server, sample: _FakeSample) -> None:
    empty = _invoke("list", "t1", "s1")
    assert empty.exit_code == 0, empty.output
    assert "No addressable agents in sample s1 (epoch 1)." in empty.stdout

    sample.operator_groups["swarm"] = _group("swarm", "worker-1")
    listed = _invoke("list", "t1", "s1")
    assert listed.exit_code == 0, listed.output
    assert "Group swarm: running" in listed.stdout
    row = next(line for line in listed.stdout.splitlines() if "worker-1" in line)
    assert row.split() == [
        "swarm",
        "worker-1",
        "running",
        "in_turn",
        "no",
        "message,",
        "pause,",
        "resume",
    ]

    as_json = json.loads(_invoke("list", "t1", "s1", "--json").stdout)
    assert as_json["task_id"] == "t1" and as_json["sample_id"] == "s1"
    assert as_json["groups"][0]["agents"][0]["actions"]["stop"] == "has ended"


def test_cli_message_sends_the_text_once(server: _Server, sample: _FakeSample) -> None:
    group = _group("swarm", "worker-1")
    sample.operator_groups["swarm"] = group
    result = _invoke(
        "message",
        "t1",
        "s1",
        "--agent",
        "worker-1",
        "--text",
        "try the other branch",
        "--interrupt",
        "--json",
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["applied"] is True
    assert payload["detail"]["target"] == {"group": "swarm", "agent": "worker-1"}
    assert group.members["worker-1"].calls == [
        ("message", "try the other branch", True, False)
    ]
    assert len(server.requests) == 1
    assert server.requests[0].url.params["interrupt"] == "true"

    from_stdin = _invoke(
        "message",
        "t1",
        "s1",
        "--agent",
        "worker-1",
        "--file",
        "-",
        "--terse",
        input="line one\nline two\n",
    )
    assert from_stdin.exit_code == 0, from_stdin.output
    assert from_stdin.stdout.strip() == (
        "agent message mytask/s1 (epoch 1): accepted — agent 'worker-1': done"
    )
    assert group.members["worker-1"].calls[-1] == (
        "message",
        "line one\nline two\n",
        False,
        False,
    )
    assert "interrupt" not in server.requests[-1].url.params


def _message_from(path: str, input: str | bytes | None = None) -> Any:
    return _invoke(
        "message",
        "t1",
        "s1",
        "--agent",
        "worker-1",
        "--file",
        path,
        "--json",
        input=input,
    )


def test_cli_message_file_takes_a_path_or_a_file_uri(
    server: _Server, sample: _FakeSample, tmp_path: Path
) -> None:
    group = _group("swarm", "worker-1")
    sample.operator_groups["swarm"] = group
    message = tmp_path / "a message.txt"
    message.write_text("from a file\n", encoding="utf-8")
    for path in (str(message), message.as_uri()):
        result = _message_from(path)
        assert result.exit_code == 0, result.output
        assert group.members["worker-1"].calls[-1][:2] == ("message", "from a file\n")
    assert len(server.requests) == 2


def test_cli_message_file_takes_an_s3_url(
    mock_s3: None, server: _Server, sample: _FakeSample
) -> None:
    group = _group("swarm", "worker-1")
    sample.operator_groups["swarm"] = group
    boto3.client("s3").put_object(
        Bucket="test-bucket", Key="operator/message.txt", Body=b"from s3"
    )
    result = _message_from("s3://test-bucket/operator/message.txt")
    assert result.exit_code == 0, result.output
    assert group.members["worker-1"].calls == [("message", "from s3", False, False)]


def test_cli_message_stdin_is_utf8_with_universal_newlines(
    server: _Server, sample: _FakeSample
) -> None:
    group = _group("swarm", "worker-1")
    sample.operator_groups["swarm"] = group
    result = _message_from("-", input="héllo\r\nwörld\r".encode())
    assert result.exit_code == 0, result.output
    assert group.members["worker-1"].calls == [
        ("message", "héllo\nwörld\n", False, False)
    ]


_FILE_READ_FAILURES: dict[str, tuple[str, bytes | None, Exception | None]] = {
    # case: (--file value, stdin, error the reader raises instead of reading)
    "stdin not UTF-8": ("-", b"\xff", None),
    "file not UTF-8": ("{tmp}/binary.txt", None, None),
    "missing file": ("{tmp}/missing.txt", None, None),
    "directory": ("{tmp}", None, None),
    "bucket-only S3 URL": ("s3://test-bucket", None, None),
    "bucket-only S3 URL with slash": ("s3://test-bucket/", None, None),
    "unknown protocol": ("no-such-protocol://message.txt", None, None),
    "malformed file URI": ("file://[bad/path", None, None),
    "no S3 credentials": ("s3://test-bucket/m.txt", None, NoCredentialsError()),
    "S3 endpoint unreachable": (
        "s3://test-bucket/m.txt",
        None,
        EndpointConnectionError(endpoint_url="https://s3.invalid"),
    ),
}


@pytest.mark.parametrize("as_json", [False, True], ids=["human", "json"])
@pytest.mark.parametrize("case", list(_FILE_READ_FAILURES))
def test_cli_message_file_read_failure_is_reported(
    server: _Server,
    sample: _FakeSample,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    request: pytest.FixtureRequest,
    case: str,
    as_json: bool,
) -> None:
    """Any failure to read --file is invalid_request, before any request."""
    sample.operator_groups["swarm"] = _group("swarm", "worker-1")
    (tmp_path / "binary.txt").write_bytes(b"\xff")
    path, input, error = _FILE_READ_FAILURES[case]
    path = path.format(tmp=tmp_path)
    if error is not None:

        def failing_file(*args: Any, **kwargs: Any) -> Any:
            raise error

        monkeypatch.setattr("inspect_ai._cli.ctl._sample.file", failing_file)
    elif path.startswith("s3://"):
        request.getfixturevalue("mock_s3")
    args = ["message", "t1", "s1", "--agent", "worker-1", "--file", path]
    result = _invoke(*args, *(["--json"] if as_json else []), input=input)
    assert result.exit_code == 1
    assert f"Could not read --file {path}: " in result.stderr
    assert "Traceback" not in result.stderr
    if as_json:
        envelope = json.loads(result.stdout)["error"]
        assert envelope["kind"] == "invalid_request"
        assert envelope["message"].startswith(f"Could not read --file {path}: ")
        assert envelope["exception"]
    else:
        assert result.stdout == ""
    assert server.requests == []


def test_cli_usage_errors(server: _Server, sample: _FakeSample) -> None:
    neither = _invoke("message", "t1", "s1", "--agent", "a")
    assert neither.exit_code == 2
    assert "exactly one of --text and --file" in neither.stderr
    both = _invoke("pause", "t1", "s1", "--agent", "a", "--group", "swarm")
    assert both.exit_code == 2
    assert "exactly one of --agent and --group" in both.stderr
    assert server.requests == []


def test_cli_renders_handler_errors(server: _Server, sample: _FakeSample) -> None:
    group = _group("swarm", "worker-1")
    group.members["worker-1"].outcome = OperatorOutcome(
        changed=False, detail="", refused="it has ended"
    )
    sample.operator_groups["swarm"] = group

    agent = _invoke("pause", "t1", "s1", "--agent", "worker-9", "--json")
    assert agent.exit_code == 1
    error = json.loads(agent.stdout)["error"]
    assert error["kind"] == "not_found" and error["status"] == 404
    assert (
        "no agent 'worker-9' in sample s1 (epoch 1); agents: worker-1"
        in (error["message"])
    )

    group_missing = _invoke("stop", "t1", "s1", "--group", "swarm:x")
    assert group_missing.exit_code == 1
    assert "no group 'swarm:x' in sample s1 (epoch 1); groups: swarm" in (
        group_missing.stderr
    )

    no_sample = _invoke("resume", "t1", "s9", "--agent", "worker-1")
    assert no_sample.exit_code == 1
    assert "sample s9 (epoch 1) not found" in no_sample.stderr

    refused = _invoke("pause", "t1", "s1", "--agent", "worker-1", "--json")
    assert refused.exit_code == 1
    error = json.loads(refused.stdout)["error"]
    assert error["status"] == 409
    assert error["message"] == (
        "Failed to update pause of agent 'worker-1' in sample s1: it has ended"
    )

    listed = _invoke("list", "t1", "s9")
    assert listed.exit_code == 1
    assert "sample s9 (epoch 1) not found" in listed.stderr


def test_cli_reports_an_older_server(server: _Server) -> None:
    from fastapi import FastAPI

    server.app = FastAPI()
    for args in (["list", "t1", "s1"], ["stop", "t1", "s1", "--agent", "a"]):
        result = _invoke(*args)
        assert result.exit_code == 1
        assert "older inspect without the `sample agent` endpoints" in result.stderr


def _lose_response(request: httpx.Request) -> None:
    raise httpx.ReadTimeout("timed out", request=request)


def test_cli_message_with_a_lost_response_is_sent_once(
    server: _Server, sample: _FakeSample
) -> None:
    group = _group("swarm", "worker-1")
    sample.operator_groups["swarm"] = group
    server.after_response = _lose_response
    result = _invoke(
        "message", "t1", "s1", "--agent", "worker-1", "--text", "stop that", "--json"
    )
    assert result.exit_code == 1
    error = json.loads(result.stdout)["error"]
    assert error["kind"] == "unknown_outcome"
    assert error["exception"] == "httpx.ReadTimeout"
    assert "may have taken effect" in error["message"]
    assert "inspect ctl sample agent list t1 s1 1" in error["message"]
    assert len(server.requests) == 1
    assert group.members["worker-1"].calls == [("message", "stop that", False, False)]


@pytest.mark.parametrize("action", ["pause", "resume", "stop"])
def test_cli_group_action_with_a_lost_response_is_sent_once(
    server: _Server, sample: _FakeSample, action: str
) -> None:
    """A retry could reach a later group registered under the same name."""
    first = _group("swarm", "worker-1")
    replacement = _group("swarm", "worker-1")
    sample.operator_groups["swarm"] = first

    def replace_then_lose(request: httpx.Request) -> None:
        sample.operator_groups["swarm"] = replacement
        _lose_response(request)

    server.after_response = replace_then_lose
    result = _invoke(action, "t1", "s1", "--group", "swarm")
    assert result.exit_code == 1
    assert "outcome unknown" in result.stderr
    assert len(server.requests) == 1
    assert first.calls == [(action, False)]
    assert replacement.calls == []


def test_cli_list_with_a_lost_response_is_retried(
    server: _Server, sample: _FakeSample
) -> None:
    sample.operator_groups["swarm"] = _group("swarm", "worker-1")
    lost: list[httpx.Request] = []

    def lose_first(request: httpx.Request) -> None:
        if not lost:
            lost.append(request)
            _lose_response(request)

    server.after_response = lose_first
    result = _invoke("list", "t1", "s1", "--json")
    assert result.exit_code == 0, result.output
    assert len(server.requests) == 2
    assert json.loads(result.stdout)["groups"][0]["name"] == "swarm"
