import json
import re
import traceback
from datetime import date
from pathlib import Path
from typing import (
    Any,
    Callable,
    Literal,
    NamedTuple,
    NoReturn,
    Sequence,
    cast,
    get_args,
)
from unittest.mock import AsyncMock

import anyio
import pytest
from pydantic import JsonValue
from test_helpers.message_ids import edited_id
from test_helpers.service_dispatch import (
    REQUEST_FILE,
    REQUEST_ID,
    dispatching_service,
)
from test_helpers.utils import (
    skip_if_no_anthropic,
    skip_if_no_docker,
    skip_if_no_google,
    skip_if_no_openai,
)
from typing_extensions import assert_never

from inspect_ai._util._async import unwrap_exception_group
from inspect_ai._util.content import (
    Content,
    ContentReasoning,
    ContentText,
    ContentToolUse,
)
from inspect_ai._util.exception import TerminateSampleError
from inspect_ai.agent import AgentState
from inspect_ai.agent._bridge._errors import PROVIDER_ERROR_KEY, ResponseFilterError
from inspect_ai.agent._bridge.anthropic_api import inspect_anthropic_api_request
from inspect_ai.agent._bridge.bridge import agent_bridge
from inspect_ai.agent._bridge.responses import inspect_responses_api_request
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
from inspect_ai.agent._bridge.util import (
    _CLIENT_NEUTRAL_CONFIG_FIELDS,
    _apply_response_filter,
    _is_unchanged,
    _settle_message_ids,
    apply_message_ids,
    bridge_generate,
    default_code_execution_providers,
    internal_web_search_providers,
)
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
from inspect_ai.model._message_ids import edited_message
from inspect_ai.model._model import (
    GenerateFilter,
    GenerateInput,
    Model,
    ModelRefusalError,
    ModelResponseFilter,
    get_model,
    use_model_event_sink,
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
from inspect_ai.tool._tool import Tool
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

    async def reset(self, prefix: list[ChatMessage]) -> None:
        pass


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
        requested_model=None,
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
            requested_model=None,
        )
    assert isinstance(exc_info.value.__cause__, ValueError)


def _raise(error: Exception) -> NoReturn:
    raise error


@pytest.mark.parametrize(
    "make_error",
    [
        lambda: LimitExceededError("token", value=2, limit=1),
        lambda: TerminateSampleError("stop"),
        lambda: ModelRefusalError(
            ModelOutput.from_content("mockllm/model", "no"), "mockllm/model"
        ),
    ],
    ids=["limit", "terminate", "refusal"],
)
async def test_response_filter_control_flow_keeps_its_context(
    make_error: Callable[[], Exception],
) -> None:
    """Control flow raised from a filter's task group keeps its own context."""
    error = make_error()

    async def fail() -> None:
        try:
            raise ValueError("context")
        except ValueError:
            _raise(error)

    async def grouped_filter(
        model: Model, output: ModelOutput, generate_input: GenerateInput
    ) -> ModelOutput | None:
        async with anyio.create_task_group() as tg:
            tg.start_soon(collect, fail())
        return None

    model = get_model("mockllm/model")
    with pytest.raises(type(error)) as exc_info:
        await _apply_response_filter(
            grouped_filter,
            model,
            ModelOutput.from_content("mockllm/model", "hi"),
            GenerateInput([], [], "auto", GenerateConfig()),
        )
    assert exc_info.value is error
    assert repr(error.__context__) == "ValueError('context')"
    assert not error.__suppress_context__
    text = "".join(traceback.format_exception(error))
    assert "Exception Group Traceback" not in text
    assert text.count(f"{type(error).__name__}: ") == 1


@pytest.mark.parametrize("changed", [False, True], ids=["unchanged", "changed"])
async def test_response_filter_keeps_the_completion_of_an_unchanged_message(
    changed: bool,
) -> None:
    """A replacement with the message unchanged keeps the provider's completion.

    A provider can set a completion that differs from the message's text (Google
    joins text continued across requests with no separator). A changed message
    has its completion rebuilt from its text.
    """
    output = ModelOutput(
        model="mockllm/model",
        choices=[
            ChatCompletionChoice(
                message=ChatMessageAssistant(
                    content=[
                        ContentText(text='{"answer":"hel'),
                        ContentText(text='lo"}'),
                    ]
                ),
                stop_reason="stop",
            )
        ],
        completion='{"answer":"hello"}',
    )

    async def replacing_filter(
        model: Model, output: ModelOutput, generate_input: GenerateInput
    ) -> ModelOutput | None:
        if changed:
            output.message.content = [ContentText(text="replaced")]
        return output

    filtered = await _apply_response_filter(
        replacing_filter,
        get_model("mockllm/model"),
        output,
        GenerateInput([], [], "auto", GenerateConfig()),
    )
    assert filtered.completion == ("replaced" if changed else '{"answer":"hello"}')


async def test_response_filter_termination_on_a_wrapper_ends_the_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A termination the filter's group was raised while handling stays sticky."""

    async def grouped_filter(
        model: Model, output: ModelOutput, generate_input: GenerateInput
    ) -> ModelOutput | None:
        try:
            raise TerminateSampleError("stop now")
        except TerminateSampleError:
            _raise(
                ExceptionGroup(
                    "cleanup", [LimitExceededError("token", value=2, limit=1)]
                )
            )

    async def generate() -> JsonValue:
        await _apply_response_filter(
            grouped_filter,
            get_model("mockllm/model"),
            ModelOutput.from_content("mockllm/model", "hi"),
            GenerateInput([], [], "auto", GenerateConfig()),
        )
        return None

    replies: list[str | None] = []
    service = dispatching_service(monkeypatch, "generate", generate, {}, replies)
    with pytest.raises(TerminateSampleError, match="stop now"):
        await service._handle_request_tracked(REQUEST_FILE, REQUEST_ID)
    assert replies == ["Terminating: stop now"]


@pytest.mark.parametrize("selected", ["error", "group"])
async def test_response_filter_termination_on_the_unwrapped_error_ends_the_request(
    monkeypatch: pytest.MonkeyPatch, selected: Literal["error", "group"]
) -> None:
    """A termination in the context of the error a filter unwraps stays sticky."""

    async def grouped_filter(
        model: Model, output: ModelOutput, generate_input: GenerateInput
    ) -> ModelOutput | None:
        limit = LimitExceededError("token", value=2, limit=1)
        error: Exception = (
            limit if selected == "error" else ExceptionGroup("inner", [limit])
        )
        error.__context__ = TerminateSampleError("stop now")
        outer = ExceptionGroup("outer", [error])
        outer.__cause__ = ValueError("outer cause")
        with unwrap_exception_group():
            raise outer

    async def generate() -> JsonValue:
        await _apply_response_filter(
            grouped_filter,
            get_model("mockllm/model"),
            ModelOutput.from_content("mockllm/model", "hi"),
            GenerateInput([], [], "auto", GenerateConfig()),
        )
        return None

    replies: list[str | None] = []
    service = dispatching_service(monkeypatch, "generate", generate, {}, replies)
    with pytest.raises(TerminateSampleError, match="stop now"):
        await service._handle_request_tracked(REQUEST_FILE, REQUEST_ID)
    assert replies == ["Terminating: stop now"]


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


@skip_if_no_docker
@pytest.mark.slow
def test_sandbox_response_filter_terminate_survives_the_scaffold_exiting_first(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A termination ends the sample even when the scaffold finishes before it lands.

    The service dispatcher writes the terminating reply before raising. Removing
    the request file is slowed here so the scaffold always reads that reply and
    exits, and the agent completes, before the termination is raised: the race
    that otherwise loses it intermittently. The termination must still end the
    sample, not be cancelled with the service or logged as a cleanup error.
    """
    from inspect_ai.util._sandbox.service import SandboxService

    remove_request_file = SandboxService._remove_request_file

    async def slow_remove_request_file(self: SandboxService, request_file: str) -> None:
        await remove_request_file(self, request_file)
        await anyio.sleep(5)

    monkeypatch.setattr(
        SandboxService, "_remove_request_file", slow_remove_request_file
    )

    log, results = _run_sandbox_eval_with_response_filter(
        tmp_path,
        _failing_response_filter("terminate"),
        model=_under_limit_model(),
        token_limit=JUDGE_TOKEN_LIMIT,
    )

    # the scaffold finished first: the ordering the race needs
    assert len(results) == 1
    _assert_failure_outcome(log, "terminate")


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


@pytest.mark.parametrize("regenerate", [False, True], ids=["output", "regeneration"])
async def test_sandbox_identity_filter_keeps_provider_tool_arguments(
    regenerate: bool,
) -> None:
    """Only arguments the filter changed must be JSON-serializable.

    `parse_tool_call`'s YAML fallback turns a bare `2024-01-01` into a `date`, which
    the Anthropic dialect renders. A filter that returns the output, or its own
    generation, unchanged must not fail a sample that would pass without it.
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
            *(
                [ModelOutput.from_content("mockllm/model", "first")]
                if regenerate
                else []
            ),
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
            ),
        ],
    )

    async def identity_filter(
        model: Model, output: ModelOutput, generate_input: GenerateInput
    ) -> ModelOutput | None:
        return await model.generate(generate_input.input) if regenerate else output

    bridge = _sandbox_bridge(identity_filter, model)
    reply = await _forward_provider_errors(
        generate_anthropic(None, None, bridge), bridge
    )({"model": "inspect", "max_tokens": 1024, "messages": CHAT_REQUEST["messages"]})

    assert PROVIDER_ERROR_KEY not in reply
    assert not bridge._failure_requested.is_set()
    tool_use = cast(list[dict[str, JsonValue]], reply["content"])[-1]
    assert tool_use["input"] == {"date": "2024-01-01"}


@pytest.mark.parametrize("edit_text", [False, True], ids=["arguments", "and text"])
@pytest.mark.parametrize("regenerate", [False, True], ids=["output", "regeneration"])
async def test_response_filter_rejects_arguments_it_makes_unserializable(
    regenerate: bool, edit_text: bool
) -> None:
    """A non-JSON argument the filter puts into a call, also one of its own generation, fails it."""
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.for_tool_call("mockllm/model", "lookup", {"q": "x"}),
            ModelOutput.for_tool_call("mockllm/model", "lookup", {"q": "y"}),
        ],
    )

    async def unserializable(
        model: Model, output: ModelOutput, generate_input: GenerateInput
    ) -> ModelOutput | None:
        if regenerate:
            output = await model.generate(generate_input.input)
        assert output.message.tool_calls
        output.message.tool_calls[0].arguments["when"] = date(2024, 1, 1)
        if edit_text:
            output.message.content = "Looking up"
        return output

    bridge = AgentBridge(AgentState(messages=[]))
    bridge.response_filter = unserializable
    with pytest.raises(ResponseFilterError, match="not JSON-serializable"):
        await bridge_generate(
            bridge,
            model,
            [ChatMessageUser(content="hi")],
            [],
            None,
            GenerateConfig(),
            requested_model=None,
        )


async def test_sandbox_forwarding_preserves_response_filter_limit() -> None:
    """A limit hit in a response filter reaches the sandbox service unchanged.

    Drives the real generate_completions -> bridge_generate -> forwarder path: the
    scaffold gets an error reply and the bridge records the `LimitExceededError`
    itself, to raise on the agent's side, where the scope that applied the limit
    handles it, whereas a wrapped one would fail the sample.
    """
    limit_error = LimitExceededError("token", value=102, limit=JUDGE_TOKEN_LIMIT)

    async def over_limit_filter(
        model: Model, output: ModelOutput, generate_input: GenerateInput
    ) -> ModelOutput | None:
        raise limit_error

    bridge = _sandbox_bridge(over_limit_filter)
    generate = _forward_provider_errors(generate_completions(bridge), bridge)
    reply = await generate(CHAT_REQUEST)
    assert PROVIDER_ERROR_KEY in reply
    assert bridge.generation_limit is limit_error
    assert not bridge._failure_requested.is_set()


@pytest.mark.parametrize(
    "failure",
    [
        f
        for f in get_args(FilterFailure)
        if _expected_error(f) not in (None, _expected_error("terminate"))
    ],
)
async def test_sandbox_response_filter_ends_sample_through_the_monitor(
    failure: FilterFailure,
) -> None:
    """A filter's refusal or failure reaches the sample runner from the sandbox.

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


async def test_sandbox_response_filter_termination_is_left_to_the_dispatcher() -> None:
    """A filter's termination propagates from a sandbox model method.

    The sandbox service dispatcher answers the RPC and propagates the
    `TerminateSampleError` out of the service task, which ends the sample, so
    the forwarder re-raises it rather than signalling the bridge's monitor.
    """
    bridge = _sandbox_bridge(_failing_response_filter("terminate"))
    with pytest.raises(TerminateSampleError, match=TERMINATE_REASON):
        await _forward_provider_errors(generate_completions(bridge), bridge)(
            CHAT_REQUEST
        )
    assert not bridge._failure_requested.is_set()


def test_sandbox_response_filter_limit_with_termination_terminates(
    tmp_path: Path,
) -> None:
    """A filter's concurrent limit and termination end the sample as a termination.

    `_apply_response_filter` raises the group's first control-flow leaf (the
    limit) with the group as its context. The service dispatcher finds the
    termination in that history before routing the limit to the sample, so it
    answers the RPC once and propagates the termination: the sample ends with
    the operator reason, not a token limit, and the monitor is not signalled.
    """
    from inspect_ai import Task, eval
    from inspect_ai.dataset import Sample
    from inspect_ai.solver import Generate, Solver, TaskState, solver

    replies: list[str | None] = []
    signalled: list[bool] = []

    async def concurrent_judges(
        model: Model, output: ModelOutput, generate_input: GenerateInput
    ) -> ModelOutput | None:
        raise ExceptionGroup(
            "concurrent judges",
            [
                LimitExceededError("token", value=2, limit=1),
                TerminateSampleError("stop now"),
            ],
        )

    @solver
    def serve_one_generation() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            bridge = _sandbox_bridge(concurrent_judges)
            try:
                with pytest.MonkeyPatch.context() as monkeypatch:
                    service = dispatching_service(
                        monkeypatch,
                        "generate_completions",
                        _forward_provider_errors(generate_completions(bridge), bridge),
                        {"json_data": CHAT_REQUEST},
                        replies,
                    )
                    await service._handle_request_tracked(REQUEST_FILE, REQUEST_ID)
            finally:
                signalled.append(bridge._failure_requested.is_set())
            return state

        return solve

    log = eval(
        Task(dataset=[Sample(input="test")], solver=serve_one_generation()),
        model="mockllm/model",
        log_dir=str(tmp_path),
        display="none",
    )[0]

    assert log.status == "success"
    assert log.samples is not None
    sample = log.samples[0]
    assert sample.error is None, sample.error
    assert sample.limit is not None
    assert (sample.limit.type, sample.limit.reason) == ("operator", "stop now")
    limits = [e for e in sample.events if e.event == "sample_limit"]
    assert [(e.type, e.message) for e in limits] == [("operator", "stop now")]
    assert replies == ["Terminating: stop now"]
    assert signalled == [False]


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
        requested_model=None,
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

    The sandbox bridge records it after answering the scaffold, to raise once
    the agent has unwound. Async, so it also runs under Trio, whose task groups
    and cancellation differ.
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
                        requested_model=None,
                    )
                case "sandbox":
                    sandbox_bridge = _sandbox_bridge(response_filter)
                    reply = await _forward_provider_errors(
                        generate_completions(sandbox_bridge), sandbox_bridge
                    )(CHAT_REQUEST)
                    assert PROVIDER_ERROR_KEY in reply
                    assert sandbox_bridge.generation_limit is not None
                    raise sandbox_bridge.generation_limit
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
    container: str | None = None,
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
            "container": {"id": container, "expires_at": "2026-10-06T12:00:00Z"}
            if container is not None
            else None,
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
            bridge,
            model,
            [ChatMessageUser(content="hi")],
            [],
            None,
            GenerateConfig(),
            requested_model=None,
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
        bridge,
        model,
        [ChatMessageUser(content="hi")],
        [],
        None,
        GenerateConfig(),
        requested_model=None,
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
                requested_model=None,
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
        assert state_output.message.id == edited_id(
            provider_output.message.id, state_output.message
        )
    else:
        assert state_output.message.id == provider_output.message.id
        assert PENDING_CODE in json.dumps(blocks)
        assert [b["type"] for b in blocks] == [b["type"] for b in original_blocks]
    # the provider's output and its replay record are untouched
    assert await _render_anthropic(provider_output.message) == original_blocks


CONTAINER_ID = "container_probe"
NESTED_PENDING_CE_ID = "srvtoolu_ce_pending"
NESTED_WS_ID = "srvtoolu_ws_nested"


async def _nested_pending_output(q: JsonValue = "x") -> ModelOutput:
    """A completed web search nested in a code execution that is still pending."""
    caller = {"type": "code_execution_20260120", "tool_id": NESTED_PENDING_CE_ID}
    return await _anthropic_output(
        [
            {"type": "text", "text": "Checking."},
            {
                "type": "server_tool_use",
                "id": NESTED_PENDING_CE_ID,
                "name": "code_execution",
                "input": {"code": PENDING_CODE},
                "caller": {"type": "direct"},
            },
            {
                "type": "server_tool_use",
                "id": NESTED_WS_ID,
                "name": "web_search",
                "input": {"query": "nhl scores"},
                "caller": caller,
            },
            {
                "type": "web_search_tool_result",
                "tool_use_id": NESTED_WS_ID,
                "content": [
                    {
                        "type": "web_search_result",
                        "title": "NHL Scores",
                        "url": "https://nhl.com/scores",
                        "encrypted_content": "ENCRYPTED_CONTENT",
                    }
                ],
                "caller": caller,
            },
            {
                "type": "tool_use",
                "id": "toolu_client",
                "name": "lookup",
                "input": {"q": q},
            },
        ],
        [ToolInfo(name="lookup", description="Look something up.")],
        stop_reason="tool_use",
        container=CONTAINER_ID,
    )


@approver
def _rejecting_approver() -> Approver:
    async def approve(
        message: str, call: ToolCall, view: ToolCallView, history: list[ChatMessage]
    ) -> Approval:
        return Approval(decision="reject", explanation="Not allowed.")

    return approve


async def _text_edit_filter(
    model: Model, output: ModelOutput, generate_input: GenerateInput
) -> ModelOutput | None:
    """Edit the first text item, keeping every other item."""
    if not isinstance(output.message.content, list):
        return None
    for item in output.message.content:
        if isinstance(item, ContentText):
            item.text = REPLACED_SENTINEL
            break
    return output


PendingKeep = Literal["unchanged", "text_edit", "rebuilt", "changed_id", "missing_id"]


def _pending_keep_filter(keep: PendingKeep) -> ModelResponseFilter:
    """Keep every server tool item; edit text and the message id per `keep`."""

    async def response_filter(
        model: Model, output: ModelOutput, generate_input: GenerateInput
    ) -> ModelOutput | None:
        if keep == "unchanged":
            return output
        await _text_edit_filter(model, output, generate_input)
        match keep:
            case "text_edit":
                pass
            case "rebuilt":
                output.choices[0].message = ChatMessageAssistant.model_validate(
                    output.message.model_dump(exclude={"id"})
                )
            case "changed_id":
                output.message.id = "filter-chosen-id"
            case "missing_id":
                output.message.id = None
            case _:
                assert_never(keep)
        return output

    return response_filter


@pytest.mark.parametrize("path", get_args(BridgePath))
@pytest.mark.parametrize("keep", get_args(PendingKeep))
async def test_response_filter_keeps_pending_work_with_its_server_items(
    keep: PendingKeep, path: BridgePath
) -> None:
    """A message that keeps its server tool items keeps their pending work.

    The completed nested search anchors the span, but its parent code execution
    is still pending, so a follow-up request must name the container recorded
    under the message id. An approval rejection replays the filtered message to
    the model, which must still resolve that container, whatever id the filter
    gave the message.
    """
    from inspect_ai.model._providers.anthropic import _pending_container_for_input

    init_sample_anthropic_assistant_internal()
    provider_output = await _nested_pending_output()
    original_blocks = await _render_anthropic(provider_output.message)
    assert _pending_container_for_input([provider_output.message]) == CONTAINER_ID

    retry_inputs: list[list[ChatMessage]] = []

    def serve(
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        if not retry_inputs and not any(
            isinstance(m, ChatMessageAssistant) for m in input
        ):
            retry_inputs.append([])
            return provider_output
        retry_inputs.append(list(input))
        return ModelOutput.from_content("mockllm/model", "done")

    model = get_model("mockllm/model", custom_outputs=serve)
    response_filter = _pending_keep_filter(keep)
    approval = [ApprovalPolicy(_rejecting_approver(), "lookup")]

    match path:
        case "in_process":
            bridge = AgentBridge(
                AgentState(messages=[]),
                approval=approval,
                response_filter=response_filter,
            )
            await bridge_generate(
                bridge,
                model,
                [ChatMessageUser(content="hi")],
                [],
                None,
                GenerateConfig(),
                requested_model=None,
            )
        case "sandbox":
            sandbox_bridge = SandboxAgentBridge(
                state=AgentState(messages=[]),
                filter=None,
                retry_refusals=None,
                compaction=None,
                port=13131,
                model=None,
                model_aliases={"inspect": model},
                approval=approval,
                response_filter=response_filter,
            )
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
        case _:
            assert_never(path)

    # the rejection retried with the filtered message, pending work and all
    assert len(retry_inputs) == 2
    retry_input = retry_inputs[1]
    assert _pending_container_for_input(retry_input) == CONTAINER_ID
    replayed = next(
        m for m in reversed(retry_input) if isinstance(m, ChatMessageAssistant)
    )
    # the work stays under the turn's id, whatever id the filter gave it
    assert replayed.id == provider_output.message.id
    replayed_blocks = await _render_anthropic(replayed)
    assert PENDING_CODE in json.dumps(replayed_blocks)
    assert {b.get("id") for b in replayed_blocks} >= {
        NESTED_PENDING_CE_ID,
        NESTED_WS_ID,
    }
    if keep != "unchanged":
        assert REPLACED_SENTINEL in [b.get("text") for b in replayed_blocks]
    # the provider's output and its replay record are untouched
    assert await _render_anthropic(provider_output.message) == original_blocks
    assert _pending_container_for_input([provider_output.message]) == CONTAINER_ID


OPENAI_SERVER_ITEMS: dict[str, dict[str, Any]] = {
    "web_search_call": {
        "id": "ws_1",
        "type": "web_search_call",
        "status": "completed",
        "action": {"type": "search", "query": "nhl scores"},
    },
    "code_interpreter_call": {
        "id": "ci_1",
        "type": "code_interpreter_call",
        "status": "completed",
        "code": "print(1)",
        "container_id": "cntr_1",
        "outputs": [{"type": "logs", "logs": "1"}],
    },
    "mcp_call": {
        "id": "mcp_1",
        "type": "mcp_call",
        "server_label": "docs",
        "name": "echo",
        "arguments": '{"text": "hi"}',
        "output": "hi",
    },
}

ServerItemsReply = Literal[
    "web_search_call",
    "code_interpreter_call",
    "mcp_call",
    "anthropic_completed",
    "anthropic_pending",
]


async def _server_items_output(reply: ServerItemsReply) -> ModelOutput:
    """A provider's reply holding server tool items and text, parsed by its converter."""
    from openai.types.responses import Response

    from inspect_ai.model._openai_responses import openai_responses_chat_choices

    match reply:
        case "web_search_call" | "code_interpreter_call" | "mcp_call":
            response = Response.model_validate(
                {
                    "id": "resp_1",
                    "object": "response",
                    "created_at": 0,
                    "model": "gpt-5",
                    "status": "completed",
                    "parallel_tool_calls": False,
                    "tool_choice": "auto",
                    "tools": [],
                    "output": [
                        OPENAI_SERVER_ITEMS[reply],
                        {
                            "id": "msg_1",
                            "type": "message",
                            "role": "assistant",
                            "status": "completed",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": "The Bruins won 3-2.",
                                    "annotations": [],
                                }
                            ],
                        },
                    ],
                }
            )
            output = ModelOutput(
                model="mockllm/model",
                choices=openai_responses_chat_choices("gpt-5", response, []),
            )
        case "anthropic_completed":
            output = await _anthropic_output(
                [b for b in NESTED_SEARCH_BLOCKS if b is not THINKING_BLOCK]
            )
        case "anthropic_pending":
            output = await _nested_pending_output()
        case _:
            assert_never(reply)
    # set so mockllm doesn't estimate usage (which downloads an encoding)
    output.usage = ModelUsage(input_tokens=1, output_tokens=1, total_tokens=2)
    return output


@pytest.mark.parametrize("reply", get_args(ServerItemsReply))
async def test_text_edit_keeping_server_items_is_a_message_of_its_own(
    reply: ServerItemsReply,
) -> None:
    """A response filter's text edit that keeps server tool items gets an edit id.

    Analysis extraction (like the viewer) keeps one message per id, so the
    generated output and the edited reply the scaffold sends back both survive
    only under different ids. The exception is an Anthropic turn that ended
    with server work running: that work replays from state keyed by the
    generated id, so the reply keeps it. Each reply goes through its own
    provider's dialect, which sends it back unchanged.
    """
    from inspect_ai.analysis._dataframe.samples.table import (
        sample_messages_from_events,
    )
    from inspect_ai.log._transcript import Transcript, init_transcript, transcript
    from inspect_ai.model._providers.anthropic import _pending_container_for_input

    init_sample_anthropic_assistant_internal()
    init_transcript(Transcript())
    done = ModelOutput.from_content("mockllm/model", "done")
    done.usage = ModelUsage(input_tokens=1, output_tokens=1, total_tokens=2)
    model = get_model(
        "mockllm/model",
        memoize=False,
        custom_outputs=[await _server_items_output(reply), done],
    )
    bridge = AgentBridge(
        AgentState(messages=[ChatMessageUser(content="go")]),
        model_aliases={"scaffold": model},
        response_filter=_text_edit_filter,
    )
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {"q": {"type": "string"}},
        "required": ["q"],
    }
    anthropic = reply.startswith("anthropic")

    async def request(input: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if anthropic:
            message = await inspect_anthropic_api_request(
                {
                    "model": "scaffold",
                    "max_tokens": 1024,
                    "messages": input,
                    "tools": [
                        {
                            "name": "lookup",
                            "description": "Look something up.",
                            "input_schema": parameters,
                        }
                    ],
                },
                None,
                internal_web_search_providers(),
                default_code_execution_providers(),
                bridge,
            )
            return [
                b.model_dump(mode="json", exclude_none=True) for b in message.content
            ]
        response = await inspect_responses_api_request(
            {
                "model": "scaffold",
                "input": input,
                "tools": [
                    {
                        "type": "function",
                        "name": "lookup",
                        "description": "Look something up.",
                        "parameters": parameters,
                    }
                ],
            },
            None,
            internal_web_search_providers(),
            default_code_execution_providers(),
            bridge,
        )
        return [item.model_dump(exclude_none=True) for item in response.output]

    history: list[dict[str, Any]] = [{"role": "user", "content": "go"}]
    items = await request(history)
    handed = bridge.state.output.message
    if anthropic:
        results: list[dict[str, Any]] = [
            {"type": "tool_result", "tool_use_id": b["id"], "content": "1"}
            for b in items
            if b["type"] == "tool_use"
        ]
        history += [
            {"role": "assistant", "content": items},
            {"role": "user", "content": [*results, {"type": "text", "text": "go on"}]},
        ]
    else:
        results = [
            {"type": "function_call_output", "call_id": item["call_id"], "output": "1"}
            for item in items
            if item["type"] == "function_call"
        ]
        history += [*items, *results, {"role": "user", "content": "go on"}]
    await request(history)

    model_events = [e for e in transcript().events if isinstance(e, ModelEvent)]
    generated = model_events[0].output.message
    assert generated.id is not None
    [sent] = [m for m in model_events[1].input if isinstance(m, ChatMessageAssistant)]
    assert sent.id == handed.id
    assert REPLACED_SENTINEL in sent.text
    assert any(isinstance(c, ContentToolUse) for c in sent.content)
    if reply == "anthropic_pending":
        assert sent.id == generated.id
        assert _pending_container_for_input([sent]) == CONTAINER_ID
    else:
        assert sent.id == edited_id(generated.id, sent) != generated.id
        extracted = [
            (m.id, m.text)
            for m in sample_messages_from_events(list(transcript().events), None)
            if isinstance(m, ChatMessageAssistant)
        ]
        assert extracted[:2] == [(generated.id, generated.text), (sent.id, sent.text)]


@approver
def _modifying_approver() -> Approver:
    async def approve(
        message: str, call: ToolCall, view: ToolCallView, history: list[ChatMessage]
    ) -> Approval:
        return Approval(
            decision="modify",
            modified=ToolCall(id=call.id, function=call.function, arguments={"q": "y"}),
        )

    return approve


async def _pending_container_output(q: JsonValue = "x") -> ModelOutput:
    """A turn ending on a client tool call while a code execution is pending."""
    return await _anthropic_output(
        [
            {"type": "text", "text": "Checking."},
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
                "input": {"q": q},
            },
        ],
        [ToolInfo(name="lookup", description="Look something up.")],
        stop_reason="tool_use",
        container=CONTAINER_ID,
    )


@pytest.mark.parametrize("path", get_args(BridgePath))
async def test_modified_arguments_keep_pending_server_work(path: BridgePath) -> None:
    """An approver's rewrite of a client call is an edit that keeps the turn's pending work."""
    from inspect_ai.model._providers.anthropic import _pending_container_for_input

    init_sample_anthropic_assistant_internal()
    provider_output = await _pending_container_output()
    original_blocks = await _render_anthropic(provider_output.message)
    model = get_model("mockllm/model", custom_outputs=[provider_output])
    approval = [ApprovalPolicy(_modifying_approver(), "lookup")]

    match path:
        case "in_process":
            bridge = AgentBridge(AgentState(messages=[]), approval=approval)
            output, _ = await bridge_generate(
                bridge,
                model,
                [ChatMessageUser(content="hi")],
                [],
                None,
                GenerateConfig(),
                requested_model=None,
            )
            handed = output.message
        case "sandbox":
            sandbox_bridge = SandboxAgentBridge(
                state=AgentState(messages=[]),
                filter=None,
                retry_refusals=None,
                compaction=None,
                port=13131,
                model=None,
                model_aliases={"inspect": model},
                approval=approval,
            )
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
            content = cast(list[dict[str, Any]], reply["content"])
            assert [b["type"] for b in content] == [b["type"] for b in original_blocks]
            handed = sandbox_bridge.state.output.message
        case _:
            assert_never(path)

    assert handed.id == edited_id(provider_output.message.id, handed)
    assert handed.tool_calls and handed.tool_calls[0].arguments == {"q": "y"}
    blocks = await _render_anthropic(handed)
    assert [b["type"] for b in blocks] == [b["type"] for b in original_blocks]
    assert _pending_container_for_input([handed]) == CONTAINER_ID
    # the model's output keeps its own record
    assert await _render_anthropic(provider_output.message) == original_blocks
    assert _pending_container_for_input([provider_output.message]) == CONTAINER_ID


async def test_edits_of_a_pending_turn_keep_its_work() -> None:
    """Inspect's edit of the turn keeps its pending work."""
    from inspect_ai.model._providers.anthropic import _pending_container_for_input

    init_sample_anthropic_assistant_internal()
    provider_output = await _pending_container_output()
    original_blocks = await _render_anthropic(provider_output.message)
    edited = edited_message(
        provider_output.message, content=[ContentText(text="Checking.  ")]
    )

    assert edited.id == edited_id(provider_output.message.id, edited)
    blocks = await _render_anthropic(edited)
    assert [b["type"] for b in blocks] == [b["type"] for b in original_blocks]
    assert _pending_container_for_input([edited]) == CONTAINER_ID


async def test_unchanged_scaffold_copy_of_a_pending_turn_keeps_its_work() -> None:
    """A scaffold's unchanged copy of the turn is placed under its id, so it keeps the pending work."""
    from inspect_ai.model._providers.anthropic import _pending_container_for_input

    init_sample_anthropic_assistant_internal()
    provider_output = await _pending_container_output()
    task = ChatMessageUser(content="hi")
    bridge = AgentBridge(AgentState(messages=[task]))
    await bridge._track_state([task], provider_output, [])
    copy = provider_output.message.model_copy(update={"id": "wire"})

    apply_message_ids(bridge, [task.model_copy(update={"id": "wire-task"}), copy])

    assert copy.id == provider_output.message.id
    assert _pending_container_for_input([copy]) == CONTAINER_ID


class _GrantRecordingBridge(AgentBridge):
    """Records the proposing ids and call verification of each grant registration."""

    registered: list[tuple[dict[str, str], list[bool] | None]]

    def register_tool_execution_grants(
        self,
        calls: Sequence[ToolCall],
        tools: Sequence[ToolInfo | Tool],
        *,
        span_id: str | None = None,
    ) -> None:
        self.registered.append(
            (dict(self._proposing_message_ids), self._proposing_call_verified)
        )


SCALAR_EDITS: dict[str, tuple[JsonValue, JsonValue]] = {
    "zero_to_false": (0, False),
    "false_to_zero": (False, 0),
    "one_to_true": (1, True),
    "true_to_one": (True, 1),
    "zero_to_one": (0, 1),
}


@pytest.mark.parametrize("edit", ["text", "text_and_call", *SCALAR_EDITS])
@pytest.mark.parametrize("turn", ["pending", "nested"])
async def test_request_filter_text_edit_keeps_pending_work(
    turn: str, edit: str
) -> None:
    """A request filter's edit of its generation keeps the turn's pending work.

    The edit gets its own id and its calls are not verified against the
    generation. A text edit, or an edit keeping the turn's server items, still
    replays the pending code execution in the turn's container; an edit of the
    calls of a turn with no server items drops it, as a response filter's does.
    That includes an argument changed between a number and a boolean, which
    Python equality takes as unchanged.
    """
    from inspect_ai.model._providers.anthropic import _pending_container_for_input

    init_sample_anthropic_assistant_internal()
    before, after = SCALAR_EDITS.get(edit, ("x", {"q": "y"}))
    provider_output = await (
        _pending_container_output(before)
        if turn == "pending"
        else _nested_pending_output(before)
    )
    original_blocks = await _render_anthropic(provider_output.message)

    async def generate(
        model: Model,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice | None,
        config: GenerateConfig,
    ) -> ModelOutput:
        output = await model.generate(
            input=input, tools=tools, tool_choice=tool_choice, config=config
        )
        output = output.model_copy(deep=True)
        if edit in SCALAR_EDITS:
            assert output.message.tool_calls
            output.message.tool_calls[0].arguments = {"q": after}
            return output
        await _text_edit_filter(
            model, output, GenerateInput(input, tools, tool_choice, config)
        )
        if edit == "text_and_call":
            assert output.message.tool_calls
            output.message.tool_calls[0].arguments = {"q": "y"}
        return output

    bridge = _GrantRecordingBridge(AgentState(messages=[]), filter=generate)
    bridge.registered = []
    output, _ = await bridge_generate(
        bridge,
        get_model("mockllm/model", custom_outputs=[provider_output]),
        [ChatMessageUser(content="hi")],
        [],
        None,
        GenerateConfig(),
        requested_model=None,
    )

    handed = output.message
    if edit in SCALAR_EDITS:
        assert handed.tool_calls and handed.tool_calls[0].arguments == {"q": after}
        assert type(handed.tool_calls[0].arguments["q"]) is type(after)
    else:
        assert REPLACED_SENTINEL in handed.text
    assert handed.id == edited_id(provider_output.message.id, handed)
    # the calls are not verified against the generation
    assert bridge.registered == [({}, None)]
    blocks = await _render_anthropic(handed)
    if edit == "text" or turn == "nested":
        assert [b["type"] for b in blocks] == [b["type"] for b in original_blocks]
        assert _pending_container_for_input([handed]) == CONTAINER_ID
    else:
        assert PENDING_CODE not in json.dumps(blocks)
        assert _pending_container_for_input([handed]) is None
    if edit == "text":
        assert [b for b in blocks if b["type"] != "text"] == [
            b for b in original_blocks if b["type"] != "text"
        ]
    # the model's output keeps its own record
    assert await _render_anthropic(provider_output.message) == original_blocks
    assert _pending_container_for_input([provider_output.message]) == CONTAINER_ID


RegeneratedTurn = Literal[
    "pending", "completed_and_pending", "completed", "plain", "text"
]


async def _regenerated_output(turn: RegeneratedTurn) -> ModelOutput:
    match turn:
        case "pending":
            return await _pending_container_output()
        case "completed_and_pending":
            return await _nested_pending_output()
        case "completed":
            return await _anthropic_output(
                [
                    {"type": "text", "text": "Checking."},
                    *PENDING_SPAN_BLOCKS["completed_and_pending"],
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
        case "plain":
            return ModelOutput.for_tool_call("mockllm/model", "lookup", {"q": "x"})
        case "text":
            return ModelOutput.from_content("mockllm/model", "Regenerated")
        case _:
            assert_never(turn)


@pytest.mark.parametrize("annotated", [False, True], ids=["as_is", "annotated"])
@pytest.mark.parametrize("path", get_args(BridgePath))
@pytest.mark.parametrize("turn", get_args(RegeneratedTurn))
async def test_response_filter_returning_its_own_generation_hands_over_that_reply(
    turn: RegeneratedTurn, path: BridgePath, annotated: bool
) -> None:
    """A filter returning its own generation unchanged hands over that generation's reply.

    The reply keeps the generation's id, so the generation's replay state
    reaches the scaffold: an Anthropic code execution still pending, and the
    container to resume it, are found by that id alone. Metadata is not
    content, so a filter may annotate the reply.
    """
    from inspect_ai.model._providers.anthropic import _pending_container_for_input

    init_sample_anthropic_assistant_internal()
    regenerated = await _regenerated_output(turn)
    regenerated_blocks = await _render_anthropic(regenerated.message)
    pending = turn in ("pending", "completed_and_pending")
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.from_content("mockllm/model", "first"),
            regenerated,
        ],
    )

    async def regenerate(
        model: Model, output: ModelOutput, generate_input: GenerateInput
    ) -> ModelOutput | None:
        output = await model.generate(generate_input.input)
        if annotated:
            output.message.metadata = {"review": "accepted"}
        return output

    match path:
        case "in_process":
            bridge = AgentBridge(AgentState(messages=[]))
            bridge.response_filter = regenerate
            output, _ = await bridge_generate(
                bridge,
                model,
                [ChatMessageUser(content="hi")],
                [],
                None,
                GenerateConfig(),
                requested_model=None,
            )
            handed = output.message
        case "sandbox":
            sandbox_bridge = _sandbox_bridge(regenerate, model)
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
            content = cast(list[dict[str, Any]], reply["content"])
            assert [b["type"] for b in content] == [
                b["type"] for b in regenerated_blocks
            ]
            handed = sandbox_bridge.state.output.message
        case _:
            assert_never(path)

    assert handed.id == regenerated.message.id
    assert await _render_anthropic(handed) == regenerated_blocks
    if annotated:
        assert handed.metadata == {"review": "accepted"}
    if pending:
        assert PENDING_CODE in json.dumps(regenerated_blocks)
        assert _pending_container_for_input([handed]) == CONTAINER_ID


@pytest.mark.parametrize(
    "returned",
    ["edited", "other_model", "same_name_endpoint", "same_name_account"],
)
@pytest.mark.parametrize("turn", ["pending", "plain"])
async def test_response_filter_regeneration_edit_or_other_model_is_an_edit(
    turn: Literal["pending", "plain"], returned: str
) -> None:
    """A regeneration the filter edits, or another client's output, replaces the bridge's output.

    Neither is the bridged model's generation unchanged, so the reply gets an
    edit id and keeps none of the generation's pending server work. Another
    client is another model, whatever its name: one with the bridged model's
    name but another endpoint or account generates under its own account.
    """
    from inspect_ai.model._providers.anthropic import _pending_container_for_input

    init_sample_anthropic_assistant_internal()
    regenerated = await _regenerated_output(turn)
    first = ModelOutput.from_content("mockllm/model", "first")
    model = get_model(
        "mockllm/model", memoize=False, custom_outputs=[first, regenerated]
    )
    match returned:
        case "same_name_endpoint":
            judge = get_model(
                "mockllm/model",
                base_url="https://other.example.com/v1",
                memoize=False,
                custom_outputs=[regenerated],
            )
        case "same_name_account":
            judge = get_model(
                "mockllm/model",
                api_key="other-account",
                memoize=False,
                custom_outputs=[regenerated],
            )
        case _:
            judge = get_model("mockllm/judge", custom_outputs=[regenerated])
    if returned.startswith("same_name"):
        assert str(judge) == str(model)

    async def regenerate(
        model: Model, output: ModelOutput, generate_input: GenerateInput
    ) -> ModelOutput | None:
        if returned != "edited":
            return await judge.generate(generate_input.input)
        output = await model.generate(generate_input.input)
        output.message.content = REPLACED_SENTINEL
        return output

    bridge = AgentBridge(AgentState(messages=[]))
    bridge.response_filter = regenerate
    output, _ = await bridge_generate(
        bridge,
        model,
        [ChatMessageUser(content="hi")],
        [],
        None,
        GenerateConfig(),
        requested_model=None,
    )

    handed = output.message
    assert handed.id is not None
    assert handed.id not in (regenerated.message.id, first.message.id)
    assert PENDING_CODE not in json.dumps(await _render_anthropic(handed))
    assert _pending_container_for_input([handed]) is None
    if turn == "pending":
        assert _pending_container_for_input([regenerated.message]) == CONTAINER_ID


SameClientCase = Literal[
    "bridged",
    "config",
    "call_temperature",
    "default_endpoint",
    "trailing_slash",
    "env_endpoint",
    "endpoint",
    "account",
    "model_args",
    "model_headers",
    "call_headers",
    "call_extra_body",
    "other_name",
]


@pytest.mark.parametrize("turn", ["pending", "completed_and_pending"])
@pytest.mark.parametrize("client", get_args(SameClientCase))
async def test_response_filter_regeneration_keeps_replay_state_only_from_bridged_client(
    client: SameClientCase,
    turn: Literal["pending", "completed_and_pending"],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only the bridged Anthropic client's own regeneration keeps its id and pending work.

    A client with the bridged model's name but another endpoint, API key or
    provider arguments ran its server work under another account, as did a
    generation whose config adds headers or body fields (e.g. an alternate
    `x-api-key`); its reply is an edit that carries none of that work into the
    bridged model's next input, and its completed server items are rejected.
    Another temperature, per model or per call, is the same client, as is a
    base URL naming the endpoint the bridged client resolved (the default,
    one from the environment, or the same URL with a trailing slash).
    """
    from unittest.mock import patch

    from inspect_ai.model._providers.anthropic import _pending_container_for_input

    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    if client == "env_endpoint":
        monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://alternate.example.com")
    init_sample_anthropic_assistant_internal()
    regenerated = await _regenerated_output(turn)
    model_name = "anthropic/claude-sonnet-4-5"
    model = get_model(
        model_name,
        api_key="primary-key",
        base_url="https://alternate.example.com"
        if client == "trailing_slash"
        else None,
        memoize=False,
    )
    call_config = GenerateConfig()
    match client:
        case "bridged":
            judge = model
        case "default_endpoint":
            judge = get_model(
                model_name,
                api_key="primary-key",
                base_url="https://api.anthropic.com",
                memoize=False,
            )
        case "trailing_slash" | "env_endpoint":
            judge = get_model(
                model_name,
                api_key="primary-key",
                base_url="https://alternate.example.com/",
                memoize=False,
            )
        case "config":
            judge = get_model(
                model_name,
                api_key="primary-key",
                config=GenerateConfig(temperature=0.9),
                memoize=False,
            )
        case "call_temperature":
            judge = model
            call_config = GenerateConfig(temperature=0.9)
        case "model_args":
            judge = get_model(
                model_name, api_key="primary-key", memoize=False, betas=["other"]
            )
        case "endpoint":
            judge = get_model(
                model_name,
                api_key="primary-key",
                base_url="https://alternate.example.com",
                memoize=False,
            )
        case "account":
            judge = get_model(model_name, api_key="other-key", memoize=False)
        case "model_headers":
            judge = get_model(
                model_name,
                api_key="primary-key",
                config=GenerateConfig(extra_headers={"x-api-key": "alternate-key"}),
                memoize=False,
            )
        case "call_headers":
            judge = model
            call_config = GenerateConfig(extra_headers={"x-api-key": "alternate-key"})
        case "call_extra_body":
            judge = model
            call_config = GenerateConfig(extra_body={"service_tier": "priority"})
        case "other_name":
            judge = get_model(
                "anthropic/claude-haiku-4-5", api_key="primary-key", memoize=False
            )
        case _:
            assert_never(client)
    outputs = [ModelOutput.from_content(model_name, "first"), regenerated]

    async def generate(*args: Any, **kwargs: Any) -> ModelOutput:
        return outputs.pop(0)

    async def regenerate(
        model: Model, output: ModelOutput, generate_input: GenerateInput
    ) -> ModelOutput | None:
        return await judge.generate(generate_input.input, config=call_config)

    bridge = AgentBridge(AgentState(messages=[]))
    bridge.response_filter = regenerate
    own = client in (
        "bridged",
        "config",
        "call_temperature",
        "default_endpoint",
        "trailing_slash",
        "env_endpoint",
    )
    with (
        patch.object(model.api, "generate", generate),
        patch.object(judge.api, "generate", generate),
    ):
        if not own and turn == "completed_and_pending":
            with pytest.raises(ResponseFilterError, match="server tool use"):
                await bridge_generate(
                    bridge,
                    model,
                    [ChatMessageUser(content="hi")],
                    [],
                    None,
                    GenerateConfig(),
                    requested_model=None,
                )
            return
        output, _ = await bridge_generate(
            bridge,
            model,
            [ChatMessageUser(content="hi")],
            [],
            None,
            GenerateConfig(),
            requested_model=None,
        )

    handed = output.message
    if own:
        assert judge is model or judge.api is not model.api
        assert handed.id == regenerated.message.id
        assert _pending_container_for_input([handed]) == CONTAINER_ID
        assert await _render_anthropic(handed) == await _render_anthropic(
            regenerated.message
        )
    else:
        assert str(judge) == str(model) or client == "other_name"
        assert handed.id != regenerated.message.id
        assert PENDING_CODE not in json.dumps(await _render_anthropic(handed))
        assert _pending_container_for_input([handed]) is None


_DEFAULT_ENDPOINTS = {
    "anthropic/claude-sonnet-4-5": "https://api.anthropic.com",
    "openai/gpt-4.1": "https://api.openai.com/v1",
    "google/gemini-2.5-flash": "https://generativelanguage.googleapis.com",
}


@pytest.mark.parametrize("model_name", list(_DEFAULT_ENDPOINTS))
@pytest.mark.parametrize(
    "endpoints",
    [
        "default_endpoint",
        "default_endpoint_slash",
        "trailing_slash",
        "case_and_port",
        "env_endpoint",
        "endpoint",
        "account",
    ],
)
def test_same_client_compares_the_endpoint_each_client_resolved(
    model_name: str, endpoints: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Base URLs naming the endpoint a client resolved are the same client.

    An explicit default endpoint, one from the environment, or a base URL that
    differs only by a trailing slash, letter case or the scheme's default port
    is the endpoint the bridged client uses; another endpoint or API key is
    another client.
    """
    from inspect_ai.agent._bridge.util import _same_client

    env_var = {
        "anthropic": "ANTHROPIC_BASE_URL",
        "openai": "OPENAI_BASE_URL",
        "google": "GOOGLE_BASE_URL",
    }[model_name.split("/")[0]]
    for name in ("ANTHROPIC_BASE_URL", "OPENAI_BASE_URL", "GOOGLE_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    default = _DEFAULT_ENDPOINTS[model_name]
    alternate = "https://alternate.example.com/v1"
    bridged_url: str | None = None
    judge_key = "primary-key"
    match endpoints:
        case "default_endpoint":
            judge_url = default
        case "default_endpoint_slash":
            judge_url = default + "/"
        case "trailing_slash":
            bridged_url, judge_url = alternate, alternate + "/"
        case "case_and_port":
            bridged_url = alternate
            judge_url = "HTTPS://Alternate.Example.com:443/v1"
        case "env_endpoint":
            monkeypatch.setenv(env_var, alternate)
            judge_url = alternate + "/"
        case "endpoint":
            judge_url = alternate
        case "account":
            judge_url, judge_key = default, "other-key"
        case _:
            raise AssertionError(endpoints)
    bridged = get_model(
        model_name, api_key="primary-key", base_url=bridged_url, memoize=False
    )
    judge = get_model(model_name, api_key=judge_key, base_url=judge_url, memoize=False)

    assert bridged.api.base_url != judge.api.base_url
    assert _same_client(judge, bridged) == (endpoints not in ("endpoint", "account"))


@pytest.mark.parametrize(
    ("a", "b", "same"),
    [
        ("https://api.example.com/v1", "HTTPS://API.Example.com:443/v1/", True),
        ("http://localhost:80/v1", "http://localhost/v1", True),
        ("https://api.example.com/v1#frag", "https://api.example.com/v1", True),
        ("https://api.example.com/v1", "https://api.example.com/V1", False),
        ("https://api.example.com/v1", "https://api.example.com:8443/v1", False),
        ("https://api.example.com/v1", "http://api.example.com/v1", False),
        ("https://u:p@api.example.com/v1", "https://api.example.com/v1", False),
        ("https://api.example.com/v1?t=a", "https://api.example.com/v1?t=b", False),
        ("http://[::1]:8000/v1", "http://[::1]:8000/v1/", True),
    ],
)
def test_normalized_endpoint_keeps_what_can_name_another_endpoint(
    a: str, b: str, same: bool
) -> None:
    from inspect_ai.agent._bridge.util import _normalized_endpoint

    assert (_normalized_endpoint(a) == _normalized_endpoint(b)) == same


def test_same_client_with_an_unresolved_lazy_vllm_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A lazy vLLM model whose server is not yet resolved has no client to read.

    It is not the client of one whose server is resolved, and comparing them
    doesn't fail.
    """
    from inspect_ai.agent._bridge.util import _same_client
    from inspect_ai.model._providers.vllm import VLLMAPI

    monkeypatch.setattr("inspect_ai.model._providers.vllm._vllm_servers", {})
    monkeypatch.setenv("VLLM_BASE_URL", "http://localhost:8000/v1")
    resolved = get_model("vllm/meta/llama", memoize=False)
    unresolved = get_model("vllm/meta/llama", memoize=False)
    assert isinstance(resolved.api, VLLMAPI)
    resolved.api._resolve_server()

    assert resolved.model_args == unresolved.model_args
    assert not hasattr(unresolved.api, "client")
    assert not _same_client(unresolved, resolved)
    assert not _same_client(resolved, unresolved)


RegenerationConfig = Literal[
    "none",
    "temperature",
    "request",
    "request_temperature",
    "request_shape",
    "request_alternate_key",
    "request_extra_body",
    "request_alternate_key_in_place",
]


@pytest.mark.parametrize("regeneration", get_args(RegenerationConfig))
async def test_response_filter_regeneration_of_a_request_with_agent_headers(
    regeneration: RegenerationConfig,
) -> None:
    """A regeneration is the bridged client's own with the request's config or none.

    The bridged request carries headers the agent sent. Regenerating with no
    config, or with the config the filter is given, with another temperature
    or request shape (system message, parallel tool calls, logprobs) or not,
    keeps the regeneration's completed and pending server work. Adding an API
    key header, also by changing the given config in place, or body fields is
    another client: its completed server items are rejected.
    """
    from unittest.mock import patch

    from inspect_ai.model._providers.anthropic import _pending_container_for_input

    init_sample_anthropic_assistant_internal()
    regenerated = await _regenerated_output("completed_and_pending")
    model_name = "anthropic/claude-sonnet-4-5"
    model = get_model(model_name, api_key="primary-key", memoize=False)
    outputs = [ModelOutput.from_content(model_name, "first"), regenerated]

    async def generate(*args: Any, **kwargs: Any) -> ModelOutput:
        return outputs.pop(0)

    async def regenerate(
        model: Model, output: ModelOutput, generate_input: GenerateInput
    ) -> ModelOutput | None:
        request = generate_input.config
        match regeneration:
            case "none":
                return await model.generate(generate_input.input)
            case "temperature":
                config = GenerateConfig(temperature=0.9)
            case "request":
                config = request
            case "request_temperature":
                config = request.merge(GenerateConfig(temperature=0.9))
            case "request_shape":
                config = request.merge(
                    GenerateConfig(
                        system_message="Be careful.",
                        parallel_tool_calls=False,
                        logprobs=True,
                        reasoning_summary="auto",
                    )
                )
            case "request_alternate_key":
                config = request.merge(
                    GenerateConfig(
                        extra_headers={
                            **(request.extra_headers or {}),
                            "x-api-key": "alternate-key",
                        }
                    )
                )
            case "request_extra_body":
                config = request.merge(
                    GenerateConfig(extra_body={"service_tier": "priority"})
                )
            case "request_alternate_key_in_place":
                assert request.extra_headers is not None
                request.extra_headers["x-api-key"] = "alternate-key"
                config = request
            case _:
                assert_never(regeneration)
        return await model.generate(generate_input.input, config=config)

    bridge = AgentBridge(AgentState(messages=[]))
    bridge.response_filter = regenerate
    request_config = GenerateConfig(
        temperature=0.2,
        extra_headers={"anthropic-beta": "client-beta", "accept-encoding": "gzip"},
    )
    with patch.object(model.api, "generate", generate):
        if regeneration not in (
            "none",
            "temperature",
            "request",
            "request_temperature",
            "request_shape",
        ):
            with pytest.raises(ResponseFilterError, match="server tool use"):
                await bridge_generate(
                    bridge,
                    model,
                    [ChatMessageUser(content="hi")],
                    [],
                    None,
                    request_config,
                    requested_model=None,
                )
            return
        output, _ = await bridge_generate(
            bridge,
            model,
            [ChatMessageUser(content="hi")],
            [],
            None,
            request_config,
            requested_model=None,
        )

    handed = output.message
    assert handed.id == regenerated.message.id
    assert _pending_container_for_input([handed]) == CONTAINER_ID
    assert await _render_anthropic(handed) == await _render_anthropic(
        regenerated.message
    )


@pytest.mark.parametrize("server_items", [False, True])
@pytest.mark.parametrize("headers", ["none", "foreign"])
async def test_response_filter_regeneration_through_a_sidecar(
    headers: Literal["none", "foreign"],
    server_items: bool,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A regeneration through a sentinel sidecar is the bridged client's own.

    Inspect adds `x-inspect-context` to each call through the sidecar, the
    filter's own `model.generate(...)` included, and the bridged request's
    config is resolved without it. The regeneration still keeps its id and
    its completed server search. Adding another header (an alternate
    `x-api-key`) is still another client: its reply gets an edited id and its
    server items are rejected.
    """
    import httpx2
    from test_helpers.stand_in_sidecar import StandInSidecar, Turn

    from inspect_ai import Task, eval_async
    from inspect_ai.dataset import Sample
    from inspect_ai.solver import Generate, Solver, TaskState, solver

    monkeypatch.delenv("ANTHROPIC_AUTH_TOKEN", raising=False)

    class ServerItemsSidecar(StandInSidecar):
        def _handle(self, request: httpx2.Request) -> httpx2.Response:
            response = super()._handle(request)
            if request.url.path == "/v1/messages" and len(self.model_calls) == 2:
                payload = response.json()
                payload["content"] += PENDING_SPAN_BLOCKS["completed_and_pending"]
                return httpx2.Response(200, json=payload)
            return response

    proceed = {"outcome": "proceed", "steps": []}
    stand_in = (ServerItemsSidecar if server_items else StandInSidecar)(
        turns=[
            Turn(text="first", judgment=proceed),
            Turn(text="regenerated", judgment=proceed),
        ]
    )
    model = get_model(
        "anthropic/claude-haiku-4-5",
        api_key="test-key",
        base_url="http://proxy.test",
        memoize=False,
        streaming=False,
        config=GenerateConfig(max_tokens=1024),
        http_client=stand_in.http_client(),
    )
    seen: dict[str, str] = {}

    async def regenerate(
        model: Model, output: ModelOutput, generate_input: GenerateInput
    ) -> ModelOutput | None:
        config = (
            GenerateConfig(extra_headers={"x-api-key": "alternate-key"})
            if headers == "foreign"
            else GenerateConfig()
        )
        replacement = await model.generate(generate_input.input, config=config)
        seen["regenerated"] = replacement.message.id or ""
        return replacement

    @solver
    def through_bridge() -> Solver:
        async def solve(state: TaskState, generate: Generate) -> TaskState:
            bridge = AgentBridge(
                AgentState(messages=state.messages), response_filter=regenerate
            )
            output, _ = await bridge_generate(
                bridge,
                model,
                state.messages,
                [],
                None,
                GenerateConfig(),
                requested_model=None,
            )
            seen["handed"] = output.message.id or ""
            state.messages.append(output.message)
            return state

        return solve

    [log] = await eval_async(
        Task(dataset=[Sample(input="Hi")], solver=through_bridge()),
        model=model,
        sentinel_proxy="auto",
        log_dir=str(tmp_path),
        fail_on_error=False,
    )

    assert log.samples is not None
    [sample] = log.samples
    model_events = [e for e in sample.events if isinstance(e, ModelEvent)]
    assert len(model_events) == 2
    assert all(
        "x-inspect-context" in (e.config.extra_headers or {}) for e in model_events
    )
    if headers == "foreign" and server_items:
        assert sample.error is not None
        assert "server tool use 'srvtoolu_ws'" in sample.error.message
        return
    assert sample.error is None
    if headers == "none":
        assert seen["handed"] == seen["regenerated"]
    else:
        assert seen["handed"] != seen["regenerated"]


def test_bridged_generation_config_allowlist_names_generate_config_fields() -> None:
    """Every allowlisted field is a `GenerateConfig` field, so none is a typo."""
    assert _CLIENT_NEUTRAL_CONFIG_FIELDS <= GenerateConfig.model_fields.keys()
    assert not _CLIENT_NEUTRAL_CONFIG_FIELDS & {
        "extra_headers",
        "extra_body",
        "fallback_models",
        "batch",
        "cache",
    }


@pytest.mark.parametrize(
    "before,after", [(False, 0), (0, False)], ids=["False to 0", "0 to False"]
)
async def test_response_filter_annotated_regeneration_with_an_edit_is_an_edit(
    before: JsonValue, after: JsonValue
) -> None:
    """Annotating a regeneration does not hide an edit Pydantic equality misses."""
    regenerated = ModelOutput.for_tool_call("mockllm/model", "f", {"n": before})
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.from_content("mockllm/model", "first"),
            regenerated,
        ],
    )

    async def annotate_and_edit(
        model: Model, output: ModelOutput, generate_input: GenerateInput
    ) -> ModelOutput | None:
        output = await model.generate(generate_input.input)
        assert output.message.tool_calls
        output.message.tool_calls[0].arguments["n"] = after
        output.message.metadata = {"review": "accepted"}
        return output

    bridge = AgentBridge(AgentState(messages=[]))
    bridge.response_filter = annotate_and_edit
    output, _ = await bridge_generate(
        bridge,
        model,
        [ChatMessageUser(content="hi")],
        [],
        None,
        GenerateConfig(),
        requested_model=None,
    )

    assert output.message.id != regenerated.message.id
    assert output.message.tool_calls
    assert output.message.tool_calls[0].arguments == {"n": after}


async def test_response_filter_rejects_merging_server_items_across_choices() -> None:
    """Server tool items of two choices cannot share one message id."""

    def tool_use(id: str) -> ContentToolUse:
        return ContentToolUse(
            tool_type="web_search", id=id, name="web_search", arguments="{}", result=""
        )

    provider_output = ModelOutput(
        model="mockllm/model",
        choices=[
            ChatCompletionChoice(
                message=ChatMessageAssistant(id=f"msg_{n}", content=[tool_use(n)]),
                stop_reason="stop",
            )
            for n in ("a", "b")
        ],
    )

    async def merging_filter(
        model: Model, output: ModelOutput, generate_input: GenerateInput
    ) -> ModelOutput | None:
        merged = [c for choice in output.choices for c in _content_items_of(choice)]
        output.choices = [
            ChatCompletionChoice(
                message=ChatMessageAssistant(content=merged), stop_reason="stop"
            )
        ]
        return output

    bridge = AgentBridge(AgentState(messages=[]))
    bridge.response_filter = merging_filter
    with pytest.raises(ResponseFilterError, match="different choices"):
        await bridge_generate(
            bridge,
            get_model("mockllm/model", custom_outputs=[provider_output]),
            [ChatMessageUser(content="hi")],
            [],
            None,
            GenerateConfig(),
            requested_model=None,
        )


def _content_items_of(choice: ChatCompletionChoice) -> list[Content]:
    assert isinstance(choice.message.content, list)
    return choice.message.content


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


def test_settle_message_ids_derives_a_replacement_from_what_it_replaces() -> None:
    """A fresh replacement is an edit of the original at its index; an unchanged choice keeps its id."""
    original = ModelOutput(
        model="mockllm/model",
        choices=[
            ChatCompletionChoice(message=ChatMessageAssistant(content=text))
            for text in ["one", "two"]
        ],
    )
    replaced = ModelOutput(
        model="mockllm/model",
        choices=[
            ChatCompletionChoice(message=ChatMessageAssistant(content="replacement")),
            original.choices[1].model_copy(),
            ChatCompletionChoice(message=ChatMessageAssistant(content="extra")),
        ],
    )

    extra_id = replaced.choices[2].message.id
    _settle_message_ids(original, replaced)

    first = replaced.choices[0].message
    assert first.id == edited_id(original.choices[0].message.id, first)
    assert replaced.choices[1].message.id == original.choices[1].message.id
    assert replaced.choices[2].message.id == extra_id
    assert all(choice.message.metadata is None for choice in replaced.choices)


def test_settle_message_ids_gives_the_same_edit_the_same_id() -> None:
    """Filtering the same output the same way (e.g. a cache hit) is the same message."""
    original = ModelOutput.from_content("mockllm/model", "before")

    def edited(text: str) -> ModelOutput:
        copy = original.model_copy(deep=True)
        copy.message.content = text
        _settle_message_ids(original, copy)
        return copy

    first, second, other = edited("after"), edited("after"), edited("other")

    assert first.message.id == second.message.id != original.message.id
    assert other.message.id not in {first.message.id, original.message.id}
    assert first.message.id == edited_id(original.message.id, first.message)


@pytest.mark.parametrize(
    "before,after,changed",
    [
        (0, False, True),
        (False, 0, True),
        (1, True, True),
        (True, 1, True),
        (1, 1.0, False),
        (1.0, 1, False),
    ],
    ids=["0 to False", "False to 0", "1 to True", "True to 1", "1 to 1.0", "1.0 to 1"],
)
def test_settle_message_ids_tells_booleans_from_numbers(
    before: JsonValue, after: JsonValue, changed: bool
) -> None:
    """A filter changing a call argument between a number and a boolean edits the reply; an equal JSON number doesn't."""
    original = ModelOutput.for_tool_call("mockllm/model", "f", {"n": before})
    copy = original.model_copy(deep=True)
    assert copy.message.tool_calls
    copy.message.tool_calls[0].arguments = {"n": after}

    _settle_message_ids(original, copy)

    if changed:
        assert copy.message.id == edited_id(original.message.id, copy.message)
        assert copy.message.id != original.message.id
    else:
        assert copy.message.id == original.message.id


class _FilterWork(NamedTuple):
    events_visited: int
    response_generations: list[int]
    """Generations each response filter had to choose from."""
    request_generations_found: int


@pytest.mark.parametrize("filter_kind", ["request", "response"])
async def test_concurrent_generating_filters_do_linear_work(
    filter_kind: Literal["request", "response"],
) -> None:
    """A filter's own generations are found without visiting other requests' events.

    N bridged requests share a sample and model, and each filter generates once,
    all N generations in flight together. The events visited in total grow
    linearly with N, and each filter finds exactly its own generation.
    """
    from contextvars import ContextVar
    from unittest.mock import patch

    from inspect_ai.agent._bridge import util as bridge_util
    from inspect_ai.log._transcript import (
        Transcript,
        TranscriptHistory,
        init_transcript,
    )

    config = GenerateConfig(max_connections=256)
    in_filter: ContextVar[bool] = ContextVar("in_filter", default=False)

    async def measure(n: int) -> _FilterWork:
        init_transcript(Transcript())
        model = get_model("mockllm/model")
        provider_generate = model.api.generate
        entered = 0
        all_entered = anyio.Event()
        visited = 0
        generations_seen: list[int] = []
        request_generations_found = 0

        async def overlapping_generate(*args: Any, **kwargs: Any) -> Any:
            nonlocal entered
            if in_filter.get():
                entered += 1
                if entered == n:
                    all_entered.set()
                await all_entered.wait()
            return await provider_generate(*args, **kwargs)

        async def response_filter(
            model: Model, output: ModelOutput, generate_input: GenerateInput
        ) -> ModelOutput | None:
            token = in_filter.set(True)
            try:
                return await model.generate(generate_input.input, config=config)
            finally:
                in_filter.reset(token)

        async def request_filter(
            model: Model,
            messages: list[ChatMessage],
            tools: list[ToolInfo],
            tool_choice: ToolChoice | None,
            config: GenerateConfig,
        ) -> ModelOutput | GenerateInput | None:
            token = in_filter.set(True)
            try:
                return await model.generate(messages, config=config)
            finally:
                in_filter.reset(token)

        recent_events = TranscriptHistory.recent_events
        settle = bridge_util._settle_message_ids
        request_filter_edits = bridge_util._request_filter_edits

        def counting_recent_events(
            history: TranscriptHistory, count: int | None = None
        ) -> Sequence[Any]:
            nonlocal visited
            events = recent_events(history, count)
            visited += len(events)
            return events

        def recording_settle(
            original: ModelOutput,
            filtered: ModelOutput,
            generations: Sequence[ChatMessageAssistant] = (),
        ) -> None:
            generations_seen.append(len(generations))
            settle(original, filtered, generations)

        def recording_request_filter_edits(
            generated: ModelOutput, output: ModelOutput
        ) -> ModelOutput:
            nonlocal request_generations_found
            assert generated.message.id == output.message.id
            request_generations_found += 1
            return request_filter_edits(generated, output)

        async def request(i: int) -> None:
            bridge = AgentBridge(AgentState(messages=[]))
            if filter_kind == "response":
                bridge.response_filter = response_filter
            else:
                bridge.filter = request_filter
            await bridge_generate(
                bridge,
                model,
                [ChatMessageUser(content=f"Question {i}")],
                [],
                None,
                config,
                requested_model=None,
            )

        with (
            patch.object(model.api, "generate", overlapping_generate),
            patch.object(TranscriptHistory, "recent_events", counting_recent_events),
            patch.object(bridge_util, "_settle_message_ids", recording_settle),
            patch.object(
                bridge_util, "_request_filter_edits", recording_request_filter_edits
            ),
        ):
            async with anyio.create_task_group() as tg:
                for i in range(n):
                    tg.start_soon(request, i)
        return _FilterWork(visited, generations_seen, request_generations_found)

    for n in (16, 64):
        work = await measure(n)
        assert work.events_visited <= 2 * n
        if filter_kind == "response":
            assert work.response_generations == [1] * n
        else:
            assert work.request_generations_found == n


async def test_response_filter_monitor_generations_are_not_retained() -> None:
    """A monitor the filter starts, generating after the bridge returns, leaves no event alive."""
    import gc
    import weakref

    from inspect_ai.event import ModelEvent

    completed: list[weakref.ref[ModelEvent]] = []

    class WeakSink:
        def on_pending(self, event: ModelEvent) -> None:
            pass

        def on_complete(self, event: ModelEvent) -> None:
            completed.append(weakref.ref(event))

    model = get_model("mockllm/model")
    started, release, generated, finish = (anyio.Event() for _ in range(4))

    async def monitor() -> None:
        started.set()
        await release.wait()
        for n in range(8):
            await model.generate(f"monitor {n}")
        generated.set()
        await finish.wait()

    sink = WeakSink()
    async with anyio.create_task_group() as tg:

        async def start_monitor(
            model: Model, output: ModelOutput, generate_input: GenerateInput
        ) -> ModelOutput | None:
            tg.start_soon(monitor)
            await started.wait()
            return output

        bridge = AgentBridge(AgentState(messages=[]), response_filter=start_monitor)
        bridge.model_event_sink = sink
        with use_model_event_sink(sink):
            await bridge_generate(
                bridge,
                model,
                [ChatMessageUser(content="hi")],
                [],
                None,
                GenerateConfig(),
                requested_model=None,
            )
        release.set()
        await generated.wait()
        gc.collect()
        retained = sum(ref() is not None for ref in completed)
        finish.set()

    assert len(completed) == 9
    assert retained == 0


@pytest.mark.parametrize("returned", ["regeneration", "output"])
async def test_response_filter_reasoning_internal_boolean_to_number_is_an_edit(
    returned: Literal["regeneration", "output"],
) -> None:
    """Changing reasoning's provider-internal `False` to `0` is rejected as a reasoning edit.

    Pydantic equality takes them as equal; they serialize differently.
    """
    message = ChatMessageAssistant(
        content=[
            ContentReasoning(
                reasoning="thinking", signature="sig", internal={"flag": False}
            ),
            ContentText(text="answer"),
        ]
    )
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.from_message(message),
            ModelOutput.from_message(message.model_copy(deep=True)),
        ],
    )

    async def edit_internal(
        model: Model, output: ModelOutput, generate_input: GenerateInput
    ) -> ModelOutput | None:
        if returned == "regeneration":
            output = await model.generate(generate_input.input)
        content = output.message.content
        assert isinstance(content, list)
        content[0].internal = {"flag": 0}
        return output

    bridge = AgentBridge(AgentState(messages=[]))
    bridge.response_filter = edit_internal
    with pytest.raises(ResponseFilterError, match="edited or added reasoning"):
        await bridge_generate(
            bridge,
            model,
            [ChatMessageUser(content="hi")],
            [],
            None,
            GenerateConfig(),
            requested_model=None,
        )


@pytest.mark.parametrize(
    "edit,unchanged",
    [
        ("metadata", True),
        ("text internal", False),
        ("reasoning internal", False),
    ],
)
def test_is_unchanged_ignores_only_metadata(edit: str, unchanged: bool) -> None:
    """A metadata annotation leaves a generation unchanged; a `False` to `0` edit elsewhere does not."""
    generation = ChatMessageAssistant(
        content=[
            ContentReasoning(
                reasoning="thinking", signature="sig", internal={"flag": False}
            ),
            ContentText(text="answer", internal={"flag": False}),
        ]
    )
    returned = generation.model_copy(deep=True)
    content = cast(list[Content], returned.content)
    match edit:
        case "metadata":
            returned.metadata = {"review": "accepted"}
        case "text internal":
            content[1].internal = {"flag": 0}
        case "reasoning internal":
            content[0].internal = {"flag": 0}

    assert _is_unchanged(returned, [generation]) is unchanged


async def test_sandbox_text_edit_of_a_regeneration_keeps_its_tool_arguments() -> None:
    """A regeneration's arguments the filter leaves alone are not its edit, though it edits the text."""
    events_tool = ToolInfo(
        name="get_events",
        description="List events on a date.",
        parameters=ToolParams(properties={"date": ToolParam(type="string")}),
    )
    provider_call = parse_tool_call("call_1", "get_events", "2024-01-01", [events_tool])
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.from_content("mockllm/model", "first"),
            ModelOutput.from_message(
                ChatMessageAssistant(content="", tool_calls=[provider_call]),
                stop_reason="tool_calls",
            ),
        ],
    )

    async def regenerate_and_edit_text(
        model: Model, output: ModelOutput, generate_input: GenerateInput
    ) -> ModelOutput | None:
        output = await model.generate(generate_input.input)
        output.message.content = "Looking up events"
        return output

    bridge = _sandbox_bridge(regenerate_and_edit_text, model)
    reply = await _forward_provider_errors(
        generate_anthropic(None, None, bridge), bridge
    )({"model": "inspect", "max_tokens": 1024, "messages": CHAT_REQUEST["messages"]})

    assert PROVIDER_ERROR_KEY not in reply
    assert not bridge._failure_requested.is_set()
    tool_use = cast(list[dict[str, JsonValue]], reply["content"])[-1]
    assert tool_use["input"] == {"date": "2024-01-01"}
