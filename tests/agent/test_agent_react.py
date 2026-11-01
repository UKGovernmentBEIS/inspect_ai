import re
from dataclasses import dataclass
from typing import Any, Callable, Literal, Sequence

import anyio
import pytest

from inspect_ai import Task, eval
from inspect_ai._util.content import ContentReasoning, ContentText
from inspect_ai.agent._agent import Agent, AgentState, agent
from inspect_ai.agent._channel import (
    AgentChannel,
    Cancel,
    UserMessage,
    current_agent_channel,
)
from inspect_ai.agent._channel.gate import turn_gate
from inspect_ai.agent._deepagent.deepagent import deepagent
from inspect_ai.agent._filter import MessageFilter
from inspect_ai.agent._handoff import handoff
from inspect_ai.agent._react import react
from inspect_ai.agent._types import (
    DEFAULT_CONTINUE_PROMPT,
    AgentAttempts,
    AgentPrompt,
    AgentSubmit,
)
from inspect_ai.dataset import Sample
from inspect_ai.event import CompactionEvent, ModelEvent
from inspect_ai.log import EvalLog, read_eval_log
from inspect_ai.model import (
    ChatMessageUser,
    GenerateConfig,
    Model,
    ModelOutput,
    ModelUsage,
    get_model,
)
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageTool,
)
from inspect_ai.model._compaction._compaction import compaction
from inspect_ai.model._compaction.auto import CompactionAuto
from inspect_ai.model._compaction.native import CompactionNative
from inspect_ai.model._compaction.trim import CompactionTrim
from inspect_ai.scorer import Score, Target, accuracy, includes, scorer
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.tool import Tool, ToolCall, tool
from inspect_ai.tool._tool_def import ToolDef
from inspect_ai.tool._tool_info import ToolInfo


@tool
def addition():
    async def execute(x: int, y: int):
        """
        Add two numbers.

        Args:
            x (int): First number to add.
            y (int): Second number to add.

        Returns:
            The sum of the two numbers.
        """
        return x + y

    return execute


@agent
def searcher() -> Agent:
    async def execute(state: AgentState, max_searches: int = 5) -> AgentState:
        """Searcher that computes max searches.

        Args:
            state: Input state (conversation)
            max_searches: Maximum number of web searches to conduct

        Returns:
            Ouput state (additions to conversation)
        """
        state.messages.append(
            ChatMessageUser(content=f"The maximum searches is {max_searches}")
        )

        return state

    return execute


AGENT_SYSTEM_MESSAGE = """
You are a helpful assistant attempting to submit the correct answer. When you have completed the task and have a result, call the {submit} function to communicate it.
"""


AGENT_INCORRECT_MESSAGE = "Your submission was incorrect."

AGENT_CONTINUE_MESSAGE = "Please proceed."

AGENT_SUBMIT_TOOL_NAME = "agent_submit"
AGENT_SUBMIT_TOOL_DESCRIPTION = "Submit an answer."


def run_react_agent(
    *,
    prompt: str | AgentPrompt | None = AgentPrompt(),
    submit: AgentSubmit = AgentSubmit(
        name=AGENT_SUBMIT_TOOL_NAME, description=AGENT_SUBMIT_TOOL_DESCRIPTION
    ),
    tools: list[Tool],
    message_limit: int | None = 30,
) -> EvalLog:
    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target=["2", "2.0", "Two"])],
        solver=react(
            prompt=prompt,
            tools=tools,
            submit=submit,
        ),
        scorer=includes(),
        message_limit=message_limit,
    )
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name=submit.name
                or (
                    submit.tool.name
                    if isinstance(submit.tool, ToolDef)
                    else ToolDef(submit.tool).name
                    if submit.tool
                    else AGENT_SUBMIT_TOOL_NAME
                ),
                tool_arguments={"answer": "2"},
            )
        ],
    )

    return eval(task, model=model)[0]


def mockllm_model_with_submissions(answers: list[str]):
    return get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="submit",
                tool_arguments={"answer": answer},
            )
            for answer in answers
        ],
    )


def mockllm_model_with_outputs(outputs: list[str]):
    return get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.from_content(model="mockllm/model", content=output)
            for output in outputs
        ],
    )


def test_react_agent_custom_prompt() -> None:
    def has_system_message(
        messages: list[ChatMessage], match: str | list[str] | None = None
    ) -> bool:
        message = next(
            (message for message in messages if isinstance(message, ChatMessageSystem)),
            None,
        )
        if message:
            if match:
                match = [match] if isinstance(match, str) else match
                for m in match:
                    if m not in message.text:
                        return False
                return True
            else:
                return True
        else:
            return False

    def check_react_agent(
        prompt: str | AgentPrompt | None,
        *,
        tools: list[Tool] = [addition()],
        system_match: str | list[str] | None = None,
    ) -> None:
        log = run_react_agent(prompt=prompt, tools=tools)
        assert log.samples
        messages = log.samples[0].messages
        if system_match:
            assert has_system_message(messages, system_match)
        else:
            assert not has_system_message(messages)

    # no prompt at all
    check_react_agent(None)

    # custom instructions
    check_react_agent(
        AgentPrompt("You are a ninja"),
        system_match=["ninja", "best possible answer"],
    )

    # custom assistant prompt
    check_react_agent(
        AgentPrompt(assistant_prompt="Try to do your best"),
        system_match=["do your best"],
    )

    # custom handoff prompt
    check_react_agent(
        AgentPrompt(handoff_prompt="Make the handoff right!"),
        tools=[handoff(searcher())],
        system_match=["best possible answer", "handoff right!"],
    )


def test_react_default_prompt_encourages_parallel_tools() -> None:
    # the default assistant prompt should encourage parallel tool calls and no
    # longer carry the old sequential "send more messages" framing.
    from inspect_ai.agent._types import PARALLEL_TOOLS_PROMPT

    log = run_react_agent(tools=[addition()])
    assert log.samples
    system_msg = next(
        m for m in log.samples[0].messages if isinstance(m, ChatMessageSystem)
    )
    assert PARALLEL_TOOLS_PROMPT in system_msg.text
    assert "send more messages with additional tool calls" not in system_msg.text


def test_react_agent_custom_submit() -> None:
    log = run_react_agent(
        prompt=AgentPrompt(assistant_prompt=AGENT_SYSTEM_MESSAGE), tools=[addition()]
    )
    check_custom_submit(log, AGENT_SUBMIT_TOOL_NAME, AGENT_SUBMIT_TOOL_DESCRIPTION)


def test_react_agent_custom_submit_tool() -> None:
    @tool
    def custom_submit():
        async def execute(answer: str) -> str:
            """The tool used to submit.

            Args:
                answer: The submitted answer.
            """
            return answer

        return execute

    # custom tool only
    log = run_react_agent(
        prompt=AgentPrompt(assistant_prompt=AGENT_SYSTEM_MESSAGE),
        submit=AgentSubmit(tool=custom_submit()),
        tools=[addition()],
    )
    check_custom_submit(log, "custom_submit", "The tool used to submit.")

    # custom tool with overridden name and description
    log = run_react_agent(
        prompt=AgentPrompt(assistant_prompt=AGENT_SYSTEM_MESSAGE),
        submit=AgentSubmit(
            tool=custom_submit(), name="submit_it", description="tool to submit it"
        ),
        tools=[addition()],
    )
    check_custom_submit(log, "submit_it", "tool to submit it")


def check_custom_submit(log: EvalLog, name: str, description: str) -> None:
    assert log.status == "success"
    assert log.samples
    model_event = next(
        (event for event in log.samples[0].events if event.event == "model")
    )
    assert model_event
    assert model_event.tools[1].name == name
    assert model_event.tools[1].description == description


def addition_dataset() -> list[Sample]:
    return [Sample(input="What is 1 + 1?", target=["2", "2.0", "Two"])]


def test_react_agent_long_submission_not_truncated() -> None:
    """A submitted answer larger than max_tool_output reaches the completion intact.

    The submit result is the scored answer, not model-facing tool output, so
    clipping it would score a truncation notice in place of what the model
    actually wrote.
    """
    answer = "A" * 2000
    log = eval(
        Task(
            dataset=addition_dataset(),
            solver=react(),
            config=GenerateConfig(max_tool_output=100),
        ),
        model=mockllm_model_with_submissions([answer]),
    )[0]
    assert log.status == "success"
    assert log.samples
    # answer_only is False by default, so the answer is appended to the
    # content the model generated alongside the submit call
    assert log.samples[0].output.completion.endswith(answer)


@tool
def custom_submit_tool():
    async def execute(answer: str) -> str:
        """The tool used to submit.

        Args:
            answer: The submitted answer.
        """
        return answer

    return execute


def _run_custom_submit(answer: str, submit_tool: ToolDef) -> EvalLog:
    return eval(
        Task(
            dataset=addition_dataset(),
            solver=react(submit=AgentSubmit(tool=submit_tool)),
            config=GenerateConfig(max_tool_output=100),
        ),
        model=mockllm_model_with_submissions([answer]),
    )[0]


def test_react_agent_custom_submit_tool_long_submission_not_truncated() -> None:
    """The exemption is defaulted onto a caller-supplied submit ToolDef too."""
    answer = "B" * 2000
    log = _run_custom_submit(answer, ToolDef(custom_submit_tool(), name="submit"))
    assert log.status == "success"
    assert log.samples
    assert log.samples[0].output.completion.endswith(answer)


def test_react_agent_custom_submit_tool_explicit_max_output_respected() -> None:
    """React defaults the submit exemption but never overrides an explicit one.

    Truncating a submission is normally a bug (the notice gets scored in place
    of the answer), but a caller who asks for a cap on their own submit tool
    gets it.
    """
    answer = "C" * 2000
    log = _run_custom_submit(
        answer, ToolDef(custom_submit_tool(), name="submit", max_output=500)
    )
    assert log.status == "success"
    assert log.samples
    completion = log.samples[0].output.completion
    assert answer not in completion
    assert len(completion) < len(answer)


def test_react_agent_no_submit() -> None:
    def addition_task() -> Task:
        return Task(
            dataset=addition_dataset(),
            solver=react(tools=[addition()], submit=False),
            scorer=includes(),
        )

    log = eval(
        addition_task(),
        model=get_model(
            "mockllm/model",
            custom_outputs=[
                ModelOutput.for_tool_call(
                    "mockllm/model", "addition", {"x": 1, "y": 1}
                ),
                ModelOutput.from_content("mockllm/model", content="2"),
            ],
        ),
    )[0]
    assert log.results
    assert log.results.scores[0].metrics["accuracy"].value == 1


def test_react_agent_retries() -> None:
    def addition_task(max_attempts: int) -> Task:
        return Task(
            dataset=addition_dataset(),
            solver=react(tools=[addition()], attempts=max_attempts),
            scorer=includes(),
            message_limit=30,
        )

    # incorrect answer with no retries
    log = eval(addition_task(1), mockllm_model_with_submissions(["5"]))[0]
    assert log.results
    assert log.results.scores[0].metrics["accuracy"].value == 0

    # correct answer on the third try
    log = eval(addition_task(3), mockllm_model_with_submissions(["5", "4", "2"]))[0]
    assert log.results
    assert log.samples
    assert log.results.scores[0].metrics["accuracy"].value == 1
    model_events = sum(
        1 for event in log.samples[0].transcript.events if event.event == "model"
    )
    assert model_events == 3


def test_react_agent_retries_with_custom_incorrect_message():
    async def async_custom_incorrect_message(state: AgentState, scores: list[Score]):
        return f"Your response to the input was incorrect: {scores[0].explanation}"

    def check_task(incorrect_message):
        addition_task = Task(
            dataset=[Sample(input="What is 1 + 1?", target="2")],
            solver=react(
                tools=[addition()],
                attempts=AgentAttempts(
                    attempts=3,
                    incorrect_message=incorrect_message,
                ),
            ),
            scorer=compare_quantities(),
            message_limit=30,
        )
        log = eval(addition_task, mockllm_model_with_submissions(["5", "1", "2"]))[0]
        assert log.results.scores[0].metrics["accuracy"].value == 1
        user_msgs = [
            m.content for m in log.samples[0].messages if isinstance(m, ChatMessageUser)
        ]
        assert user_msgs == [
            "What is 1 + 1?",
            "Your response to the input was incorrect: Answer is too high",
            "Your response to the input was incorrect: Answer is too low",
        ]

    check_task(async_custom_incorrect_message)


def test_react_agent_on_continue_str():
    # should always return on the on_continue str
    on_continue = "Please keep going!"
    addition_task = Task(
        dataset=[Sample(input="What is 1 + 1?", target="2")],
        solver=react(tools=[addition()], on_continue=on_continue),
        scorer=compare_quantities(),
    )
    log = eval(
        addition_task,
        model=get_model(
            "mockllm/model",
            custom_outputs=[
                ModelOutput.for_tool_call(
                    "mockllm/model", "addition", {"x": 1, "y": 1}
                ),
                ModelOutput.from_content("mockllm/model", "I give up!"),
                ModelOutput.for_tool_call("mockllm/model", "submit", {"answer": "2"}),
            ],
        ),
    )[0]
    assert log.status == "success"
    assert log.samples
    messages = log.samples[0].messages
    assert len(messages) == 7
    assert messages[-2].text == on_continue


def test_react_agent_on_continue_null():
    # should return default str if there are no tool calls
    addition_task = Task(
        dataset=[Sample(input="What is 1 + 1?", target="2")],
        solver=react(tools=[addition()]),
        scorer=compare_quantities(),
    )
    log = eval(
        addition_task,
        model=get_model(
            "mockllm/model",
            custom_outputs=[
                ModelOutput.for_tool_call(
                    "mockllm/model", "addition", {"x": 1, "y": 1}
                ),
                ModelOutput.from_content("mockllm/model", "I give up!"),
                ModelOutput.for_tool_call("mockllm/model", "submit", {"answer": "2"}),
            ],
        ),
    )[0]
    assert log.status == "success"
    assert log.samples
    messages = log.samples[0].messages
    assert len(messages) == 7  # on continue should only appear once
    assert messages[-2].text == DEFAULT_CONTINUE_PROMPT.format(submit="submit")


def test_react_agent_on_continue_str_with_braces():
    # an on_continue string containing literal braces (e.g. a JSON example)
    # must be passed through verbatim — only the documented {submit}
    # placeholder is substituted, other braces are not str.format() fields.
    on_continue = 'Call a tool, e.g. {"name": "{submit}", "answer": "..."}'
    addition_task = Task(
        dataset=[Sample(input="What is 1 + 1?", target="2")],
        solver=react(tools=[addition()], on_continue=on_continue),
        scorer=compare_quantities(),
    )
    log = eval(
        addition_task,
        model=get_model(
            "mockllm/model",
            custom_outputs=[
                ModelOutput.from_content("mockllm/model", "I think it is 2."),
                ModelOutput.for_tool_call("mockllm/model", "submit", {"answer": "2"}),
            ],
        ),
    )[0]
    assert log.status == "success"
    assert log.samples
    assert log.samples[0].error is None
    messages = log.samples[0].messages
    assert messages[-2].text == 'Call a tool, e.g. {"name": "submit", "answer": "..."}'


def test_react_agent_on_continue_func_with_braces():
    # an on_continue callable may echo model output back to the model; literal
    # braces in that output (model-controlled) must not be treated as
    # str.format() fields and crash the agent.
    async def on_continue(state: AgentState) -> bool | str:
        if not state.output.message.tool_calls:
            return f'You said "{state.output.completion}". Please call {{submit}}.'
        return True

    addition_task = Task(
        dataset=[Sample(input="What is 1 + 1?", target="2")],
        solver=react(tools=[addition()], on_continue=on_continue),
        scorer=compare_quantities(),
    )
    log = eval(
        addition_task,
        model=get_model(
            "mockllm/model",
            custom_outputs=[
                ModelOutput.from_content("mockllm/model", "I refuse. {pwned}"),
                ModelOutput.for_tool_call("mockllm/model", "submit", {"answer": "2"}),
            ],
        ),
    )[0]
    assert log.status == "success"
    assert log.samples
    assert log.samples[0].error is None
    messages = log.samples[0].messages
    assert messages[-2].text == 'You said "I refuse. {pwned}". Please call submit.'


def test_react_agent_on_continue_edit_keeps_logged_input(tmp_path):
    # an on_continue that rewrites an earlier tool result in place must not
    # change what the earlier generation's logged input shows
    async def on_continue(state: AgentState) -> bool:
        tool_messages = [m for m in state.messages if isinstance(m, ChatMessageTool)]
        if len(tool_messages) == 2:
            tool_messages[0].content = "[elided]"
        return True

    addition_task = Task(
        dataset=[Sample(input="What is 1 + 1?", target="2")],
        solver=react(tools=[addition()], on_continue=on_continue),
        scorer=compare_quantities(),
    )
    log = eval(
        addition_task,
        model=get_model(
            "mockllm/model",
            custom_outputs=[
                ModelOutput.for_tool_call(
                    "mockllm/model", "addition", {"x": 1, "y": 1}
                ),
                ModelOutput.for_tool_call(
                    "mockllm/model", "addition", {"x": 2, "y": 2}
                ),
                ModelOutput.for_tool_call("mockllm/model", "submit", {"answer": "2"}),
            ],
        ),
        log_dir=str(tmp_path),
    )[0]
    assert log.status == "success"

    sample = read_eval_log(log.location).samples[0]
    model_events = [e for e in sample.events if isinstance(e, ModelEvent)]
    first_tool_results = [
        next(m for m in e.input if isinstance(m, ChatMessageTool))
        for e in model_events[1:]
    ]
    assert [m.text for m in first_tool_results] == ["2", "[elided]"]


def test_react_agent_assistant_prompt_with_braces():
    # a user-supplied assistant_prompt / submit_prompt may legitimately contain
    # literal braces (e.g. a JSON output schema). Only the documented {submit}
    # placeholder is substituted; other braces must be left intact and must
    # not raise via str.format().
    assistant_prompt = 'You are helpful. Output {"json": true}. Use {submit} to finish.'
    log = run_react_agent(
        prompt=AgentPrompt(assistant_prompt=assistant_prompt),
        tools=[addition()],
    )
    assert log.status == "success"
    assert log.samples
    assert log.samples[0].error is None
    system_msg = next(
        m for m in log.samples[0].messages if isinstance(m, ChatMessageSystem)
    )
    assert '{"json": true}' in system_msg.text
    assert f"Use {AGENT_SUBMIT_TOOL_NAME} to finish." in system_msg.text

    # also exercise the branch where assistant_prompt has no {submit} so the
    # separate submit_prompt (with braces of its own) is appended
    log = run_react_agent(
        prompt=AgentPrompt(
            assistant_prompt='Respond with {"done": false} until ready.',
            submit_prompt='When ready call {submit}() with {"done": true}.',
        ),
        tools=[addition()],
    )
    assert log.status == "success"
    assert log.samples
    assert log.samples[0].error is None
    system_msg = next(
        m for m in log.samples[0].messages if isinstance(m, ChatMessageSystem)
    )
    assert '{"done": false}' in system_msg.text
    assert f'call {AGENT_SUBMIT_TOOL_NAME}() with {{"done": true}}.' in system_msg.text


def test_react_agent_on_continue_func():
    async def on_continue(state: AgentState) -> bool | str:
        if state.output.completion == "5":
            return "You should definitely continue!"
        elif state.output.completion == "1":
            return False
        else:
            return True

    addition_task = Task(
        dataset=[Sample(input="What is 1 + 1?", target="2")],
        solver=react(tools=[addition()], attempts=3, on_continue=on_continue),
        scorer=compare_quantities(),
        message_limit=30,
    )
    log = eval(addition_task, mockllm_model_with_outputs(["5", "1", "2"]))[0]
    assert log.status == "success"
    assert log.samples
    messages = log.samples[0].messages
    assert (
        next((m for m in messages if m.text == "You should definitely continue!"), None)
        is not None
    )
    assert messages[-1].text == "1"


def test_react_agent_concatenates():
    @solver
    def validate_answer() -> Solver:
        async def execute(state: TaskState, generate: Generate) -> TaskState:
            if state.output.completion == "2":
                raise RuntimeError("Submitted answer not properly concatenated")
            return state

        return execute

    addition_task = Task(
        dataset=[Sample(input="What is 1 + 1?", target=["2", "2.0", "Two"])],
        solver=[react(tools=[addition()], attempts=3), validate_answer()],
        scorer=includes(),
        message_limit=30,
    )

    log = eval(addition_task, mockllm_model_with_submissions(["2"]))[0]
    assert log.results
    assert log.results.scores[0].metrics["accuracy"].value == 1.0


@scorer(metrics=[accuracy()])
def compare_quantities():
    async def score(state: TaskState, target: Target) -> Score:
        match = re.search(r".*?(\d+)$", state.output.completion)
        assert match
        answer = float(match.group(1))

        target_value = float(target.text)
        if answer == target_value:
            return Score(value=1.0, answer=state.output.completion)
        elif answer > target_value:
            return Score(
                value=0.0,
                answer=state.output.completion,
                explanation="Answer is too high",
            )
        else:
            return Score(
                value=0.0,
                answer=state.output.completion,
                explanation="Answer is too low",
            )

    return score


def test_remove_submit_tool_filters_reasoning_content():
    """Test that _remove_submit_tool removes both submit tool calls and reasoning content."""
    from inspect_ai.agent._react import _remove_submit_tool

    # Create a tool call for submit
    submit_tool_call = ToolCall(
        id="call_123",
        function="submit",
        arguments={"answer": "42"},
    )

    # Create a tool call for a regular tool
    regular_tool_call = ToolCall(
        id="call_456",
        function="addition",
        arguments={"x": 1, "y": 2},
    )

    # Create an assistant message with both reasoning content and tool calls
    message_with_reasoning = ChatMessageAssistant(
        content=[
            ContentReasoning(reasoning="I need to think about this problem..."),
            ContentText(text="Let me solve this step by step."),
        ],
        tool_calls=[regular_tool_call, submit_tool_call],
    )

    # Create an assistant message without reasoning content but with submit tool call
    message_without_reasoning = ChatMessageAssistant(
        content="Just a regular message",
        tool_calls=[submit_tool_call],
    )

    # Create an assistant message with only regular tool calls (should be unchanged)
    message_regular_only = ChatMessageAssistant(
        content=[
            ContentReasoning(reasoning="This reasoning should stay"),
            ContentText(text="Regular message"),
        ],
        tool_calls=[regular_tool_call],
    )

    messages = [
        message_with_reasoning,
        message_without_reasoning,
        message_regular_only,
    ]

    # Filter out submit tool calls
    filtered_messages = _remove_submit_tool(messages, "submit")

    # Verify we still have all messages
    assert len(filtered_messages) == 3

    # Check first message: reasoning content should be removed, submit tool call removed
    first_filtered = filtered_messages[0]
    assert isinstance(first_filtered, ChatMessageAssistant)
    assert len(first_filtered.tool_calls) == 1  # Only regular tool call should remain
    assert first_filtered.tool_calls[0].function == "addition"

    # Reasoning content should be filtered out
    assert isinstance(first_filtered.content, list)
    reasoning_content = [
        c for c in first_filtered.content if isinstance(c, ContentReasoning)
    ]
    assert len(reasoning_content) == 0, (
        "Reasoning content should be removed when submit tool call is filtered"
    )

    # Text content should remain
    text_content = [c for c in first_filtered.content if isinstance(c, ContentText)]
    assert len(text_content) == 1
    assert text_content[0].text == "Let me solve this step by step."

    # Check second message: submit tool call should be removed, content unchanged (no reasoning)
    second_filtered = filtered_messages[1]
    assert isinstance(second_filtered, ChatMessageAssistant)
    assert second_filtered.tool_calls == []  # Submit tool call removed
    assert (
        second_filtered.content == "Just a regular message"
    )  # String content unchanged

    # Check third message: should be completely unchanged (no submit tool calls)
    third_filtered = filtered_messages[2]
    assert isinstance(third_filtered, ChatMessageAssistant)
    assert len(third_filtered.tool_calls) == 1
    assert third_filtered.tool_calls[0].function == "addition"

    # Reasoning content should NOT be filtered out (no submit tool call was removed)
    assert isinstance(third_filtered.content, list)
    reasoning_content = [
        c for c in third_filtered.content if isinstance(c, ContentReasoning)
    ]
    assert len(reasoning_content) == 1, (
        "Reasoning content should remain when no submit tool call is filtered"
    )
    assert reasoning_content[0].reasoning == "This reasoning should stay"


@pytest.mark.parametrize(
    ("truncation", "expected_message_count", "expected_submit"),
    [
        pytest.param(
            "auto", 142, True, id="with_auto_truncation"
        ),  # sys msg + 0.7 * 200
        pytest.param(
            "disabled", 201, False, id="with_disabled_truncation"
        ),  # no submit (agent terminates)
    ],
)
def test_react_agent_truncation(
    truncation: Literal["auto", "disabled"] | MessageFilter,
    expected_message_count: int,
    expected_submit: bool,
):
    """Test the react agent with different truncation settings"""
    task = Task(
        dataset=[Sample(input="What is the capital of Denmark?", target="Copenhagen")],
        solver=react(truncation=truncation),
        scorer=includes(),
    )

    model = get_model(
        "mockllm/model",
        custom_outputs=[
            *(
                [
                    ModelOutput.from_content(
                        model="mockllm/model",
                        content="This is a repeated message",
                    )
                ]
                * 99
            ),
            ModelOutput.from_content(
                model="mockllm/model",
                content="Final message with stop_reason=model_length",
                stop_reason="model_length",
            ),
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="submit",
                tool_arguments={"answer": "Copenhagen"},
            ),
        ],
    )

    log = eval(task, model=model)[0]
    assert log.results

    assert log.samples and (sample := log.samples[0])
    assert len(sample.messages) == expected_message_count
    last_message = sample.messages[-1]
    assert (
        last_message.content == "tool call for tool submit\n\nCopenhagen"
    ) == expected_submit

    assert sample.scores and len(sample.scores) == 1
    assert (score := sample.scores["includes"])
    assert score.value == "C" if expected_submit else "I"


def test_react_agent_retry_refusals_disabled() -> None:
    """Test that without retry_refusals, 3 consecutive content_filter responses break the loop.

    Without retry_refusals, content_filter responses pass through directly.
    The agent loop allows up to 3 consecutive content_filter responses before
    breaking to avoid an infinite loop while giving the model a chance to recover.
    """
    task = Task(
        dataset=addition_dataset(),
        solver=react(tools=[addition()]),
        scorer=includes(),
        message_limit=30,
    )

    model = get_model(
        "mockllm/model",
        custom_outputs=[
            # 3 consecutive refusals trigger the break
            ModelOutput.from_content(
                model="mockllm/model",
                content="I cannot help with that.",
                stop_reason="content_filter",
            ),
            ModelOutput.from_content(
                model="mockllm/model",
                content="I still cannot help.",
                stop_reason="content_filter",
            ),
            ModelOutput.from_content(
                model="mockllm/model",
                content="I really cannot help.",
                stop_reason="content_filter",
            ),
            # This output won't be reached
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="submit",
                tool_arguments={"answer": "2"},
            ),
        ],
    )

    log = eval(task, model=model)[0]
    assert log.status == "success"
    assert log.samples
    # Loop breaks after 3 consecutive content_filter responses
    model_events = sum(
        1 for event in log.samples[0].transcript.events if event.event == "model"
    )
    assert model_events == 3
    assert log.results
    assert log.results.scores[0].metrics["accuracy"].value == 0


def test_react_agent_retry_refusals_success() -> None:
    """Test that with retry_refusals, refusals are retried within a single generation.

    With retry_refusals=2, up to 2 retry attempts are made within a single
    _model_generate call. The key difference from no retry_refusals is that
    the refusal message is NOT added to the conversation - only the successful
    response is added.
    """
    task = Task(
        dataset=addition_dataset(),
        solver=react(tools=[addition()], retry_refusals=2),
        scorer=includes(),
    )

    model = get_model(
        "mockllm/model",
        custom_outputs=[
            # First attempt within _model_generate: refusal (triggers retry)
            ModelOutput.from_content(
                model="mockllm/model",
                content="I cannot help with that.",
                stop_reason="content_filter",
            ),
            # Second attempt within _model_generate: success
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="submit",
                tool_arguments={"answer": "2"},
            ),
        ],
    )

    log = eval(task, model=model)[0]
    assert log.status == "success"
    assert log.results
    assert log.results.scores[0].metrics["accuracy"].value == 1
    # With retry_refusals, only the successful response is added to messages
    # (the refusal is discarded). So we should see only 1 assistant message.
    assert log.samples
    assistant_messages = [
        m for m in log.samples[0].messages if isinstance(m, ChatMessageAssistant)
    ]
    assert len(assistant_messages) == 1
    # The refusal content should NOT be in any message
    assert not any("cannot help" in m.text for m in assistant_messages)


def test_react_agent_retry_refusals_exhausted() -> None:
    """Test that when retries are exhausted and consecutive threshold hit, loop breaks.

    With retry_refusals=2, each _model_generate call consumes up to 3 outputs
    (initial + 2 retries). The outer loop allows 3 consecutive content_filter
    results before breaking. So we need 3 × 3 = 9 refusal outputs total.
    """
    task = Task(
        dataset=addition_dataset(),
        solver=react(tools=[addition()], retry_refusals=2),
        scorer=includes(),
        message_limit=30,
    )

    model = get_model(
        "mockllm/model",
        custom_outputs=[
            # 3 outer loop iterations × 3 refusals each (initial + 2 retries)
            *(
                ModelOutput.from_content(
                    model="mockllm/model",
                    content=f"I cannot help ({i}).",
                    stop_reason="content_filter",
                )
                for i in range(9)
            ),
        ],
    )

    log = eval(task, model=model)[0]
    assert log.status == "success"
    assert log.samples
    assert log.results
    assert log.results.scores[0].metrics["accuracy"].value == 0


def test_react_agent_retry_refusals_no_submit() -> None:
    """Test retry_refusals with submit=False."""
    task = Task(
        dataset=addition_dataset(),
        solver=react(tools=[addition()], submit=False, retry_refusals=1),
        scorer=includes(),
    )

    model = get_model(
        "mockllm/model",
        custom_outputs=[
            # First attempt: refusal (triggers retry)
            ModelOutput.from_content(
                model="mockllm/model",
                content="I cannot help.",
                stop_reason="content_filter",
            ),
            # Second attempt: success with tool call
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="addition",
                tool_arguments={"x": 1, "y": 1},
            ),
            # Final response
            ModelOutput.from_content(model="mockllm/model", content="2"),
        ],
    )

    log = eval(task, model=model)[0]
    assert log.status == "success"
    assert log.results
    assert log.results.scores[0].metrics["accuracy"].value == 1


def test_react_agent_retry_refusals_recovery() -> None:
    """Test that a transient refusal doesn't break the loop.

    The model refuses once then succeeds on the next attempt, verifying
    that the consecutive content_filter counter resets on success.
    """
    task = Task(
        dataset=addition_dataset(),
        solver=react(tools=[addition()]),
        scorer=includes(),
        message_limit=30,
    )

    model = get_model(
        "mockllm/model",
        custom_outputs=[
            # First generation: refusal (consecutive_content_filter = 1)
            ModelOutput.from_content(
                model="mockllm/model",
                content="I cannot help with that.",
                stop_reason="content_filter",
            ),
            # Second generation: success with tool call (counter resets to 0)
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="submit",
                tool_arguments={"answer": "2"},
            ),
        ],
    )

    log = eval(task, model=model)[0]
    assert log.status == "success"
    assert log.results
    assert log.results.scores[0].metrics["accuracy"].value == 1


def _refusal(i: int = 0) -> ModelOutput:
    return ModelOutput.from_content(
        model="mockllm/model",
        content=f"I cannot help ({i}).",
        stop_reason="content_filter",
    )


def _submit_two() -> ModelOutput:
    return ModelOutput.for_tool_call(
        model="mockllm/model",
        tool_name="submit",
        tool_arguments={"answer": "2"},
    )


def _model_event_count(log: EvalLog) -> int:
    assert log.samples
    return sum(1 for event in log.samples[0].events if event.event == "model")


def test_react_agent_fail_on_refusal_after_retries() -> None:
    """With fail_on_refusal, retry_refusals=N still applies: N+1 refusals fail the sample."""
    task = Task(
        dataset=addition_dataset(),
        solver=react(tools=[addition()], retry_refusals=2),
        scorer=includes(),
    )
    model = get_model(
        "mockllm/model",
        custom_outputs=[_refusal(0), _refusal(1), _refusal(2), _submit_two()],
    )

    log = eval(task, model=model, fail_on_refusal=True, fail_on_error=False)[0]
    assert log.samples
    error = log.samples[0].error
    assert error is not None
    assert "Model refusal (mockllm/model): I cannot help (2)." in error.message
    # initial attempt + 2 retries, then the sample failed
    assert _model_event_count(log) == 3


def test_react_agent_fail_on_refusal_retry_recovers() -> None:
    """Refusals within the retry budget don't fail the sample."""
    task = Task(
        dataset=addition_dataset(),
        solver=react(tools=[addition()], retry_refusals=2),
        scorer=includes(),
    )
    model = get_model(
        "mockllm/model",
        custom_outputs=[_refusal(0), _refusal(1), _submit_two()],
    )

    log = eval(task, model=model, fail_on_refusal=True)[0]
    assert log.status == "success"
    assert log.results
    assert log.results.scores[0].metrics["accuracy"].value == 1
    assert log.samples
    assert log.samples[0].error is None


def test_react_agent_fail_on_refusal_no_retries() -> None:
    """Without retry_refusals a single refusal fails the sample."""
    task = Task(
        dataset=addition_dataset(),
        solver=react(tools=[addition()]),
        scorer=includes(),
    )
    model = get_model("mockllm/model", custom_outputs=[_refusal(), _submit_two()])

    log = eval(task, model=model, fail_on_refusal=True, fail_on_error=False)[0]
    assert log.samples
    assert log.samples[0].error is not None
    assert _model_event_count(log) == 1


def test_react_agent_fail_on_refusal_no_submit() -> None:
    """The react_no_submit() loop gets the same retry-then-fail behaviour."""
    task = Task(
        dataset=addition_dataset(),
        solver=react(tools=[addition()], submit=False, retry_refusals=1),
        scorer=includes(),
    )
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            _refusal(0),
            _refusal(1),
            ModelOutput.from_content(model="mockllm/model", content="2"),
        ],
    )

    log = eval(task, model=model, fail_on_refusal=True, fail_on_error=False)[0]
    assert log.samples
    assert log.samples[0].error is not None
    assert _model_event_count(log) == 2


# ---------------------------------------------------------------------------
# Turn gate
# ---------------------------------------------------------------------------


@dataclass
class _GateCall:
    texts: list[str]
    last_role: str
    has_assistant: bool
    state_matches: bool
    interrupted: bool
    redirected: bool


# rewrite hook: (boundary index, messages) -> whether it rewrote them
_GateRewrite = Callable[[int, list[ChatMessage]], bool]


class _TestGate:
    """Turn gate that records the boundaries of the first loop it sees."""

    def __init__(self, rewrite: _GateRewrite | None = None) -> None:
        self.rewrite = rewrite
        self.channel: AgentChannel | None = None
        self.calls: list[_GateCall] = []
        self.interrupted: anyio.Event | None = None
        self.redirected = False

    async def before_turn(
        self,
        channel: AgentChannel,
        messages: Sequence[ChatMessage],
        state: AgentState | None,
    ) -> bool:
        if self.channel is None:
            self.channel = channel
            channel.subscribe_turn_state(self._on_turn_state)
        if channel is not self.channel:
            return False
        assert isinstance(messages, list)
        self.calls.append(
            _GateCall(
                texts=[m.text for m in messages],
                last_role=messages[-1].role,
                has_assistant=any(m.role == "assistant" for m in messages),
                state_matches=state is not None and state.messages is messages,
                interrupted=self.interrupted is not None and self.interrupted.is_set(),
                redirected=self.redirected,
            )
        )
        return self.rewrite(len(self.calls) - 1, messages) if self.rewrite else False

    def closed(self, channel: AgentChannel) -> None:
        pass

    def _on_turn_state(self, turn_state: str) -> None:
        if turn_state == "cancelled" and self.interrupted is not None:
            self.interrupted.set()


@agent
def _gated(gate: _TestGate, inner: Agent) -> Agent:
    async def execute(state: AgentState) -> AgentState:
        with turn_gate(gate):
            return await inner(state)

    return execute


@agent
def _gated_with_redirect(gate: _TestGate, inner: Agent) -> Agent:
    """Post an operator redirect once the loop's turn is interrupted."""

    async def execute(state: AgentState) -> AgentState:
        interrupted = anyio.Event()
        gate.interrupted = interrupted

        async def redirect() -> None:
            await interrupted.wait()
            gate.redirected = True
            assert gate.channel is not None
            gate.channel._post(UserMessage(message=ChatMessageUser(content="REDIRECT")))

        async with anyio.create_task_group() as tg:
            tg.start_soon(redirect)
            with turn_gate(gate):
                state = await inner(state)
            tg.cancel_scope.cancel()
        return state

    return execute


@tool
def lookup() -> Tool:
    async def execute() -> str:
        """Look up a value."""
        return "ORIGINAL RESULT"

    return execute


@tool
def stall() -> Tool:
    async def execute() -> str:
        """Wait until interrupted."""
        current_agent_channel()._interrupt(Cancel())
        await anyio.sleep_forever()
        return "never"

    return execute


def _tool_turn(name: str = "lookup") -> ModelOutput:
    return ModelOutput.for_tool_call(
        model="mockllm/model", tool_name=name, tool_arguments={}
    )


def _overflow() -> ModelOutput:
    return ModelOutput.from_content(
        model="mockllm/model", content="overflow", stop_reason="model_length"
    )


def _done(submit: bool) -> ModelOutput:
    if submit:
        return ModelOutput.for_tool_call(
            model="mockllm/model", tool_name="submit", tool_arguments={"answer": "done"}
        )
    return ModelOutput.from_content(model="mockllm/model", content="done")


def _model_inputs(log: EvalLog) -> list[list[str]]:
    assert log.samples
    return [
        [m.text for m in e.input]
        for e in log.samples[0].events
        if isinstance(e, ModelEvent)
    ]


def _forced_compactions(log: EvalLog) -> int:
    assert log.samples
    return len(
        [
            e
            for e in log.samples[0].events
            if isinstance(e, CompactionEvent)
            and (e.metadata or {}).get("trigger") == "forced"
        ]
    )


def _count_resets(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Count `reset()` calls on the compaction handlers react creates."""
    import inspect_ai.agent._react as react_module

    resets: list[int] = []

    def create_counting(**kwargs: Any) -> Any:
        handler = compaction(**kwargs)
        reset = handler.reset

        async def counting_reset(prefix: list[ChatMessage]) -> None:
            resets.append(len(prefix))
            await reset(prefix)

        setattr(handler, "reset", counting_reset)
        return handler

    monkeypatch.setattr(react_module, "create_compaction", create_counting)
    return resets


def _replace_tool_result(messages: list[ChatMessage]) -> None:
    index = next(i for i, m in enumerate(messages) if m.role == "tool")
    messages[index] = messages[index].model_copy(update={"content": "REWRITTEN RESULT"})


_SUBMIT_IDS = ["react", "react_no_submit"]


@pytest.mark.parametrize("submit", [True, False], ids=_SUBMIT_IDS)
def test_react_turn_gate_runs_at_every_boundary(submit: bool) -> None:
    gate = _TestGate()
    task = Task(
        dataset=[Sample(input="Test")],
        solver=_gated(
            gate,
            react(
                tools=[lookup()],
                submit=submit,
                compaction=CompactionTrim(threshold=10_000),
            ),
        ),
    )
    model = get_model(
        "mockllm/model", custom_outputs=[_tool_turn(), _overflow(), _done(submit)]
    )

    log = eval(task, model=model)[0]

    assert log.status == "success"
    assert len(_model_inputs(log)) == 3
    # before the first generation, after a tool turn, after a recovered overflow
    assert [(c.has_assistant, c.last_role) for c in gate.calls] == [
        (False, "user"),
        (True, "tool"),
        (True, "tool"),
    ]
    assert all(c.state_matches for c in gate.calls)


@pytest.mark.parametrize("submit", [True, False], ids=_SUBMIT_IDS)
def test_react_turn_gate_runs_after_interrupt_redirect(submit: bool) -> None:
    gate = _TestGate()
    task = Task(
        dataset=[Sample(input="Test")],
        solver=_gated_with_redirect(gate, react(tools=[stall()], submit=submit)),
    )
    model = get_model(
        "mockllm/model", custom_outputs=[_tool_turn("stall"), _done(submit)]
    )

    log = eval(task, model=model)[0]

    assert log.status == "success"
    # never called while after_cancel() waits for the redirect
    assert [(c.interrupted, c.redirected) for c in gate.calls] == [
        (False, False),
        (True, True),
    ]
    assert gate.calls[1].texts[-1] == "REDIRECT"


@pytest.mark.parametrize("agent_kind", ["react", "deepagent"])
@pytest.mark.parametrize("change", ["replace", "delete", "append"])
def test_react_turn_gate_rewrite_reaches_model_input(
    agent_kind: str, change: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    resets = _count_resets(monkeypatch)

    def rewrite(index: int, messages: list[ChatMessage]) -> bool:
        if index != 1:
            return False
        if change == "replace":
            _replace_tool_result(messages)
            return True
        if change == "delete":
            messages[:] = [m for m in messages if m.text != "DELETE-ME"]
            return True
        messages.append(ChatMessageUser(content="APPENDED"))
        return False

    gate = _TestGate(rewrite)
    inner = (
        react(tools=[lookup()], compaction=CompactionTrim(threshold=10_000))
        if agent_kind == "react"
        else deepagent(tools=[lookup()])
    )
    task = Task(
        dataset=[
            Sample(
                input=[
                    ChatMessageUser(content="KEEP"),
                    ChatMessageUser(content="DELETE-ME"),
                ]
            )
        ],
        solver=_gated(gate, inner),
    )
    model = get_model("mockllm/model", custom_outputs=[_tool_turn(), _done(True)])

    log = eval(task, model=model)[0]

    assert log.status == "success"
    first, second = _model_inputs(log)
    assert "ORIGINAL RESULT" not in first and "DELETE-ME" in first
    if change == "replace":
        assert "REWRITTEN RESULT" in second
        assert "ORIGINAL RESULT" not in second
    elif change == "delete":
        assert "DELETE-ME" not in second
    else:
        assert second[-1] == "APPENDED"
    assert len(resets) == (0 if change == "append" else 1)


@pytest.mark.parametrize("submit", [True, False], ids=_SUBMIT_IDS)
@pytest.mark.parametrize("rewrite_after_overflow", [True, False])
def test_react_overflow_after_rewrite_forces_compaction_again(
    submit: bool, rewrite_after_overflow: bool
) -> None:
    def rewrite(index: int, messages: list[ChatMessage]) -> bool:
        # boundary 3 follows the overflow that forced compaction recovered
        if index == 3 and rewrite_after_overflow:
            _replace_tool_result(messages)
            return True
        return False

    task = Task(
        dataset=[Sample(input="Test")],
        solver=_gated(
            _TestGate(rewrite),
            react(
                tools=[lookup()],
                submit=submit,
                compaction=CompactionTrim(threshold=10_000),
                truncation="disabled",
            ),
        ),
    )
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            _tool_turn(),
            _tool_turn(),
            _overflow(),
            _overflow(),
            _done(submit),
        ],
    )

    log = eval(task, model=model)[0]

    assert log.status == "success"
    assert log.samples
    completion = log.samples[0].output.completion or ""
    if rewrite_after_overflow:
        assert _forced_compactions(log) == 2
        assert "done" in completion
    else:
        assert _forced_compactions(log) == 1
        assert "done" not in completion


def _anthropic_shaped_compact() -> Callable[..., Any]:
    """A stub `Model.compact()` returning Anthropic's shape: no system message."""

    async def compact(
        self: Model,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        instructions: str | None = None,
    ) -> tuple[list[ChatMessage], ModelUsage | None]:
        return [
            ChatMessageAssistant(content="[COMPACTED BLOCK]"),
            ChatMessageUser(content="Please continue working."),
        ], None

    return compact


@pytest.mark.parametrize("submit", [True, False], ids=_SUBMIT_IDS)
@pytest.mark.parametrize("strategy", ["native", "auto"])
@pytest.mark.parametrize(
    ("boundary", "role"), [(0, "system"), (1, "system"), (1, "user")]
)
def test_react_native_compaction_keeps_message_appended_at_boundary(
    submit: bool,
    strategy: str,
    boundary: int,
    role: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Model, "compact", _anthropic_shaped_compact())
    resets = _count_resets(monkeypatch)

    def append(index: int, messages: list[ChatMessage]) -> bool:
        if index != boundary:
            return False
        if role == "system":
            # an appended system message is a rewrite, as a runtime's gate
            # reports it, so the handler's saved prefix includes it
            messages.append(ChatMessageSystem(content="EXTRA SYSTEM"))
            return True
        messages.append(ChatMessageUser(content="EXTRA USER"))
        return False

    compaction_strategy = (
        CompactionNative(threshold=10_000)
        if strategy == "native"
        else CompactionAuto(threshold=10_000)
    )
    task = Task(
        dataset=[Sample(input="Test")],
        solver=_gated(
            _TestGate(append),
            react(tools=[lookup()], submit=submit, compaction=compaction_strategy),
        ),
    )
    outputs = [_overflow(), _done(submit)]
    if boundary == 1:
        outputs.insert(0, _tool_turn())
    model = get_model("mockllm/model", custom_outputs=outputs)

    log = eval(task, model=model)[0]

    assert log.status == "success"
    assert _forced_compactions(log) == 1
    after_compaction = _model_inputs(log)[-1]
    assert "[COMPACTED BLOCK]" in after_compaction
    if role == "system":
        assert "EXTRA SYSTEM" in after_compaction
        assert len(resets) == 1
    else:
        assert len(resets) == 0
