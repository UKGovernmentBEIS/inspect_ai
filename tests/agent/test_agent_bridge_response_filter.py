from pathlib import Path
from typing import Literal, cast, get_args
from unittest.mock import AsyncMock

import anyio
import pytest
from pydantic import JsonValue
from test_helpers.utils import skip_if_no_docker

from inspect_ai._util.exception import TerminateSampleError
from inspect_ai.agent import AgentState
from inspect_ai.agent._bridge._errors import PROVIDER_ERROR_KEY, ResponseFilterError
from inspect_ai.agent._bridge.bridge import agent_bridge
from inspect_ai.agent._bridge.sandbox import bridge as sandbox_bridge_module
from inspect_ai.agent._bridge.sandbox.bridge import (
    _monitor_failure,
    sandbox_agent_bridge,
)
from inspect_ai.agent._bridge.sandbox.service import (
    _forward_provider_errors,
    generate_completions,
)
from inspect_ai.agent._bridge.sandbox.types import SandboxAgentBridge
from inspect_ai.agent._bridge.types import AgentBridge
from inspect_ai.agent._bridge.util import bridge_generate
from inspect_ai.event import ModelEvent
from inspect_ai.log import EvalLog
from inspect_ai.model._chat_message import ChatMessage, ChatMessageUser
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model import (
    GenerateFilter,
    GenerateInput,
    Model,
    ModelRefusalError,
    ModelResponseFilter,
    get_model,
)
from inspect_ai.model._model_output import ModelOutput, ModelUsage, StopReason
from inspect_ai.model._providers.mockllm import MockLLM
from inspect_ai.tool._tool_choice import ToolChoice
from inspect_ai.tool._tool_info import ToolInfo
from inspect_ai.util import ExecResult
from inspect_ai.util._limit import LimitExceededError


class _FakeProxy:
    def __aiter__(self) -> "_FakeProxy":
        return self

    async def __anext__(self) -> object:
        raise StopAsyncIteration

    async def kill(self) -> None:
        return None


class _FakeSandbox:
    def __init__(self) -> None:
        self.exec_remote = AsyncMock(return_value=_FakeProxy())
        self._tools_user: str | None = None


REPLACED_SENTINEL = "9E5C8B41-D8AE-4E15-A8E7-2A86C5C73D5C"
SANDBOX_REPLACED_SENTINEL = "1F4D8E62-A93B-4E72-B6F1-9B3C20A8B4F8"


def _run_eval_with_filters(
    tmp_path: Path,
    *,
    filter: GenerateFilter | None = None,
    response_filter: ModelResponseFilter | None = None,
    retry_refusals: int | None = None,
    model: str | Model = "mockllm/model",
    token_limit: int | None = None,
    target: str | None = None,
) -> EvalLog:
    """Run a one-turn agent_bridge eval against mockllm with supplied filters."""
    from openai import AsyncOpenAI

    from inspect_ai import Task, eval, task
    from inspect_ai.agent import Agent, agent
    from inspect_ai.dataset import Sample
    from inspect_ai.model._openai_convert import messages_to_openai
    from inspect_ai.scorer import includes

    @agent
    def my_agent() -> Agent:
        async def execute(state: AgentState) -> AgentState:
            async with agent_bridge(
                state,
                filter=filter,
                response_filter=response_filter,
                retry_refusals=retry_refusals,
            ) as bridge:
                async with AsyncOpenAI(api_key="sk-test") as client:
                    await client.chat.completions.create(
                        model="inspect",
                        messages=await messages_to_openai(state.messages),
                    )
                return bridge.state

        return execute

    @task
    def t() -> Task:
        return Task(
            dataset=[Sample(input="Say hi.", target=target or "")],
            solver=my_agent(),
            scorer=includes() if target is not None else None,
            token_limit=token_limit,
        )

    log = eval(t(), model=model, log_dir=str(tmp_path), display="plain")
    return log[0]


# The only non-Docker check that sandbox_agent_bridge() hands response_filter to
# its bridge; the Docker tests below cover the behavior end to end.
async def test_sandbox_agent_bridge_entry_point_accepts_response_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The sandbox_agent_bridge() async context manager must accept response_filter."""

    async def my_filter(
        model: Model, output: ModelOutput, generate_input: GenerateInput
    ) -> ModelOutput | None:
        return output

    async def fake_run_model_service(
        _sandbox_env: object,
        _web_search: object,
        _code_execution: object,
        _bridge: object,
        _instance: str,
        started: anyio.Event,
    ) -> None:
        started.set()
        await anyio.sleep_forever()

    fake_sandbox = _FakeSandbox()
    monkeypatch.setattr(
        sandbox_bridge_module,
        "sandbox_with_injected_tools",
        AsyncMock(return_value=fake_sandbox),
    )
    monkeypatch.setattr(
        sandbox_bridge_module,
        "run_model_service",
        fake_run_model_service,
    )

    async with sandbox_agent_bridge(response_filter=my_filter) as bridge:
        assert bridge.response_filter is my_filter


def test_response_filter_passthrough(tmp_path: Path) -> None:
    """When response_filter returns None, output is unchanged."""
    call_count = {"n": 0}

    async def my_filter(
        model: Model, output: ModelOutput, generate_input: GenerateInput
    ) -> ModelOutput | None:
        call_count["n"] += 1
        return None

    log = _run_eval_with_filters(tmp_path, response_filter=my_filter)
    assert call_count["n"] == 1
    assert log.samples is not None
    assert log.samples[0].output.completion == MockLLM.default_output


def test_response_filter_replaces_output(tmp_path: Path) -> None:
    """When response_filter returns a ModelOutput, that output is used."""

    async def my_filter(
        model: Model, output: ModelOutput, generate_input: GenerateInput
    ) -> ModelOutput | None:
        return ModelOutput.from_content(model.name, REPLACED_SENTINEL)

    log = _run_eval_with_filters(tmp_path, response_filter=my_filter)
    assert log.samples is not None
    assert log.samples[0].output.completion == REPLACED_SENTINEL


def test_response_filter_edit_reaches_the_scorer(tmp_path: Path) -> None:
    """An output edited in place and returned is what the sample is scored on.

    `ModelOutput.completion` is derived from the message only when the output is
    built, so a filter that edits `output.message` and returns it would otherwise
    leave the sample's completion, and so the score, on the unfiltered text.
    """

    async def editing_filter(
        model: Model, output: ModelOutput, generate_input: GenerateInput
    ) -> ModelOutput | None:
        output.message.content = REPLACED_SENTINEL
        return output

    log = _run_eval_with_filters(
        tmp_path, response_filter=editing_filter, target=REPLACED_SENTINEL
    )
    assert log.samples is not None
    sample = log.samples[0]
    assert sample.output.completion == REPLACED_SENTINEL
    assert sample.scores is not None
    assert sample.scores["includes"].value == "C"


def test_response_filter_cannot_mutate_recorded_model_event(tmp_path: Path) -> None:
    """A mutating filter must not rewrite the provider ModelEvent output."""
    provider_output: ModelOutput | None = None

    async def mutating_filter(
        model: Model, output: ModelOutput, generate_input: GenerateInput
    ) -> ModelOutput | None:
        nonlocal provider_output
        provider_output = output.model_copy(deep=True)
        output.message.content = REPLACED_SENTINEL
        return None

    log = _run_eval_with_filters(tmp_path, response_filter=mutating_filter)

    assert provider_output is not None
    assert log.samples is not None
    model_events = [
        event for event in log.samples[0].events if isinstance(event, ModelEvent)
    ]
    assert len(model_events) == 1
    assert model_events[0].output == provider_output


def test_response_filter_refusal_triggers_retry(tmp_path: Path) -> None:
    """A response_filter returning content_filter triggers a retry."""
    call_log: list[str] = []

    async def my_filter(
        model: Model, output: ModelOutput, generate_input: GenerateInput
    ) -> ModelOutput | None:
        call_log.append(output.stop_reason)
        return ModelOutput.from_content(
            model.name,
            "blocked",
            stop_reason="content_filter",
        )

    _run_eval_with_filters(tmp_path, response_filter=my_filter, retry_refusals=2)
    assert len(call_log) == 3, (
        f"expected 3 filter calls, got {len(call_log)}: {call_log}"
    )


def test_response_filter_can_suppress_refusal(tmp_path: Path) -> None:
    """A response_filter that clears content_filter suppresses retry."""
    call_count = {"n": 0}

    async def my_filter(
        model: Model, output: ModelOutput, generate_input: GenerateInput
    ) -> ModelOutput | None:
        call_count["n"] += 1
        return ModelOutput.from_content(
            model.name,
            "all good",
            stop_reason="stop",
        )

    _run_eval_with_filters(tmp_path, response_filter=my_filter, retry_refusals=5)
    assert call_count["n"] == 1, f"expected 1 filter call, got {call_count['n']}"


def test_response_filter_no_retry_budget(tmp_path: Path) -> None:
    """When retry_refusals is None, content_filter must not loop."""
    call_count = {"n": 0}

    async def my_filter(
        model: Model, output: ModelOutput, generate_input: GenerateInput
    ) -> ModelOutput | None:
        call_count["n"] += 1
        return ModelOutput.from_content(
            model.name,
            "blocked",
            stop_reason="content_filter",
        )

    _run_eval_with_filters(tmp_path, response_filter=my_filter)
    assert call_count["n"] == 1, f"expected 1 call, got {call_count['n']}"


def test_request_and_response_filter_compose(tmp_path: Path) -> None:
    """Request filter runs before model.generate; response filter runs after.

    The response filter sees the inputs the request filter produced: the request
    filter injects a sentinel tool, which must appear in the response filter's
    `GenerateInput.tools`.
    """
    call_order: list[str] = []
    response_seen_tools: list[list[str]] = []
    sentinel_tool = ToolInfo(
        name="sentinel_tool",
        description="injected by request filter",
    )

    async def req_filter(
        model: Model,
        input_messages: list[ChatMessage],
        tool_info: list[ToolInfo],
        tool_choice: ToolChoice | None,
        config: GenerateConfig,
    ) -> GenerateInput:
        call_order.append("request_filter")
        return GenerateInput(input_messages, [sentinel_tool], tool_choice, config)

    async def resp_filter(
        model: Model, output: ModelOutput, generate_input: GenerateInput
    ) -> ModelOutput | None:
        call_order.append("response_filter")
        response_seen_tools.append([t.name for t in generate_input.tools])
        return None

    _run_eval_with_filters(tmp_path, filter=req_filter, response_filter=resp_filter)
    assert call_order == ["request_filter", "response_filter"], (
        f"unexpected ordering: {call_order}"
    )
    assert response_seen_tools == [["sentinel_tool"]], (
        "response_filter must observe the request filter's injected tools; "
        f"saw {response_seen_tools}"
    )


def test_response_filter_runs_on_request_filter_substitute(tmp_path: Path) -> None:
    """An output the request filter substitutes also goes through the response filter.

    `model.generate()` never runs in that case, so there is no ModelEvent.
    """
    seen: list[str] = []

    async def req_filter(
        model: Model,
        input_messages: list[ChatMessage],
        tool_info: list[ToolInfo],
        tool_choice: ToolChoice | None,
        config: GenerateConfig,
    ) -> ModelOutput:
        return ModelOutput.from_content(model.name, "FROM-REQUEST-FILTER")

    async def resp_filter(
        model: Model, output: ModelOutput, generate_input: GenerateInput
    ) -> ModelOutput | None:
        seen.append(output.completion)
        return ModelOutput.from_content(model.name, REPLACED_SENTINEL)

    log = _run_eval_with_filters(
        tmp_path, filter=req_filter, response_filter=resp_filter
    )
    assert seen == ["FROM-REQUEST-FILTER"]
    assert log.samples is not None
    assert log.samples[0].output.completion == REPLACED_SENTINEL
    assert not [e for e in log.samples[0].events if isinstance(e, ModelEvent)]


_SANDBOX_SCAFFOLD_SCRIPT = (
    "import os\n"
    "import time\n"
    "import urllib.error\n"
    "import urllib.request\n"
    "\n"
    "for attempt in range(30):\n"
    "    request = urllib.request.Request(\n"
    "        os.environ['OPENAI_BASE_URL'] + '/chat/completions',\n"
    "        data=os.environ['PAYLOAD'].encode(),\n"
    "        headers={'Content-Type': 'application/json'},\n"
    "    )\n"
    "    try:\n"
    "        print(urllib.request.urlopen(request).read().decode())\n"
    "        break\n"
    "    except urllib.error.URLError:\n"
    "        if attempt == 29:\n"
    "            raise\n"
    "        time.sleep(0.5)\n"
)
"""Scaffold run in the container: one chat completion through the model proxy."""


def _run_sandbox_eval_with_response_filter(
    tmp_path: Path,
    response_filter: ModelResponseFilter,
    *,
    model: str | Model = "mockllm/model",
    token_limit: int | None = None,
) -> tuple[EvalLog, list[ExecResult[str]]]:
    """Run a one-turn sandbox_agent_bridge eval in docker with a response filter.

    Returns the log and the scaffold's exec result (absent if the sample ended
    before the scaffold finished).
    """
    import json

    from inspect_ai import Task, eval, task
    from inspect_ai.agent import Agent, agent
    from inspect_ai.dataset import Sample
    from inspect_ai.util import sandbox

    results: list[ExecResult[str]] = []

    @agent
    def my_agent() -> Agent:
        async def execute(state: AgentState) -> AgentState:
            async with sandbox_agent_bridge(
                state,
                response_filter=response_filter,
            ) as bridge:
                payload = json.dumps(
                    {
                        "model": "inspect",
                        "messages": [{"role": "user", "content": "Say hi."}],
                    }
                )
                result = await sandbox().exec(
                    cmd=["python3", "-c", _SANDBOX_SCAFFOLD_SCRIPT],
                    env={
                        "OPENAI_BASE_URL": "http://localhost:13131/v1",
                        "PAYLOAD": payload,
                    },
                    timeout=30,
                )
                results.append(result)
                return bridge.state

        return execute

    @task
    def t() -> Task:
        return Task(
            dataset=[Sample(input="Say hi.")],
            solver=my_agent(),
            sandbox="docker",
            token_limit=token_limit,
        )

    log = eval(t(), model=model, log_dir=str(tmp_path), display="plain")
    return log[0], results


@skip_if_no_docker
@pytest.mark.slow
def test_sandbox_response_filter_replaces_output(tmp_path: Path) -> None:
    """The response_filter hook fires through the sandbox bridge."""

    async def my_filter(
        model: Model, output: ModelOutput, generate_input: GenerateInput
    ) -> ModelOutput | None:
        return ModelOutput.from_content(model.name, SANDBOX_REPLACED_SENTINEL)

    log, results = _run_sandbox_eval_with_response_filter(tmp_path, my_filter)
    assert len(results) == 1
    assert results[0].success, results[0].stderr
    assert SANDBOX_REPLACED_SENTINEL in results[0].stdout
    assert SANDBOX_REPLACED_SENTINEL in log.model_dump_json()


class _RecordingCompact:
    """Minimal `Compact` implementation that just records what it's given."""

    def __init__(self) -> None:
        self.recorded: list[tuple[list[ChatMessage], ModelOutput]] = []

    async def compact_input(
        self, messages: list[ChatMessage], force: bool = False
    ) -> tuple[list[ChatMessage], None]:
        return messages, None

    async def record_output(
        self, input: list[ChatMessage], output: ModelOutput
    ) -> None:
        self.recorded.append((input, output))


async def test_response_filter_runs_after_compaction_baseline_update() -> None:
    """A replacing filter must not blind compaction to the real generate usage.

    `compact.record_output()` calibrates the compaction token baseline from
    `output.usage`, and early-returns when usage is `None`. A response_filter
    can replace `output` with a synthetic one (e.g. `ModelOutput.from_content()`,
    which carries no usage) -- the filter changes what the scaffold sees, not
    what the generate call actually consumed, so the baseline must be recorded
    from the pre-filter output.
    """
    model = get_model(
        "mockllm/model",
        custom_outputs=[ModelOutput.from_content("mockllm/model", "original")],
    )
    compact = _RecordingCompact()
    bridge = AgentBridge(AgentState(messages=[]))
    bridge._compact = compact

    async def replacing_filter(
        model: Model, output: ModelOutput, generate_input: GenerateInput
    ) -> ModelOutput | None:
        return ModelOutput.from_content(model.name, REPLACED_SENTINEL)

    bridge.response_filter = replacing_filter

    output, _ = await bridge_generate(
        bridge,
        model,
        [ChatMessageUser(content="hello")],
        [],
        None,
        GenerateConfig(),
    )

    # the filter's replacement is what the scaffold gets back
    assert output.completion == REPLACED_SENTINEL
    assert output.usage is None

    # but compaction was calibrated from the real generate call, not the
    # filter's synthetic replacement
    assert len(compact.recorded) == 1
    recorded_output = compact.recorded[0][1]
    assert recorded_output.completion == "original"
    assert recorded_output.usage is not None


async def test_response_filter_exception_fails_sample_in_process() -> None:
    """A raising response_filter must fail the sample, not be swallowed.

    In-process, this means the exception propagates out of `bridge_generate`
    as a `ResponseFilterError` attributing the failure to the filter.
    """
    model = get_model(
        "mockllm/model",
        custom_outputs=[ModelOutput.from_content("mockllm/model", "hi")],
    )
    bridge = AgentBridge(AgentState(messages=[]))

    async def raising_filter(
        model: Model, output: ModelOutput, generate_input: GenerateInput
    ) -> ModelOutput | None:
        raise ValueError("filter is broken")

    bridge.response_filter = raising_filter

    with pytest.raises(ResponseFilterError) as exc_info:
        await bridge_generate(
            bridge,
            model,
            [ChatMessageUser(content="hello")],
            [],
            None,
            GenerateConfig(),
        )
    assert "filter is broken" in str(exc_info.value)
    assert isinstance(exc_info.value.__cause__, ValueError)


# ---------------------------------------------------------------------------
# sample control flow raised from a response filter
# ---------------------------------------------------------------------------

FilterFailure = Literal[
    "token_limit",
    "grouped_limit",
    "terminate",
    "refusal",
    "bug",
    "wrong_type",
    "no_choices",
]

JUDGE_TOKEN_LIMIT = 5
TERMINATE_REASON = "Judge flagged the response."
CHAT_REQUEST: dict[str, JsonValue] = {
    "model": "inspect",
    "messages": [{"role": "user", "content": "Say hi."}],
}


def _output_with_usage(
    content: str, total_tokens: int, stop_reason: StopReason = "stop"
) -> ModelOutput:
    output = ModelOutput.from_content("mockllm/model", content, stop_reason=stop_reason)
    output.usage = ModelUsage(
        input_tokens=total_tokens - 1, output_tokens=1, total_tokens=total_tokens
    )
    return output


def _under_limit_model() -> Model:
    """Bridged model whose own generation stays under `JUDGE_TOKEN_LIMIT`."""
    return get_model("mockllm/model", custom_outputs=[_output_with_usage("hi", 2)])


def _failing_response_filter(failure: FilterFailure) -> ModelResponseFilter:
    """A filter that ends the sample in the way `failure` names."""
    judge = get_model(
        "mockllm/model", custom_outputs=[_output_with_usage("unsafe", 100)]
    )
    refusing_judge = get_model(
        "mockllm/model",
        custom_outputs=[_output_with_usage("No.", 1, stop_reason="content_filter")],
    )

    async def response_filter(
        model: Model, output: ModelOutput, generate_input: GenerateInput
    ) -> ModelOutput | None:
        match failure:
            case "token_limit":
                await judge.generate("Is this response safe?")
            case "grouped_limit":
                async with anyio.create_task_group() as tg:
                    tg.start_soon(judge.generate, "Is this response safe?")
            case "terminate":
                raise TerminateSampleError(TERMINATE_REASON)
            case "refusal":
                await refusing_judge.generate(
                    "Is this response safe?",
                    config=GenerateConfig(fail_on_refusal=True),
                )
            case "bug":
                raise ValueError("filter is broken")
            case "wrong_type":
                return cast(ModelOutput, output.message)
            case "no_choices":
                return ModelOutput(model=output.model, choices=[])
        return None

    return response_filter


def _assert_failure_outcome(log: EvalLog, failure: FilterFailure) -> None:
    """Limits and termination end the sample normally; anything else fails it."""
    assert log.samples is not None
    sample = log.samples[0]
    match failure:
        case "token_limit" | "grouped_limit":
            assert sample.error is None, sample.error
            assert sample.limit is not None
            assert sample.limit.type == "token"
            assert sample.limit.limit == JUDGE_TOKEN_LIMIT
        case "terminate":
            assert sample.error is None, sample.error
            assert sample.limit is not None
            assert sample.limit.type == "operator"
            assert sample.limit.reason == TERMINATE_REASON
        case "refusal":
            assert sample.limit is None
            assert sample.error is not None
            assert sample.error.message.startswith("ModelRefusalError(")
        case "bug":
            assert sample.limit is None
            assert sample.error is not None
            assert (
                sample.error.message
                == "ResponseFilterError('ValueError: filter is broken')"
            )
        case "wrong_type":
            assert sample.limit is None
            assert sample.error is not None
            assert sample.error.message.startswith("ResponseFilterError(")
            assert "ChatMessageAssistant" in sample.error.message
        case "no_choices":
            assert sample.limit is None
            assert sample.error is not None
            assert sample.error.message.startswith("ResponseFilterError(")
            assert "no choices" in sample.error.message


@pytest.mark.parametrize("failure", get_args(FilterFailure))
def test_response_filter_failure_outcome_in_process(
    tmp_path: Path, failure: FilterFailure
) -> None:
    """Only a genuine filter failure is a `ResponseFilterError`.

    A judge call exceeding the sample's token limit (directly or from a task
    group), a termination request, or a judge refusal under `fail_on_refusal`
    is sample control flow and keeps its own outcome. A filter that raises, or
    that returns something other than a `ModelOutput` with choices, fails the
    sample with a `ResponseFilterError`.
    """
    log = _run_eval_with_filters(
        tmp_path,
        response_filter=_failing_response_filter(failure),
        model=_under_limit_model(),
        token_limit=JUDGE_TOKEN_LIMIT,
    )
    _assert_failure_outcome(log, failure)


@skip_if_no_docker
@pytest.mark.slow
@pytest.mark.parametrize("failure", ["token_limit", "terminate", "bug"])
def test_sandbox_response_filter_failure_outcome(
    tmp_path: Path, failure: FilterFailure
) -> None:
    """The sandbox bridge gives filter limits, termination and bugs the same outcomes."""
    log, _ = _run_sandbox_eval_with_response_filter(
        tmp_path,
        _failing_response_filter(failure),
        model=_under_limit_model(),
        token_limit=JUDGE_TOKEN_LIMIT,
    )
    _assert_failure_outcome(log, failure)


def _sandbox_bridge(response_filter: ModelResponseFilter) -> SandboxAgentBridge:
    return SandboxAgentBridge(
        state=AgentState(messages=[]),
        filter=None,
        retry_refusals=None,
        compaction=None,
        port=13131,
        model=None,
        model_aliases={"inspect": _under_limit_model()},
        response_filter=response_filter,
    )


async def test_sandbox_forwarding_preserves_response_filter_limit() -> None:
    """A limit hit in a response filter reaches the sandbox service unchanged.

    Drives the real generate_completions -> bridge_generate -> forwarder path: the
    sandbox service ends the sample on a `LimitExceededError` from a model method,
    whereas a wrapped or forwarded one would fail the sample instead.
    """
    limit_error = LimitExceededError("token", value=102, limit=JUDGE_TOKEN_LIMIT)

    async def over_limit_filter(
        model: Model, output: ModelOutput, generate_input: GenerateInput
    ) -> ModelOutput | None:
        raise limit_error

    bridge = _sandbox_bridge(over_limit_filter)
    generate = _forward_provider_errors(generate_completions(bridge), bridge)
    with pytest.raises(LimitExceededError) as exc_info:
        await generate(CHAT_REQUEST)
    assert exc_info.value is limit_error


@pytest.mark.parametrize(
    "failure, expected, message",
    [
        ("terminate", TerminateSampleError, TERMINATE_REASON),
        ("refusal", ModelRefusalError, "Model refusal"),
        ("bug", ResponseFilterError, "ValueError: filter is broken"),
        ("wrong_type", ResponseFilterError, "ChatMessageAssistant"),
        ("no_choices", ResponseFilterError, "no choices"),
    ],
)
async def test_sandbox_response_filter_ends_sample_through_the_monitor(
    failure: FilterFailure, expected: type[Exception], message: str
) -> None:
    """A filter's termination, refusal or failure reaches the sample runner from the sandbox.

    A re-raise from a sandbox model method would become an RPC error and never
    reach the sample runner, so the forwarder hands the exception to the
    bridge's monitor, which raises it in the agent's task group, while the
    scaffold gets an error reply.
    """
    bridge = _sandbox_bridge(_failing_response_filter(failure))
    reply = await _forward_provider_errors(generate_completions(bridge), bridge)(
        CHAT_REQUEST
    )

    assert PROVIDER_ERROR_KEY in reply
    assert bridge._failure_requested.is_set()
    with pytest.raises(expected, match=message):
        await _monitor_failure(bridge)
