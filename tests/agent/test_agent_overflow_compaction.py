"""Tests for forced-compaction recovery in the react agent's overflow path."""

import json
from typing import Any, Literal

import httpx2
import pytest
from openai import DefaultAsyncHttpxClient
from typing_extensions import override

from inspect_ai import Task, eval
from inspect_ai.agent import Agent, AgentState, react
from inspect_ai.dataset import Sample
from inspect_ai.event import CompactionEvent
from inspect_ai.model import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageUser,
    GenerateConfig,
    Model,
    ModelOutput,
    get_model,
)
from inspect_ai.model._compaction import CompactionStrategy
from inspect_ai.model._compaction.auto import CompactionAuto
from inspect_ai.model._compaction.edit import CompactionEdit
from inspect_ai.model._compaction.summary import CompactionSummary
from inspect_ai.model._compaction.trim import CompactionTrim
from inspect_ai.tool import Tool, tool
from inspect_ai.tool._tool_info import ToolInfo


@tool
def lookup() -> Tool:
    async def execute() -> str:
        """Look up a value."""
        return "value " * 50

    return execute


def _lookup_turns(count: int) -> list[ModelOutput]:
    return [
        ModelOutput.for_tool_call(
            model="mockllm/model", tool_name="lookup", tool_arguments={}
        )
        for _ in range(count)
    ]


def _overflow_output() -> ModelOutput:
    return ModelOutput.from_content(
        model="mockllm/model",
        content="Failed turn (overflow)",
        stop_reason="model_length",
    )


def _done_output(submit: bool) -> ModelOutput:
    if submit:
        return ModelOutput.for_tool_call(
            model="mockllm/model",
            tool_name="submit",
            tool_arguments={"answer": "done"},
        )
    return ModelOutput.from_content(model="mockllm/model", content="done")


class _AlwaysRaisesCompaction(CompactionStrategy):
    """Test-only strategy that always raises when compact() is called."""

    def __init__(self) -> None:
        # High threshold so predictive compaction never triggers; only
        # forced compaction (force=True) will invoke compact().
        super().__init__(type="trim", threshold=10_000, memory=False)

    @override
    async def compact(
        self, model: Model, messages: list[ChatMessage], tools: list[ToolInfo]
    ) -> tuple[list[ChatMessage], ChatMessageUser | None]:
        raise RuntimeError("simulated compaction failure")


@pytest.mark.parametrize(
    "react_factory",
    [
        pytest.param(lambda **kw: react(**kw), id="react"),
        pytest.param(
            lambda **kw: react(submit=False, **kw),  # exercises react_no_submit path
            id="react_no_submit",
        ),
    ],
)
def test_model_length_with_compaction_triggers_force_and_continues(
    react_factory,
) -> None:
    """Forced compaction recovers from model_length when compaction is configured.

    When generate returns model_length and compaction is configured,
    the overflow handler invokes forced compaction and the agent continues.
    """
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.from_content(
                model="mockllm/model",
                content="Failed turn (overflow)",
                stop_reason="model_length",
            ),
            ModelOutput.from_content(
                model="mockllm/model",
                content="Recovered after compaction",
            ),
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="submit",
                tool_arguments={"answer": "done"},
            ),
        ],
    )

    task = Task(
        dataset=[Sample(input="Test", target="done")],
        solver=react_factory(
            compaction=CompactionTrim(threshold=10_000),
        ),
    )

    log = eval(task, model=model)[0]
    assert log.status == "success", f"Agent should have recovered. Status: {log.status}"

    # Verify the recovery emitted a CompactionEvent with trigger=forced.
    # This confirms _handle_overflow invoked compact_input(force=True).
    from inspect_ai.event import CompactionEvent

    assert log.samples
    events = [e for e in log.samples[0].events if isinstance(e, CompactionEvent)]
    triggers = [(e.metadata or {}).get("trigger") for e in events]
    assert "forced" in triggers, (
        f"Expected a CompactionEvent with metadata.trigger='forced' "
        f"from overflow recovery; got triggers {triggers}"
    )


@pytest.mark.parametrize(
    "strategy_factory",
    [
        pytest.param(
            lambda: CompactionTrim(threshold=10_000, preserve=0.5),
            id="trim",
        ),
        # CompactionEdit reduces message content (replaces tool results
        # with TOOL_RESULT_REMOVED) but not message count, so recovery
        # must not gate on length reduction.
        pytest.param(
            lambda: CompactionEdit(threshold=10_000, keep_tool_uses=0),
            id="edit",
        ),
    ],
)
def test_model_length_with_compaction_recovers_and_continues(strategy_factory) -> None:
    """With a realistic conversation, forced compaction recovers and the agent continues.

    The submit answer is the canary -- if the agent broke out on overflow
    instead of recovering, it would never reach submit. We additionally
    assert there are no duplicate message IDs in the recovered history,
    which guards against summary-style strategies where the c_message
    object is also the last element of the compacted input.
    """
    # Build conversation: 10 plain turns (each adds an assistant message
    # and a default-continue user prompt = 20 messages), then overflow,
    # then recovery, then submit.
    custom_outputs = [
        ModelOutput.from_content(model="mockllm/model", content=f"Turn {i}")
        for i in range(10)
    ]
    custom_outputs.extend(
        [
            ModelOutput.from_content(
                model="mockllm/model",
                content="Failed turn (overflow)",
                stop_reason="model_length",
            ),
            ModelOutput.from_content(
                model="mockllm/model",
                content="Recovered after compaction",
            ),
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="submit",
                tool_arguments={"answer": "done"},
            ),
        ]
    )

    model = get_model("mockllm/model", custom_outputs=custom_outputs)

    task = Task(
        dataset=[Sample(input="Test", target="done")],
        solver=react(compaction=strategy_factory()),
        message_limit=100,
    )

    log = eval(task, model=model)[0]
    assert log.status == "success"

    # Canary: the submit was reached only if the agent recovered from overflow.
    assert log.samples
    output_text = log.samples[0].output.completion or ""
    assert "done" in output_text, (
        f"Expected agent to reach submit after overflow recovery; "
        f"got output completion: {output_text!r}"
    )

    # Recovered history should not contain duplicate message IDs
    # (e.g., a summary appearing as both compacted[-1] and c_message).
    ids = [m.id for m in log.samples[0].messages if m.id]
    assert len(ids) == len(set(ids)), (
        f"Duplicate message IDs detected in recovered history: {ids}"
    )


def test_model_length_with_compaction_failure_falls_through_to_filter() -> None:
    """Falls through to overflow filter when forced compaction fails.

    If forced compaction raises (e.g., RuntimeError 'compaction insufficient'),
    the existing overflow filter takes over.
    """
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.from_content(
                model="mockllm/model",
                content="Failed turn (overflow)",
                stop_reason="model_length",
            ),
            ModelOutput.from_content(
                model="mockllm/model",
                content="Recovered after truncation",
            ),
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="submit",
                tool_arguments={"answer": "done"},
            ),
        ],
    )

    # Use a strategy that always raises when compact() is invoked.
    # The high threshold ensures predictive compaction never triggers;
    # only forced compaction in _handle_overflow will invoke compact().
    impossible_strategy = _AlwaysRaisesCompaction()

    task = Task(
        dataset=[Sample(input="Test", target="done")],
        solver=react(
            compaction=impossible_strategy,
            truncation="auto",  # Falls back to message-trim filter
        ),
    )

    log = eval(task, model=model)[0]
    assert log.status == "success", (
        "Agent should have recovered via the truncation filter even when "
        f"forced compaction fails. Status: {log.status}"
    )


def test_model_length_without_recovery_terminates() -> None:
    """No compaction, no overflow filter: the agent terminates cleanly."""
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.from_content(
                model="mockllm/model",
                content="Failed turn (overflow)",
                stop_reason="model_length",
            ),
        ],
    )

    task = Task(
        dataset=[Sample(input="Test", target="done")],
        solver=react(),  # No compaction, default truncation="disabled"
    )

    log = eval(task, model=model)[0]
    # Agent should NOT have submitted (no successful path).
    assert log.samples
    sample = log.samples[0]
    last_message = sample.messages[-1] if sample.messages else None
    if last_message is not None:
        # If there's a final message, it should be the failed assistant turn,
        # not a submit tool call.
        assert "submit" not in (
            last_message.content if isinstance(last_message.content, str) else ""
        ), "Agent should not have reached submit when no recovery is configured"


class _WithholdsPrefixCompaction(CompactionStrategy):
    """Native-shaped strategy, matching CompactionNative on Anthropic."""

    def __init__(self) -> None:
        # High threshold so only forced compaction (force=True) invokes this.
        super().__init__(type="summary", threshold=10_000, memory=False)

    @property
    @override
    def preserve_prefix(self) -> bool:
        # the provider re-emits or encodes the user turns itself
        return False

    @override
    async def compact(
        self, model: Model, messages: list[ChatMessage], tools: list[ToolInfo]
    ) -> tuple[list[ChatMessage], ChatMessageUser | None]:
        return [
            ChatMessageAssistant(content="[COMPACTED BLOCK]"),
            ChatMessageUser(content="Please continue working."),
        ], None


def test_overflow_recovery_keeps_the_conversation_in_the_record() -> None:
    """What a strategy withholds from the model must still reach the record."""
    task_prompt = "UNIQUE-TASK-PROMPT: solve the widget problem."
    sentinel = "SENTINEL-EARLY-TURN"
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.from_content(model="mockllm/model", content=sentinel),
            ModelOutput.from_content(
                model="mockllm/model",
                content="Failed turn (overflow)",
                stop_reason="model_length",
            ),
            ModelOutput.from_content(
                model="mockllm/model", content="Recovered after compaction"
            ),
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="submit",
                tool_arguments={"answer": "done"},
            ),
        ],
    )

    task = Task(
        dataset=[Sample(input=task_prompt, target="done")],
        solver=react(compaction=_WithholdsPrefixCompaction()),
    )

    log = eval(task, model=model)[0]
    assert log.status == "success"
    assert log.samples

    # without this, the agent simply terminating would satisfy the
    # history assertions vacuously
    compaction_events = [
        e for e in log.samples[0].events if isinstance(e, CompactionEvent)
    ]
    assert "forced" in [(e.metadata or {}).get("trigger") for e in compaction_events]
    assert "done" in (log.samples[0].output.completion or "")

    texts = [m.text for m in log.samples[0].messages]
    assert any(task_prompt in t for t in texts), (
        f"sample input missing from the recorded conversation: {texts}"
    )
    assert any(sentinel in t for t in texts), (
        f"pre-overflow turn missing from the recorded conversation: {texts}"
    )
    assert not any("Failed turn (overflow)" in t for t in texts), (
        f"the failed overflow turn should not be recorded: {texts}"
    )

    # the retry must be sent the handler's reduced view, not the retained
    # record — otherwise it would overflow again immediately
    retry_input = [e.input for e in log.samples[0].events if e.event == "model"][-1]
    retry_texts = [m.text for m in retry_input]
    assert any("[COMPACTED BLOCK]" in t for t in retry_texts), (
        f"retry was not sent the compacted view: {retry_texts}"
    )
    assert not any(sentinel in t or task_prompt in t for t in retry_texts), (
        f"retry re-sent messages the strategy withheld: {retry_texts}"
    )


def _overflow_executor(calls: list[str]) -> Agent:
    """Bare callable as the model: always reports a context overflow."""

    async def execute(state: AgentState, tools: list[Tool]) -> AgentState:
        calls.append("call")
        if len(calls) > 3:
            raise RuntimeError(
                "overflow recovery looped: the agent was handed the same "
                "overflowing conversation again"
            )
        state.output = ModelOutput.from_content(
            model="custom/agent",
            content="Failed turn (overflow)",
            stop_reason="model_length",
        )
        state.messages.append(state.output.message)
        return state

    return execute


@pytest.mark.parametrize("submit", [True, False], ids=["react", "react_no_submit"])
def test_custom_agent_model_does_not_loop_on_overflow(submit: bool) -> None:
    """Forced compaction must not claim recovery for a directly-invoked model.

    `_agent_generate` invokes anything that is not `str | Model | None`
    itself, so it never consults the compaction handler, and claiming
    recovery would hand it the same conversation forever. The dispatch is
    structural, so an unregistered callable is the case that discriminates.
    """
    calls: list[str] = []
    task = Task(
        dataset=[Sample(input="Test", target="done")],
        solver=react(
            model=_overflow_executor(calls),
            submit=submit,
            compaction=CompactionTrim(threshold=10_000, preserve=0.5),
        ),
    )

    log = eval(task, model="mockllm/model")[0]

    assert log.status == "success"
    assert len(calls) == 1, (
        f"expected the agent to be called once and then terminate; got {len(calls)}"
    )


def _forced_compactions(log: Any) -> int:
    return len(
        [
            e
            for e in log.samples[0].events
            if isinstance(e, CompactionEvent)
            and (e.metadata or {}).get("trigger") == "forced"
        ]
    )


@pytest.mark.parametrize("submit", [True, False], ids=["react", "react_no_submit"])
def test_overflow_after_forced_compaction_terminates(submit: bool) -> None:
    """A retry that overflows again does not force compaction a second time.

    The handler does not check that forced compaction shrank the input, so
    compacting again could resend the same request indefinitely. With no
    overflow filter the agent ends.
    """
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            *_lookup_turns(2),
            _overflow_output(),
            _overflow_output(),
            _done_output(submit),
        ],
    )

    task = Task(
        dataset=[Sample(input="Test", target="done")],
        solver=react(
            tools=[lookup()],
            submit=submit,
            compaction=CompactionEdit(threshold=10_000, keep_tool_uses=0),
        ),
    )

    log = eval(task, model=model)[0]
    assert log.status == "success"
    assert log.samples
    assert _forced_compactions(log) == 1
    assert len([e for e in log.samples[0].events if e.event == "model"]) == 4
    assert "done" not in (log.samples[0].output.completion or "")


@pytest.mark.parametrize("submit", [True, False], ids=["react", "react_no_submit"])
def test_overflow_after_forced_compaction_falls_back_to_filter(submit: bool) -> None:
    """A retry that overflows again goes to the overflow filter, not compaction."""
    filtered: list[int] = []

    async def drop_last(messages: list[ChatMessage]) -> list[ChatMessage]:
        filtered.append(len(messages))
        return messages[:-1]

    model = get_model(
        "mockllm/model",
        custom_outputs=[
            *_lookup_turns(2),
            _overflow_output(),
            _overflow_output(),
            _done_output(submit),
        ],
    )

    task = Task(
        dataset=[Sample(input="Test", target="done")],
        solver=react(
            tools=[lookup()],
            submit=submit,
            compaction=CompactionEdit(threshold=10_000, keep_tool_uses=0),
            truncation=drop_last,
        ),
    )

    log = eval(task, model=model)[0]
    assert log.status == "success"
    assert log.samples
    assert _forced_compactions(log) == 1
    assert len(filtered) == 1
    assert "done" in (log.samples[0].output.completion or "")


@pytest.mark.parametrize("submit", [True, False], ids=["react", "react_no_submit"])
def test_overflow_after_successful_retry_compacts_again(submit: bool) -> None:
    """An overflow after a retry that fit gets forced compaction again."""
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            *_lookup_turns(2),
            _overflow_output(),
            *_lookup_turns(1),
            _overflow_output(),
            _done_output(submit),
        ],
    )

    task = Task(
        dataset=[Sample(input="Test", target="done")],
        solver=react(
            tools=[lookup()],
            submit=submit,
            compaction=CompactionEdit(threshold=10_000, keep_tool_uses=0),
        ),
    )

    log = eval(task, model=model)[0]
    assert log.status == "success"
    assert log.samples
    assert _forced_compactions(log) == 2
    assert "done" in (log.samples[0].output.completion or "")


def _response_body(output: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "id": "resp",
        "object": "response",
        "created_at": 0,
        "model": "gpt-5.6-sol",
        "status": "completed",
        "output": output,
        "parallel_tool_calls": True,
        "tool_choice": "auto",
        "tools": [],
        "usage": {
            "input_tokens": 1,
            "output_tokens": 1,
            "total_tokens": 2,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens_details": {"reasoning_tokens": 0},
        },
    }


def _reasoning_and_lookup(n: int) -> list[dict[str, Any]]:
    return [
        {
            "type": "reasoning",
            "id": f"rs_{n}",
            "summary": [],
            "encrypted_content": f"ENCRYPTED-{n}",
        },
        {
            "type": "function_call",
            "id": f"fc_{n}",
            "call_id": f"call_{n}",
            "name": "lookup",
            "arguments": "{}",
            "status": "completed",
        },
    ]


def _final_output(request: dict[str, Any]) -> list[dict[str, Any]]:
    if "submit" in [tool.get("name") for tool in request.get("tools", [])]:
        return [
            {
                "type": "function_call",
                "id": "fc_submit",
                "call_id": "call_submit",
                "name": "submit",
                "arguments": json.dumps({"answer": "done"}),
                "status": "completed",
            }
        ]
    return [_text_output("done")]


def _text_output(text: str) -> dict[str, Any]:
    return {
        "type": "message",
        "id": "msg",
        "role": "assistant",
        "status": "completed",
        "content": [{"type": "output_text", "text": text, "annotations": []}],
    }


def _error_response(request: httpx2.Request, code: str) -> httpx2.Response:
    return httpx2.Response(
        400,
        json={
            "error": {
                "message": "Input exceeds the context window.",
                "type": "invalid_request_error",
                "param": "input",
                "code": code,
            }
        },
        request=request,
    )


def _openai_with_local_counting(
    status_code: int,
    turns: list[Literal["lookup", "overflow", "final"]],
    agent_requests: list[dict[str, Any]],
) -> Model:
    """OpenAI Responses model whose token-count endpoint is unavailable.

    Agent requests (those with tools) are answered from `turns` and recorded;
    a request beyond them fails the sample rather than looping. Requests
    without tools are summarization calls; the summary counts more than the
    turns it replaces, so the local count does not fall.
    """

    async def handler(request: httpx2.Request) -> httpx2.Response:
        if request.url.path in ("/v1/responses/input_tokens", "/v1/responses/compact"):
            return httpx2.Response(
                status_code,
                headers={"allow": "GET"} if status_code == 405 else {},
                json={"detail": f"HTTP {status_code}"},
                request=request,
            )
        assert request.url.path == "/v1/responses"
        body = json.loads(request.content)
        if not body.get("tools"):
            return httpx2.Response(
                200,
                json=_response_body([_text_output("SUMMARY " * 300)]),
                request=request,
            )
        agent_requests.append(body)
        if len(agent_requests) > len(turns):
            return _error_response(request, "unexpected_request")
        turn = turns[len(agent_requests) - 1]
        if turn == "overflow":
            return _error_response(request, "context_length_exceeded")
        output = (
            _reasoning_and_lookup(len(agent_requests))
            if turn == "lookup"
            else _final_output(body)
        )
        return httpx2.Response(200, json=_response_body(output), request=request)

    return get_model(
        "openai/gpt-5.6-sol",
        api_key="test",
        base_url="http://test/v1",
        http_client=DefaultAsyncHttpxClient(transport=httpx2.MockTransport(handler)),
        responses_api=True,
        memoize=False,
        # skips the reasoning-summary probe request
        config=GenerateConfig(reasoning_summary="none"),
    )


@pytest.mark.parametrize("status_code", [404, 405])
@pytest.mark.parametrize("submit", [True, False], ids=["react", "react_no_submit"])
def test_overflow_recovery_with_local_counting_resends_at_most_once(
    status_code: int, submit: bool
) -> None:
    """Forced compaction that cannot shrink the input is retried only once.

    Without the native token-count endpoint, OpenAI counts with a local
    tokenizer that skips encrypted reasoning, so an input that overflowed can
    count well under the threshold. The edit keeps the only reasoning and tool
    use, so the retry sends the same input and overflows again. The agent then
    ends instead of compacting and resending it indefinitely.
    """
    agent_requests: list[dict[str, Any]] = []
    model = _openai_with_local_counting(
        status_code, ["lookup", "overflow", "overflow"], agent_requests
    )

    task = Task(
        dataset=[Sample(input="Solve this using the tool.", target="done")],
        solver=react(
            tools=[lookup()],
            submit=submit,
            compaction=CompactionEdit(threshold=1_000, memory=False),
        ),
    )

    log = eval(task, model=model)[0]
    assert log.status == "success", log.error
    assert len(agent_requests) == 3
    assert agent_requests[2]["input"] == agent_requests[1]["input"]


@pytest.mark.parametrize("status_code", [404, 405])
@pytest.mark.parametrize("submit", [True, False], ids=["react", "react_no_submit"])
@pytest.mark.parametrize(
    "strategy",
    [
        # drops the older reasoning, keeps both tool uses
        pytest.param(CompactionEdit(threshold=10_000, memory=False), id="edit"),
        pytest.param(CompactionSummary(threshold=10_000, memory=False), id="summary"),
        # native compaction is unavailable, so this falls back to summary
        pytest.param(CompactionAuto(threshold=10_000, memory=False), id="auto"),
    ],
)
def test_overflow_recovery_with_local_counting_removes_reasoning(
    status_code: int, submit: bool, strategy: CompactionStrategy
) -> None:
    """Forced compaction that removes encrypted reasoning recovers.

    The local tokenizer skips the reasoning, so the count does not fall (the
    edit leaves it unchanged, the summary raises it), but the retry no longer
    sends that reasoning.
    """
    agent_requests: list[dict[str, Any]] = []
    model = _openai_with_local_counting(
        status_code, ["lookup", "lookup", "overflow", "final"], agent_requests
    )

    task = Task(
        dataset=[Sample(input="Solve this using the tool.", target="done")],
        solver=react(tools=[lookup()], submit=submit, compaction=strategy),
    )

    log = eval(task, model=model)[0]
    assert log.status == "success", log.error
    assert log.samples
    assert len(agent_requests) == 4
    assert "ENCRYPTED-1" in json.dumps(agent_requests[2]["input"])
    assert "ENCRYPTED-1" not in json.dumps(agent_requests[3]["input"])
    assert "done" in (log.samples[0].output.completion or "")
