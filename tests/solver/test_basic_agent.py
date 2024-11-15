from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.log import EvalLog
from inspect_ai.model import ChatMessageUser, ModelOutput, get_model
from inspect_ai.scorer import Score, Target, accuracy, includes, scorer
from inspect_ai.solver import Solver, TaskState, basic_agent, solver, system_message
from inspect_ai.tool import Tool, tool


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


AGENT_SYSTEM_MESSAGE = """
You are a helpful assistant attempting to submit the correct answer. When you have completed the task and have a result, call the agent_submit() function to communicate it.
"""


AGENT_INCORRECT_MESSAGE = "Your submission was incorrect."

AGENT_CONTINUE_MESSAGE = "Please proceed."

AGENT_SUBMIT_TOOL_NAME = "agent_submit"
AGENT_SUBMIT_TOOL_DESCRIPTION = "Submit an answer."


def run_basic_agent(
    tools: list[Tool] | Solver, message_limit: int | None = 30
) -> EvalLog:
    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target=["2", "2.0", "Two"])],
        solver=basic_agent(
            init=system_message(AGENT_SYSTEM_MESSAGE),
            tools=tools,
            submit_name=AGENT_SUBMIT_TOOL_NAME,
            submit_description=AGENT_SUBMIT_TOOL_DESCRIPTION,
        ),
        scorer=includes(),
        message_limit=message_limit,
    )

    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name=AGENT_SUBMIT_TOOL_NAME,
                tool_arguments={"answer": "2"},
            )
        ],
    )

    return eval(task, model=model)[0]


def mockllm_model(answers: list[str]):
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


def test_basic_agent_solver():
    @solver
    def addition_tool() -> Solver:
        async def solve(state, generate):
            state.tools = [addition()]
            return state

        return solve

    log = run_basic_agent(addition_tool())
    assert log.status == "success"
    assert log.results.scores[0].metrics["accuracy"].value == 1


def test_basic_agent_custom_text():
    log = run_basic_agent([addition()])
    assert log.status == "success"
    assert log.samples[0].messages[0].content == AGENT_SYSTEM_MESSAGE
    tool_event = next(
        (event for event in log.samples[0].transcript.events if event.event == "tool")
    )
    assert tool_event
    assert tool_event.function == AGENT_SUBMIT_TOOL_NAME
    model_event = next(
        (event for event in log.samples[0].transcript.events if event.event == "model")
    )
    assert model_event
    assert model_event.tools[1].name == AGENT_SUBMIT_TOOL_NAME
    assert model_event.tools[1].description == AGENT_SUBMIT_TOOL_DESCRIPTION


def test_basic_agent_retries():
    def addition_task(max_attempts):
        return Task(
            dataset=[Sample(input="What is 1 + 1?", target=["2", "2.0", "Two"])],
            solver=basic_agent(
                tools=[addition()], max_attempts=max_attempts, message_limit=30
            ),
            scorer=includes(),
        )

    # incorrect answer with no retries
    log = eval(addition_task(1), mockllm_model(["5"]))[0]
    assert log.results.scores[0].metrics["accuracy"].value == 0

    # correct answer on the third try
    log = eval(addition_task(3), mockllm_model(["5", "4", "2"]))[0]
    assert log.results.scores[0].metrics["accuracy"].value == 1
    model_events = sum(
        1 for event in log.samples[0].transcript.events if event.event == "model"
    )
    assert model_events == 3


def test_basic_agent_retries_with_custom_incorrect_message():
    @scorer(metrics=[accuracy()])
    def compare_quantities():
        async def score(state: TaskState, target: Target) -> Score:
            answer = float(state.output.completion)
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

    def custom_incorrect_message(state: TaskState, scores: list[Score]):
        return f"Your response to the input '{state.input}' was incorrect: {scores[0].explanation}"

    addition_task = Task(
        dataset=[Sample(input="What is 1 + 1?", target="2")],
        solver=basic_agent(
            tools=[addition()],
            max_attempts=3,
            message_limit=30,
            incorrect_message=custom_incorrect_message,
        ),
        scorer=compare_quantities(),
    )
    log = eval(addition_task, mockllm_model(["5", "1", "2"]))[0]
    assert log.results.scores[0].metrics["accuracy"].value == 1
    user_msgs = [
        m.content for m in log.samples[0].messages if isinstance(m, ChatMessageUser)
    ]
    assert user_msgs == [
        "What is 1 + 1?",
        "Your response to the input 'What is 1 + 1?' was incorrect: Answer is too high",
        "Your response to the input 'What is 1 + 1?' was incorrect: Answer is too low",
    ]
