import re

from inspect_ai import Task, eval
from inspect_ai.agent._agent import Agent, AgentState, agent
from inspect_ai.agent._handoff import handoff
from inspect_ai.agent._react import react
from inspect_ai.agent._types import AgentAttempts, AgentPrompt, AgentSubmit
from inspect_ai.dataset import Sample
from inspect_ai.log import EvalLog
from inspect_ai.model import ChatMessageUser, ModelOutput, get_model
from inspect_ai.model._chat_message import ChatMessage, ChatMessageSystem
from inspect_ai.scorer import Score, Target, accuracy, includes, scorer
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.tool import Tool, tool
from inspect_ai.tool._tool_def import ToolDef


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
You are a helpful assistant attempting to submit the correct answer. When you have completed the task and have a result, call the agent_submit() function to communicate it.
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
                tool_name=submit.name or ToolDef(submit.tool).name
                if submit.tool
                else AGENT_SUBMIT_TOOL_NAME,
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


def test_react_agent_retries() -> None:
    def addition_task(max_attempts: int) -> Task:
        return Task(
            dataset=[Sample(input="What is 1 + 1?", target=["2", "2.0", "Two"])],
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
    on_continue = "Please keep going and call the {submit}() tool!"
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
    assert messages[-2].text == on_continue.format(submit="submit")


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
