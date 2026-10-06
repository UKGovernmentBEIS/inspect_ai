import json
import re
from pathlib import Path
from typing import Any, Literal, NamedTuple, cast, get_args
from unittest.mock import AsyncMock

import anyio
import pytest
from pydantic import JsonValue
from test_helpers.utils import (
    skip_if_no_anthropic,
    skip_if_no_docker,
    skip_if_no_google,
    skip_if_no_openai,
)
from typing_extensions import assert_never

from inspect_ai._util.content import (
    Content,
    ContentReasoning,
    ContentText,
    ContentToolUse,
)
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
    generate_anthropic,
    generate_completions,
)
from inspect_ai.agent._bridge.sandbox.types import SandboxAgentBridge
from inspect_ai.agent._bridge.types import AgentBridge
from inspect_ai.agent._bridge.util import bridge_generate
from inspect_ai.approval import Approval, ApprovalPolicy, Approver, approver
from inspect_ai.event import ModelEvent
from inspect_ai.log import EvalLog
from inspect_ai.model._call_tools import parse_tool_call
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageUser,
)
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model import (
    GenerateFilter,
    GenerateInput,
    Model,
    ModelRefusalError,
    ModelResponseFilter,
    get_model,
)
from inspect_ai.model._model_output import (
    ChatCompletionChoice,
    ModelOutput,
    ModelUsage,
    StopReason,
)
from inspect_ai.model._providers.anthropic import (
    init_sample_anthropic_assistant_internal,
)
from inspect_ai.model._providers.mockllm import MockLLM
from inspect_ai.tool._tool_call import ToolCall, ToolCallView
from inspect_ai.tool._tool_choice import ToolChoice
from inspect_ai.tool._tool_info import ToolInfo
from inspect_ai.tool._tool_params import ToolParam, ToolParams
from inspect_ai.util import ExecResult, collect, token_limit
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


DictValuedShape = Literal["tool_call_dicts", "choice_dicts"]


def _dict_valued_filter(shape: DictValuedShape) -> ModelResponseFilter:
    """A filter that puts valid plain dicts where models belong."""

    async def response_filter(
        model: Model, output: ModelOutput, generate_input: GenerateInput
    ) -> ModelOutput | None:
        match shape:
            case "tool_call_dicts":
                output.message.tool_calls = cast(
                    list[ToolCall],
                    [{"id": "call_1", "function": "bash", "arguments": {"cmd": "ls"}}],
                )
                return output
            case "choice_dicts":
                return ModelOutput.model_construct(
                    model=output.model,
                    choices=[
                        {
                            "message": {
                                "role": "assistant",
                                "content": REPLACED_SENTINEL,
                            },
                            "stop_reason": "stop",
                        }
                    ],
                )
            case _:
                assert_never(shape)

    return response_filter


@pytest.mark.parametrize("shape", get_args(DictValuedShape))
def test_response_filter_dict_values_are_validated_into_models(
    tmp_path: Path, shape: DictValuedShape
) -> None:
    """A returned output is validated, so valid dicts in it become models."""
    log = _run_eval_with_filters(tmp_path, response_filter=_dict_valued_filter(shape))
    assert log.samples is not None
    sample = log.samples[0]
    assert sample.error is None, sample.error
    match shape:
        case "tool_call_dicts":
            assert sample.output.message.tool_calls is not None
            assert sample.output.message.tool_calls[0].function == "bash"
        case "choice_dicts":
            assert sample.output.completion == REPLACED_SENTINEL
        case _:
            assert_never(shape)


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
    """A response_filter that replaces a refusal suppresses the retry."""
    call_count = {"n": 0}
    refusing_model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.from_content(
                "mockllm/model", "No.", stop_reason="content_filter"
            )
        ]
        * 6,
    )

    async def my_filter(
        model: Model, output: ModelOutput, generate_input: GenerateInput
    ) -> ModelOutput | None:
        call_count["n"] += 1
        return ModelOutput.from_content(
            model.name,
            "all good",
            stop_reason="stop",
        )

    log = _run_eval_with_filters(
        tmp_path, response_filter=my_filter, retry_refusals=5, model=refusing_model
    )
    assert call_count["n"] == 1, f"expected 1 filter call, got {call_count['n']}"
    assert log.samples is not None
    assert log.samples[0].output.completion == "all good"


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


RefusalFilterMode = Literal["replace", "pass_through"]
RefusalSource = Literal["default_generation", "request_filter"]
REFUSAL_RETRY_BUDGETS = [None, 2]


async def _delegating_filter(
    model: Model,
    messages: list[ChatMessage],
    tools: list[ToolInfo],
    tool_choice: ToolChoice | None,
    config: GenerateConfig,
) -> ModelOutput:
    """A request filter that makes the generation itself."""
    return await model.generate(
        messages, tools=tools, tool_choice=tool_choice, config=config
    )


def _refusal_request_filter(source: RefusalSource) -> GenerateFilter | None:
    match source:
        case "default_generation":
            return None
        case "request_filter":
            return _delegating_filter
        case _:
            assert_never(source)


def _fail_on_refusal_model() -> Model:
    """A model that always refuses, with `fail_on_refusal` set in its config."""
    return get_model(
        "mockllm/model",
        config=GenerateConfig(fail_on_refusal=True),
        custom_outputs=[
            ModelOutput.from_content(
                "mockllm/model", "No.", stop_reason="content_filter"
            )
        ]
        * 4,
    )


def _refusal_filter(mode: RefusalFilterMode, seen: list[str]) -> ModelResponseFilter:
    """A filter that records each stop reason and replaces or keeps the output."""

    async def response_filter(
        model: Model, output: ModelOutput, generate_input: GenerateInput
    ) -> ModelOutput | None:
        seen.append(output.stop_reason)
        match mode:
            case "replace":
                return ModelOutput.from_content(model.name, REPLACED_SENTINEL)
            case "pass_through":
                return None
            case _:
                assert_never(mode)

    return response_filter


def _expected_refusal_filter_calls(
    mode: RefusalFilterMode, retry_refusals: int | None
) -> list[str]:
    match mode:
        case "replace":
            return ["content_filter"]
        case "pass_through":
            return ["content_filter"] * (1 + (retry_refusals or 0))
        case _:
            assert_never(mode)


@pytest.mark.parametrize("source", get_args(RefusalSource))
@pytest.mark.parametrize("retry_refusals", REFUSAL_RETRY_BUDGETS)
@pytest.mark.parametrize("mode", get_args(RefusalFilterMode))
def test_response_filter_sees_refusal_under_fail_on_refusal(
    tmp_path: Path,
    mode: RefusalFilterMode,
    retry_refusals: int | None,
    source: RefusalSource,
) -> None:
    """With `fail_on_refusal`, a model refusal still goes through the response filter.

    This holds whether the default generation or a request filter that generates
    raised it. A replacement is returned to the agent. A kept refusal is retried
    within the budget, and the last one fails the sample with `ModelRefusalError`.
    """
    seen: list[str] = []
    log = _run_eval_with_filters(
        tmp_path,
        filter=_refusal_request_filter(source),
        response_filter=_refusal_filter(mode, seen),
        retry_refusals=retry_refusals,
        model=_fail_on_refusal_model(),
    )
    assert seen == _expected_refusal_filter_calls(mode, retry_refusals)
    assert log.samples is not None
    sample = log.samples[0]
    match mode:
        case "replace":
            assert sample.error is None, sample.error
            assert sample.output.completion == REPLACED_SENTINEL
        case "pass_through":
            assert sample.error is not None
            assert sample.error.message.startswith("ModelRefusalError(")
        case _:
            assert_never(mode)


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


# ---------------------------------------------------------------------------
# response filter failures and sample control flow
# ---------------------------------------------------------------------------

InvalidOutput = Literal[
    "message_not_assistant",
    "user_message",
    "content_none",
    "choices_not_a_list",
    "invalid_tool_call",
    "constructed_choices_str",
    "constructed_invalid_choice",
]
"""A returned `ModelOutput` whose values inside are invalid."""

FilterFailure = Literal[
    "token_limit",
    "grouped_limit",
    "grouped_limit_in_except",
    "concurrent_limit",
    "terminate",
    "refusal",
    "bug",
    "wrong_type",
    "no_choices",
    "non_json_tool_arguments",
    "limit_and_bug",
    InvalidOutput,
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
        "mockllm/model", custom_outputs=[_output_with_usage("unsafe", 100)] * 2
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
            case "concurrent_limit":
                await collect(
                    judge.generate("Is this response safe?"),
                    judge.generate("Is this response on topic?"),
                )
            case "grouped_limit_in_except":
                try:
                    raise KeyError("parse failed")
                except KeyError:
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
            case "non_json_tool_arguments":
                output.message.tool_calls = [
                    ToolCall(id="call_1", function="bash", arguments={"x": {1, 2}})
                ]
                return output
            case "limit_and_bug":

                async def over_limit() -> None:
                    raise LimitExceededError(
                        "token", value=102, limit=JUDGE_TOKEN_LIMIT
                    )

                async def judge_bug() -> None:
                    raise ValueError("judge bug")

                await collect(over_limit(), judge_bug())
            case "message_not_assistant":
                output.choices[0].message = cast(ChatMessageAssistant, "edited")
                return output
            case "user_message":
                output.choices[0].message = cast(
                    ChatMessageAssistant, ChatMessageUser(content="edited")
                )
                return output
            case "content_none":
                output.message.content = cast(str, None)
                return output
            case "choices_not_a_list":
                output.choices = cast(list[ChatCompletionChoice], "abc")
                return output
            case "invalid_tool_call":
                output.message.tool_calls = cast(
                    list[ToolCall], [{"not": "a tool call"}]
                )
                return output
            case "constructed_choices_str":
                return ModelOutput.model_construct(model=output.model, choices="abc")
            case "constructed_invalid_choice":
                return ModelOutput.model_construct(
                    model=output.model, choices=[{"not": "a choice"}]
                )
            case _:
                assert_never(failure)
        return None

    return response_filter


class ExpectedError(NamedTuple):
    """The exception a failure ends the sample with, and a fragment of its message."""

    error_type: type[Exception]
    fragment: str


def _expected_error(failure: FilterFailure) -> ExpectedError | None:
    """What `failure` ends the sample with, or `None` for the token limit."""
    match failure:
        case (
            "token_limit"
            | "grouped_limit"
            | "grouped_limit_in_except"
            | "concurrent_limit"
        ):
            return None
        case "terminate":
            return ExpectedError(TerminateSampleError, TERMINATE_REASON)
        case "refusal":
            return ExpectedError(ModelRefusalError, "Model refusal")
        case "bug":
            return ExpectedError(ResponseFilterError, "ValueError: filter is broken")
        case "wrong_type":
            return ExpectedError(ResponseFilterError, "ChatMessageAssistant")
        case "no_choices":
            return ExpectedError(ResponseFilterError, "no choices")
        case "non_json_tool_arguments":
            return ExpectedError(ResponseFilterError, "not JSON-serializable")
        case "limit_and_bug":
            return ExpectedError(ResponseFilterError, "ExceptionGroup")
        case (
            "message_not_assistant"
            | "user_message"
            | "content_none"
            | "choices_not_a_list"
            | "invalid_tool_call"
            | "constructed_choices_str"
            | "constructed_invalid_choice"
        ):
            return ExpectedError(ResponseFilterError, "invalid ModelOutput")
        case _:
            assert_never(failure)


def _assert_failure_outcome(log: EvalLog, failure: FilterFailure) -> None:
    """Limits and termination end the sample normally; anything else fails it."""
    assert log.samples is not None
    sample = log.samples[0]
    expected = _expected_error(failure)
    if expected is None:
        assert sample.error is None, sample.error
        assert sample.limit is not None
        assert sample.limit.type == "token"
        assert sample.limit.limit == JUDGE_TOKEN_LIMIT
    elif expected.error_type is TerminateSampleError:
        assert sample.error is None, sample.error
        assert sample.limit is not None
        assert sample.limit.type == "operator"
        assert sample.limit.reason == expected.fragment
    else:
        assert sample.limit is None
        assert sample.error is not None
        assert sample.error.message.startswith(f"{expected.error_type.__name__}(")
        assert expected.fragment in sample.error.message


@pytest.mark.parametrize("failure", get_args(FilterFailure))
def test_response_filter_failure_outcome_in_process(
    tmp_path: Path, failure: FilterFailure
) -> None:
    """Only a genuine filter failure is a `ResponseFilterError`.

    A judge call exceeding the sample's token limit (directly or from a task
    group, also one entered while handling another exception), a termination
    request, or a judge refusal under `fail_on_refusal` is sample control flow
    and keeps its own outcome. A filter that raises, or that returns anything
    but a valid `ModelOutput` with choices, fails the sample with a
    `ResponseFilterError`.
    """
    log = _run_eval_with_filters(
        tmp_path,
        response_filter=_failing_response_filter(failure),
        model=_under_limit_model(),
        token_limit=JUDGE_TOKEN_LIMIT,
    )
    _assert_failure_outcome(log, failure)


async def test_response_filter_error_keeps_the_filter_exception_as_cause() -> None:
    """The `ResponseFilterError` keeps what the filter raised as its `__cause__`."""
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
    assert isinstance(exc_info.value.__cause__, ValueError)


@skip_if_no_docker
@pytest.mark.slow
@pytest.mark.parametrize(
    "failure",
    [
        "token_limit",
        "concurrent_limit",
        "terminate",
        "bug",
        "message_not_assistant",
        "non_json_tool_arguments",
        "limit_and_bug",
    ],
)
def test_sandbox_response_filter_failure_outcome(
    tmp_path: Path, failure: FilterFailure
) -> None:
    """The sandbox bridge gives filter limits, termination and failures the same outcomes."""
    log, _ = _run_sandbox_eval_with_response_filter(
        tmp_path,
        _failing_response_filter(failure),
        model=_under_limit_model(),
        token_limit=JUDGE_TOKEN_LIMIT,
    )
    _assert_failure_outcome(log, failure)


def _sandbox_bridge(
    response_filter: ModelResponseFilter,
    model: Model | None = None,
    retry_refusals: int | None = None,
    filter: GenerateFilter | None = None,
) -> SandboxAgentBridge:
    return SandboxAgentBridge(
        state=AgentState(messages=[]),
        filter=filter,
        retry_refusals=retry_refusals,
        compaction=None,
        port=13131,
        model=None,
        model_aliases={"inspect": model or _under_limit_model()},
        response_filter=response_filter,
    )


async def test_sandbox_identity_filter_keeps_provider_tool_arguments() -> None:
    """Only arguments the filter changed must be JSON-serializable.

    `parse_tool_call`'s YAML fallback turns a bare `2024-01-01` into a `date`, which
    the Anthropic dialect renders. A filter that returns the output unchanged must
    not fail a sample that would pass without it.
    """
    events_tool = ToolInfo(
        name="get_events",
        description="List events on a date.",
        parameters=ToolParams(properties={"date": ToolParam(type="string")}),
    )
    provider_call = parse_tool_call("call_1", "get_events", "2024-01-01", [events_tool])
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput(
                model="mockllm/model",
                choices=[
                    ChatCompletionChoice(
                        message=ChatMessageAssistant(
                            content="", tool_calls=[provider_call]
                        ),
                        stop_reason="tool_calls",
                    )
                ],
            )
        ],
    )

    async def identity_filter(
        model: Model, output: ModelOutput, generate_input: GenerateInput
    ) -> ModelOutput | None:
        return output

    bridge = _sandbox_bridge(identity_filter, model)
    reply = await _forward_provider_errors(
        generate_anthropic(None, None, bridge), bridge
    )({"model": "inspect", "max_tokens": 1024, "messages": CHAT_REQUEST["messages"]})

    assert PROVIDER_ERROR_KEY not in reply
    assert not bridge._failure_requested.is_set()
    tool_use = cast(list[dict[str, JsonValue]], reply["content"])[-1]
    assert tool_use["input"] == {"date": "2024-01-01"}


async def test_sandbox_forwarding_preserves_response_filter_limit() -> None:
    """A limit hit in a response filter reaches the sandbox service unchanged.

    Drives the real generate_completions -> bridge_generate -> forwarder path: the
    sandbox service ends the sample on a `LimitExceededError` from a model method,
    whereas a wrapped one would fail the sample, and one returned as an error reply
    would leave it running.
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
    "failure", [f for f in get_args(FilterFailure) if _expected_error(f) is not None]
)
async def test_sandbox_response_filter_ends_sample_through_the_monitor(
    failure: FilterFailure,
) -> None:
    """A filter's termination, refusal or failure reaches the sample runner from the sandbox.

    A re-raise from a sandbox model method would become an RPC error and never
    reach the sample runner, so the forwarder hands the exception to the
    bridge's monitor, which raises it in the agent's task group, while the
    scaffold gets an error reply.
    """
    expected = _expected_error(failure)
    assert expected is not None
    bridge = _sandbox_bridge(_failing_response_filter(failure))
    reply = await _forward_provider_errors(generate_completions(bridge), bridge)(
        CHAT_REQUEST
    )

    assert PROVIDER_ERROR_KEY in reply
    assert bridge._failure_requested.is_set()
    with pytest.raises(expected.error_type, match=re.escape(expected.fragment)):
        await _monitor_failure(bridge)


@pytest.mark.parametrize("source", get_args(RefusalSource))
@pytest.mark.parametrize("retry_refusals", REFUSAL_RETRY_BUDGETS)
@pytest.mark.parametrize("mode", get_args(RefusalFilterMode))
async def test_sandbox_response_filter_sees_refusal_under_fail_on_refusal(
    mode: RefusalFilterMode, retry_refusals: int | None, source: RefusalSource
) -> None:
    """The sandbox bridge passes a `fail_on_refusal` refusal through the response filter.

    Compaction is calibrated from each refused output, as for any other output.
    A kept refusal reaches the sample runner through the bridge's monitor.
    """
    seen: list[str] = []
    bridge = _sandbox_bridge(
        _refusal_filter(mode, seen),
        _fail_on_refusal_model(),
        retry_refusals,
        _refusal_request_filter(source),
    )
    compact = _RecordingCompact()
    bridge._compact = compact
    reply = await _forward_provider_errors(generate_completions(bridge), bridge)(
        CHAT_REQUEST
    )

    assert seen == _expected_refusal_filter_calls(mode, retry_refusals)
    assert [output.stop_reason for _, output in compact.recorded] == seen
    match mode:
        case "replace":
            assert PROVIDER_ERROR_KEY not in reply
            assert not bridge._failure_requested.is_set()
            choices = cast(list[dict[str, JsonValue]], reply["choices"])
            message = cast(dict[str, JsonValue], choices[0]["message"])
            assert message["content"] == REPLACED_SENTINEL
        case "pass_through":
            assert PROVIDER_ERROR_KEY in reply
            assert bridge._failure_requested.is_set()
            with pytest.raises(ModelRefusalError):
                await _monitor_failure(bridge)
        case _:
            assert_never(mode)


async def test_response_filter_runs_under_bridge_approval_policies() -> None:
    """Model calls a response filter makes see the bridge's approval policies.

    The bridge applies them to its request filter for the same reason: an active
    policy is what refuses remote MCP servers the provider would run unapproved.
    """
    from inspect_ai.approval import ApprovalPolicy, auto_approver
    from inspect_ai.approval._apply import have_tool_approval

    seen: list[bool] = []

    async def checking_filter(
        model: Model, output: ModelOutput, generate_input: GenerateInput
    ) -> ModelOutput | None:
        seen.append(have_tool_approval())
        return None

    bridge = AgentBridge(
        AgentState(messages=[]),
        approval=[ApprovalPolicy(auto_approver(), "*")],
        response_filter=checking_filter,
    )
    await bridge_generate(
        bridge,
        get_model("mockllm/model"),
        [ChatMessageUser(content="hello")],
        [],
        None,
        GenerateConfig(),
    )
    assert seen == [True]


BridgePath = Literal["in_process", "sandbox"]


@pytest.mark.parametrize("path", get_args(BridgePath))
@pytest.mark.parametrize(
    "failure", [f for f in get_args(FilterFailure) if _expected_error(f) is None]
)
async def test_response_filter_limit_propagates(
    failure: FilterFailure, path: BridgePath
) -> None:
    """A limit a response filter hits, also from a task group, leaves the bridge unwrapped.

    Async, so it also runs under Trio, whose task groups and cancellation differ.
    """
    response_filter = _failing_response_filter(failure)
    with token_limit(JUDGE_TOKEN_LIMIT):
        with pytest.raises(LimitExceededError) as exc_info:
            match path:
                case "in_process":
                    bridge = AgentBridge(AgentState(messages=[]))
                    bridge.response_filter = response_filter
                    await bridge_generate(
                        bridge,
                        _under_limit_model(),
                        [ChatMessageUser(content="hello")],
                        [],
                        None,
                        GenerateConfig(),
                    )
                case "sandbox":
                    sandbox_bridge = _sandbox_bridge(response_filter)
                    await _forward_provider_errors(
                        generate_completions(sandbox_bridge), sandbox_bridge
                    )(CHAT_REQUEST)
                case _:
                    assert_never(path)
    assert exc_info.value.type == "token"
    assert exc_info.value.limit == JUDGE_TOKEN_LIMIT


# ---------------------------------------------------------------------------
# provider-owned content: edits a dialect would replay over
# ---------------------------------------------------------------------------

THINKING_BLOCK: dict[str, Any] = {
    "type": "thinking",
    "thinking": "I should search for the scores.",
    "signature": "SIGNATURE",
}
CE_ID = "srvtoolu_011"
WS_ID = "srvtoolu_014"
NESTED_SEARCH_BLOCKS: list[dict[str, Any]] = [
    THINKING_BLOCK,
    {"type": "text", "text": "Let me search for that."},
    {
        "type": "server_tool_use",
        "id": CE_ID,
        "name": "code_execution",
        "input": {"code": "results = web_search('nhl scores')"},
        "caller": {"type": "direct"},
    },
    {
        "type": "server_tool_use",
        "id": WS_ID,
        "name": "web_search",
        "input": {"query": "nhl scores last night"},
        "caller": {"type": "code_execution_20260120", "tool_id": CE_ID},
    },
    {
        "type": "web_search_tool_result",
        "tool_use_id": WS_ID,
        "content": [
            {
                "type": "web_search_result",
                "title": "NHL Scores",
                "url": "https://nhl.com/scores",
                "encrypted_content": "ENCRYPTED_CONTENT",
            }
        ],
        "caller": {"type": "code_execution_20260120", "tool_id": CE_ID},
    },
    {
        "type": "code_execution_tool_result",
        "tool_use_id": CE_ID,
        "content": {
            "type": "encrypted_code_execution_result",
            "encrypted_stdout": "ENCRYPTED_STDOUT",
            "return_code": 0,
            "stderr": "",
            "content": [],
        },
    },
    {"type": "text", "text": "The Bruins won 3-2."},
]
"""A thinking block, a web search nested in code execution, and text."""


async def _anthropic_output(
    blocks: list[dict[str, Any]],
    tools: list[ToolInfo] | None = None,
    stop_reason: str = "end_turn",
) -> ModelOutput:
    """Parse an Anthropic response, recording its replay state for this sample."""
    from anthropic.types import Message

    from inspect_ai.model._providers.anthropic import model_output_from_message

    message = Message.model_validate(
        {
            "id": "msg_01",
            "type": "message",
            "role": "assistant",
            "model": "claude-opus-4-8",
            "content": blocks,
            "stop_reason": stop_reason,
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }
    )
    output, _ = await model_output_from_message(
        client=None, model="claude-opus-4-8", message=message, tools=tools or []
    )
    return output


async def _render_anthropic(message: ChatMessageAssistant) -> list[dict[str, Any]]:
    from inspect_ai.model._providers.anthropic import assistant_message_block_params

    return cast(list[dict[str, Any]], await assistant_message_block_params(message))


ProviderOwnedEdit = Literal[
    "edit_search_arguments",
    "edit_code_execution_result",
    "edit_thinking",
    "add_server_tool_use",
    "drop_search_keep_code_execution",
]


def _content_items(output: ModelOutput) -> list[Content]:
    assert isinstance(output.message.content, list)
    return output.message.content


def _provider_owned_edit(edit: ProviderOwnedEdit) -> ModelResponseFilter:
    """A filter that makes an edit Anthropic would replay over."""

    async def response_filter(
        model: Model, output: ModelOutput, generate_input: GenerateInput
    ) -> ModelOutput | None:
        content = _content_items(output)
        tool_uses = {c.id: c for c in content if isinstance(c, ContentToolUse)}
        match edit:
            case "edit_search_arguments":
                tool_uses[WS_ID].arguments = '{"query": "edited"}'
            case "edit_code_execution_result":
                tool_uses[CE_ID].result = "edited"
            case "edit_thinking":
                reasoning = next(c for c in content if isinstance(c, ContentReasoning))
                reasoning.summary = "edited"
            case "add_server_tool_use":
                content.append(
                    ContentToolUse(
                        tool_type="mcp_call",
                        id="mcptoolu_01",
                        name="lookup",
                        context="docs",
                        arguments="{}",
                        result="added",
                    )
                )
            case "drop_search_keep_code_execution":
                content.remove(tool_uses[WS_ID])
            case _:
                assert_never(edit)
        return output

    return response_filter


@pytest.mark.parametrize("edit", get_args(ProviderOwnedEdit))
async def test_response_filter_rejects_edits_to_provider_owned_content(
    edit: ProviderOwnedEdit,
) -> None:
    """Edits to reasoning or server tool items fail rather than being replayed over.

    Anthropic renders signed thinking and server tool spans from its replay
    records, so these edits would reach the agent as the original content (and a
    partly removed span would come back whole) while bridge state kept the edit.
    """
    init_sample_anthropic_assistant_internal()
    provider_output = await _anthropic_output(NESTED_SEARCH_BLOCKS)
    model = get_model("mockllm/model", custom_outputs=[provider_output])
    bridge = AgentBridge(AgentState(messages=[]))
    bridge.response_filter = _provider_owned_edit(edit)

    with pytest.raises(ResponseFilterError):
        await bridge_generate(
            bridge, model, [ChatMessageUser(content="hi")], [], None, GenerateConfig()
        )


ProviderOwnedKeep = Literal["unchanged", "edit_text", "drop_server_tools"]


def _provider_owned_keep(keep: ProviderOwnedKeep) -> ModelResponseFilter:
    async def response_filter(
        model: Model, output: ModelOutput, generate_input: GenerateInput
    ) -> ModelOutput | None:
        content = _content_items(output)
        match keep:
            case "unchanged":
                pass
            case "edit_text":
                text = next(c for c in content if isinstance(c, ContentText))
                text.text = REPLACED_SENTINEL
            case "drop_server_tools":
                output.message.content = [
                    c for c in content if not isinstance(c, ContentToolUse)
                ]
            case _:
                assert_never(keep)
        return output

    return response_filter


@pytest.mark.parametrize("keep", get_args(ProviderOwnedKeep))
async def test_response_filter_keeps_provider_owned_content_it_can_render(
    keep: ProviderOwnedKeep,
) -> None:
    """Unchanged or wholly removed provider-owned items render as the filter left them."""
    init_sample_anthropic_assistant_internal()
    provider_output = await _anthropic_output(NESTED_SEARCH_BLOCKS)
    provider_before = provider_output.model_copy(deep=True)
    original_blocks = await _render_anthropic(provider_output.message)
    model = get_model("mockllm/model", custom_outputs=[provider_output])
    bridge = AgentBridge(AgentState(messages=[]))
    bridge.response_filter = _provider_owned_keep(keep)

    output, _ = await bridge_generate(
        bridge, model, [ChatMessageUser(content="hi")], [], None, GenerateConfig()
    )
    blocks = await _render_anthropic(output.message)

    server_block_types = {
        "server_tool_use",
        "web_search_tool_result",
        "code_execution_tool_result",
    }
    match keep:
        case "unchanged":
            assert blocks == original_blocks
        case "edit_text":
            assert [b for b in blocks if b["type"] in server_block_types] == [
                b for b in original_blocks if b["type"] in server_block_types
            ]
            assert REPLACED_SENTINEL in [b.get("text") for b in blocks]
        case "drop_server_tools":
            assert [b for b in blocks if b["type"] in server_block_types] == []
            assert blocks == [
                b for b in original_blocks if b["type"] not in server_block_types
            ]
        case _:
            assert_never(keep)
    # the provider's own output is untouched
    assert provider_output.message == provider_before.message
    assert await _render_anthropic(provider_output.message) == original_blocks


PENDING_CODE = "print(20240101)"
PENDING_SPAN_BLOCKS: dict[str, list[dict[str, Any]]] = {
    "pending_only": [],
    "completed_and_pending": [
        {
            "type": "server_tool_use",
            "id": "srvtoolu_ws",
            "name": "web_search",
            "input": {"query": "nhl scores"},
            "caller": {"type": "direct"},
        },
        {
            "type": "web_search_tool_result",
            "tool_use_id": "srvtoolu_ws",
            "content": [
                {
                    "type": "web_search_result",
                    "title": "NHL Scores",
                    "url": "https://nhl.com/scores",
                    "encrypted_content": "ENCRYPTED_CONTENT",
                }
            ],
            "caller": {"type": "direct"},
        },
    ],
}
"""Server work before a code execution still pending when the turn ended."""


async def _pending_span_output(spans: str) -> ModelOutput:
    """A turn ending on a client tool call while a code execution is pending."""
    return await _anthropic_output(
        [
            {"type": "text", "text": "Checking."},
            *PENDING_SPAN_BLOCKS[spans],
            {
                "type": "server_tool_use",
                "id": "srvtoolu_pending",
                "name": "code_execution",
                "input": {"code": PENDING_CODE},
                "caller": {"type": "direct"},
            },
            {
                "type": "tool_use",
                "id": "toolu_client",
                "name": "lookup",
                "input": {"q": "x"},
            },
        ],
        [ToolInfo(name="lookup", description="Look something up.")],
        stop_reason="tool_use",
    )


async def _text_only_filter(
    model: Model, output: ModelOutput, generate_input: GenerateInput
) -> ModelOutput | None:
    """Edit the output in place down to one text item, keeping its message id."""
    output.message.content = [ContentText(text=REPLACED_SENTINEL)]
    output.message.tool_calls = None
    output.choices[0].stop_reason = "stop"
    return output


async def _identity_filter(
    model: Model, output: ModelOutput, generate_input: GenerateInput
) -> ModelOutput | None:
    return output


@pytest.mark.parametrize("path", get_args(BridgePath))
@pytest.mark.parametrize("replace", [False, True], ids=["unchanged", "replaced"])
@pytest.mark.parametrize("spans", list(PENDING_SPAN_BLOCKS))
async def test_response_filter_replacement_drops_pending_server_work(
    spans: str, replace: bool, path: BridgePath
) -> None:
    """Pending server work reaches the agent only with the output it belongs to.

    Anthropic replays a code execution still pending at the end of a turn by
    message id, since it has no content item. A replacement must not carry it
    along; an unchanged output still does.
    """
    init_sample_anthropic_assistant_internal()
    provider_output = await _pending_span_output(spans)
    original_blocks = await _render_anthropic(provider_output.message)
    assert PENDING_CODE in json.dumps(original_blocks)
    model = get_model("mockllm/model", custom_outputs=[provider_output])
    response_filter = _text_only_filter if replace else _identity_filter

    blocks: list[dict[str, Any]]
    match path:
        case "in_process":
            bridge = AgentBridge(AgentState(messages=[]))
            bridge.response_filter = response_filter
            output, _ = await bridge_generate(
                bridge,
                model,
                [ChatMessageUser(content="hi")],
                [],
                None,
                GenerateConfig(),
            )
            blocks = await _render_anthropic(output.message)
            state_output = output
        case "sandbox":
            sandbox_bridge = _sandbox_bridge(response_filter, model)
            reply = await _forward_provider_errors(
                generate_anthropic(None, None, sandbox_bridge), sandbox_bridge
            )(
                {
                    "model": "inspect",
                    "max_tokens": 1024,
                    "messages": CHAT_REQUEST["messages"],
                }
            )
            assert PROVIDER_ERROR_KEY not in reply
            blocks = cast(list[dict[str, Any]], reply["content"])
            state_output = sandbox_bridge.state.output
        case _:
            assert_never(path)

    if replace:
        assert [(b["type"], b.get("text")) for b in blocks] == [
            ("text", REPLACED_SENTINEL)
        ]
        assert state_output.message.content == [ContentText(text=REPLACED_SENTINEL)]
    else:
        assert PENDING_CODE in json.dumps(blocks)
        assert [b["type"] for b in blocks] == [b["type"] for b in original_blocks]
    # the provider's output and its replay record are untouched
    assert await _render_anthropic(provider_output.message) == original_blocks


class NativeTool(NamedTuple):
    """A tool Anthropic calls by its own name, and the Inspect tool it maps to."""

    wire_name: str
    inspect_name: str
    arguments: dict[str, Any]


NATIVE_TOOLS = [
    NativeTool("computer", "computer", {"action": "screenshot"}),
    NativeTool("bash", "bash_session", {"command": "ls"}),
    NativeTool("str_replace_editor", "text_editor", {"command": "view", "path": "/"}),
    NativeTool(
        "str_replace_based_edit_tool", "text_editor", {"command": "view", "path": "/"}
    ),
]


@approver
def _recording_approver(seen: list[str]) -> Approver:
    async def approve(
        message: str, call: ToolCall, view: ToolCallView, history: list[ChatMessage]
    ) -> Approval:
        seen.append(call.function)
        return Approval(decision="approve")

    return approve


@pytest.mark.parametrize("new_id", [False, True], ids=["same_id", "new_id"])
@pytest.mark.parametrize("native", NATIVE_TOOLS, ids=lambda n: n.wire_name)
async def test_sandbox_response_filter_renamed_native_call(
    native: NativeTool, new_id: bool
) -> None:
    """A renamed call reaches the agent under the name approval reviewed.

    Anthropic renders a native tool's wire name by call id, so a call that keeps
    its id would go out under the original native name. Keeping the id while
    changing the function fails the sample; a new id renders the new function.
    """
    init_sample_anthropic_assistant_internal()
    provider_output = await _anthropic_output(
        [
            {
                "type": "tool_use",
                "id": "toolu_01",
                "name": native.wire_name,
                "input": native.arguments,
            }
        ],
        [ToolInfo(name=native.inspect_name, description="native tool")],
    )
    assert provider_output.message.tool_calls is not None
    assert provider_output.message.tool_calls[0].function == native.inspect_name

    async def renaming_filter(
        model: Model, output: ModelOutput, generate_input: GenerateInput
    ) -> ModelOutput | None:
        assert output.message.tool_calls is not None
        call = output.message.tool_calls[0]
        call.function = "safe_echo"
        call.arguments = {"text": "hi"}
        if new_id:
            call.id = "toolu_02"
        return output

    approved: list[str] = []
    bridge = SandboxAgentBridge(
        state=AgentState(messages=[]),
        filter=None,
        retry_refusals=None,
        compaction=None,
        port=13131,
        model=None,
        model_aliases={
            "inspect": get_model("mockllm/model", custom_outputs=[provider_output])
        },
        approval=[ApprovalPolicy(_recording_approver(approved), "*")],
        response_filter=renaming_filter,
    )
    reply = await _forward_provider_errors(
        generate_anthropic(None, None, bridge), bridge
    )({"model": "inspect", "max_tokens": 1024, "messages": CHAT_REQUEST["messages"]})

    if new_id:
        assert PROVIDER_ERROR_KEY not in reply
        tool_use = cast(list[dict[str, JsonValue]], reply["content"])[-1]
        assert tool_use["name"] == "safe_echo"
        assert approved == ["safe_echo"]
        assert bridge.state.output.message.tool_calls is not None
        assert bridge.state.output.message.tool_calls[0].function == "safe_echo"
    else:
        assert PROVIDER_ERROR_KEY in reply
        assert approved == []
        with pytest.raises(ResponseFilterError, match="new id"):
            await _monitor_failure(bridge)


# ---------------------------------------------------------------------------
# live providers: each bridge dialect with a replacing and a tool-call filter
# ---------------------------------------------------------------------------

LiveFilterMode = Literal["replace", "tool_call"]
LiveDialect = Literal["completions", "responses", "anthropic", "google"]

FILTERED_LOCATION = "8A2F6C1D-filtered-location"
WEATHER_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {"location": {"type": "string", "description": "A city."}},
    "required": ["location"],
}
WEATHER_DESCRIPTION = "Get the current weather in a given location"


class ClientReply(NamedTuple):
    """What the bridged client received: its text and each tool call's arguments."""

    text: str
    tool_arguments: list[dict[str, Any]]


async def _call_bridged_client(
    dialect: LiveDialect, prompt: str, tools: bool
) -> ClientReply:
    """Make one request through the bridge with the dialect's own SDK."""
    params: dict[str, Any] = {}
    match dialect:
        case "completions":
            from openai import AsyncOpenAI
            from openai.types.chat import ChatCompletion

            if tools:
                params["tools"] = [
                    {
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "description": WEATHER_DESCRIPTION,
                            "parameters": WEATHER_PARAMETERS,
                        },
                    }
                ]
                params["tool_choice"] = "required"
            async with AsyncOpenAI(api_key="inspect") as client:
                completion = cast(
                    ChatCompletion,
                    await client.chat.completions.create(
                        model="inspect",
                        messages=[{"role": "user", "content": prompt}],
                        **params,
                    ),
                )
            message = completion.choices[0].message
            return ClientReply(
                message.content or "",
                [
                    json.loads(call.function.arguments)
                    for call in message.tool_calls or []
                    if call.type == "function"
                ],
            )
        case "responses":
            from openai import AsyncOpenAI
            from openai.types.responses import Response

            if tools:
                params["tools"] = [
                    {
                        "type": "function",
                        "name": "get_weather",
                        "description": WEATHER_DESCRIPTION,
                        "parameters": WEATHER_PARAMETERS,
                        "strict": False,
                    }
                ]
                params["tool_choice"] = "required"
            async with AsyncOpenAI(api_key="inspect") as client:
                response = cast(
                    Response,
                    await client.responses.create(
                        model="inspect", input=prompt, **params
                    ),
                )
            return ClientReply(
                response.output_text,
                [
                    json.loads(item.arguments)
                    for item in response.output
                    if item.type == "function_call"
                ],
            )
        case "anthropic":
            from anthropic import AsyncAnthropic
            from anthropic.types import Message

            if tools:
                params["tools"] = [
                    {
                        "name": "get_weather",
                        "description": WEATHER_DESCRIPTION,
                        "input_schema": WEATHER_PARAMETERS,
                    }
                ]
                params["tool_choice"] = {"type": "any"}
            async with AsyncAnthropic(api_key="inspect") as anthropic_client:
                anthropic_message = cast(
                    Message,
                    await anthropic_client.messages.create(
                        model="inspect",
                        max_tokens=1024,
                        messages=[{"role": "user", "content": prompt}],
                        **params,
                    ),
                )
            return ClientReply(
                "".join(
                    block.text
                    for block in anthropic_message.content
                    if block.type == "text"
                ),
                [
                    cast(dict[str, Any], block.input)
                    for block in anthropic_message.content
                    if block.type == "tool_use"
                ],
            )
        case "google":
            from google import genai

            config = genai.types.GenerateContentConfig()
            if tools:
                config.tools = [
                    genai.types.Tool(
                        function_declarations=[
                            genai.types.FunctionDeclaration(
                                name="get_weather",
                                description=WEATHER_DESCRIPTION,
                                parameters_json_schema=WEATHER_PARAMETERS,
                            )
                        ]
                    )
                ]
                config.tool_config = genai.types.ToolConfig(
                    function_calling_config=genai.types.FunctionCallingConfig(
                        mode=genai.types.FunctionCallingConfigMode.ANY
                    )
                )
            google_client = genai.Client(api_key="inspect")
            content = await google_client.aio.models.generate_content(
                model="inspect", contents=prompt, config=config
            )
            text = "".join(
                part.text or ""
                for candidate in content.candidates or []
                if candidate.content is not None
                for part in candidate.content.parts or []
            )
            return ClientReply(
                text, [dict(call.args or {}) for call in content.function_calls or []]
            )
        case _:
            assert_never(dialect)


async def _live_filter(
    model: Model, output: ModelOutput, generate_input: GenerateInput
) -> ModelOutput | None:
    """Replace text output; point every tool call at `FILTERED_LOCATION`."""
    if not output.message.tool_calls:
        return ModelOutput.from_content(model.name, REPLACED_SENTINEL)
    for call in output.message.tool_calls:
        call.arguments = {"location": FILTERED_LOCATION}
    return output


def _run_live_response_filter(
    model: str, dialect: LiveDialect, mode: LiveFilterMode, tmp_path: Path
) -> None:
    """Run one bridged request against a live model with `_live_filter`."""
    from inspect_ai import Task, eval
    from inspect_ai.agent import Agent, agent
    from inspect_ai.dataset import Sample

    replies: list[ClientReply] = []
    tools = mode == "tool_call"
    prompt = (
        "What is the weather in Paris? Use the get_weather tool."
        if tools
        else "Say hello in one word."
    )

    @agent
    def live_agent() -> Agent:
        async def execute(state: AgentState) -> AgentState:
            async with agent_bridge(state, response_filter=_live_filter) as bridge:
                replies.append(await _call_bridged_client(dialect, prompt, tools))
                return bridge.state

        return execute

    log = eval(
        Task(dataset=[Sample(input=prompt)], solver=live_agent()),
        model=model,
        log_dir=str(tmp_path),
        display="plain",
    )[0]
    assert log.status == "success", log.error
    assert len(replies) == 1
    reply = replies[0]

    # the provider's own output is what the ModelEvent records
    assert log.samples is not None
    model_events = [e for e in log.samples[0].events if isinstance(e, ModelEvent)]
    assert len(model_events) == 1
    provider_output = model_events[0].output
    match mode:
        case "replace":
            assert reply.text == REPLACED_SENTINEL
            assert reply.tool_arguments == []
            assert REPLACED_SENTINEL not in provider_output.completion
        case "tool_call":
            assert reply.tool_arguments
            assert all(
                arguments == {"location": FILTERED_LOCATION}
                for arguments in reply.tool_arguments
            )
            assert provider_output.message.tool_calls
            assert all(
                call.arguments.get("location") != FILTERED_LOCATION
                for call in provider_output.message.tool_calls
            )
        case _:
            assert_never(mode)


@skip_if_no_openai
@pytest.mark.parametrize("mode", get_args(LiveFilterMode))
def test_live_response_filter_completions(tmp_path: Path, mode: LiveFilterMode) -> None:
    _run_live_response_filter("openai/gpt-4o-mini", "completions", mode, tmp_path)


@skip_if_no_openai
@pytest.mark.parametrize("mode", get_args(LiveFilterMode))
def test_live_response_filter_responses(tmp_path: Path, mode: LiveFilterMode) -> None:
    _run_live_response_filter("openai/gpt-5-mini", "responses", mode, tmp_path)


@skip_if_no_anthropic
@pytest.mark.parametrize("mode", get_args(LiveFilterMode))
def test_live_response_filter_anthropic(tmp_path: Path, mode: LiveFilterMode) -> None:
    _run_live_response_filter("anthropic/claude-haiku-4-5", "anthropic", mode, tmp_path)


@skip_if_no_google
@pytest.mark.parametrize("mode", get_args(LiveFilterMode))
def test_live_response_filter_google(tmp_path: Path, mode: LiveFilterMode) -> None:
    _run_live_response_filter("google/gemini-3.1-flash-lite", "google", mode, tmp_path)


LiveNativeMode = Literal["edit_text", "drop_server_tools", "edit_search"]
SERVER_BLOCK_TYPES = {
    "server_tool_use",
    "web_search_tool_result",
    "code_execution_tool_result",
}


def _live_native_filter(
    mode: LiveNativeMode, saw_server_tools: list[bool]
) -> ModelResponseFilter:
    """Record whether each output had server tool items, then edit it per `mode`."""

    async def response_filter(
        model: Model, output: ModelOutput, generate_input: GenerateInput
    ) -> ModelOutput | None:
        content = output.message.content
        if not isinstance(content, list):
            saw_server_tools.append(False)
            return None
        tool_uses = [c for c in content if isinstance(c, ContentToolUse)]
        saw_server_tools.append(bool(tool_uses))
        match mode:
            case "edit_text":
                for item in content:
                    if isinstance(item, ContentText):
                        item.text = f"{item.text} {REPLACED_SENTINEL}"
                        break
            case "drop_server_tools":
                output.message.content = [
                    c for c in content if not isinstance(c, ContentToolUse)
                ]
            case "edit_search":
                if tool_uses:
                    tool_uses[0].arguments = '{"query": "edited"}'
            case _:
                assert_never(mode)
        return output

    return response_filter


@skip_if_no_anthropic
@pytest.mark.parametrize("mode", get_args(LiveNativeMode))
def test_live_response_filter_anthropic_native_content(
    tmp_path: Path, mode: LiveNativeMode
) -> None:
    """A filter over live Anthropic server tool content, followed by another turn.

    Web search with dynamic filtering returns nested server tool spans. Keeping
    them while editing text, or removing all of them, must render as the filter
    left them and replay on the next turn; editing one fails the sample.
    """
    from anthropic import AsyncAnthropic

    from inspect_ai import Task, eval
    from inspect_ai.agent import Agent, agent
    from inspect_ai.dataset import Sample

    saw_server_tools: list[bool] = []
    first_reply_types: list[str] = []
    first_reply_text: list[str] = []
    prompt = "What movie won best picture in 2025? Search the web."

    @agent
    def native_agent() -> Agent:
        async def execute(state: AgentState) -> AgentState:
            async with agent_bridge(
                state, response_filter=_live_native_filter(mode, saw_server_tools)
            ) as bridge:
                async with AsyncAnthropic(api_key="inspect") as client:
                    tools: Any = [
                        {
                            "type": "web_search_20260209",
                            "name": "web_search",
                            "max_uses": 3,
                        }
                    ]
                    messages: Any = [{"role": "user", "content": prompt}]
                    response = await client.messages.create(
                        model="inspect",
                        max_tokens=4096,
                        messages=messages,
                        tools=tools,
                        tool_choice={"type": "any"},
                    )
                    first_reply_types.extend(block.type for block in response.content)
                    first_reply_text.extend(
                        block.text for block in response.content if block.type == "text"
                    )
                    messages = messages + [
                        {"role": "assistant", "content": response.content},
                        {"role": "user", "content": "Answer in one short sentence."},
                    ]
                    await client.messages.create(
                        model="inspect",
                        max_tokens=4096,
                        messages=messages,
                        tools=tools,
                    )
                return bridge.state

        return execute

    log = eval(
        Task(dataset=[Sample(input=prompt)], solver=native_agent()),
        model="anthropic/claude-sonnet-4-6",
        log_dir=str(tmp_path),
        display="plain",
    )[0]
    assert log.samples is not None
    sample = log.samples[0]

    # the model actually produced server tool content on the first turn
    assert saw_server_tools and saw_server_tools[0]
    match mode:
        case "edit_text":
            assert sample.error is None, sample.error
            assert len(saw_server_tools) == 2
            assert SERVER_BLOCK_TYPES & set(first_reply_types)
            assert any(REPLACED_SENTINEL in text for text in first_reply_text)
        case "drop_server_tools":
            assert sample.error is None, sample.error
            assert len(saw_server_tools) == 2
            assert not SERVER_BLOCK_TYPES & set(first_reply_types)
        case "edit_search":
            assert sample.error is not None
            assert sample.error.message.startswith("ResponseFilterError(")
            assert first_reply_types == []
        case _:
            assert_never(mode)
