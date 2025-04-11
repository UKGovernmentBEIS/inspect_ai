from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.log import EvalLog
from inspect_ai.model import ChatMessageUser, ModelOutput, get_model
from inspect_ai.model._model_output import ModelUsage
from inspect_ai.scorer import Score, Target, accuracy, includes, scorer
from inspect_ai.solver import Solver, TaskState, basic_agent, solver, system_message
from inspect_ai.solver._solver import Generate
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

    async def async_custom_incorrect_message(state: TaskState, scores: list[Score]):
        return f"Your response to the input '{state.input}' was incorrect: {scores[0].explanation}"

    def check_task(incorrect_message):
        addition_task = Task(
            dataset=[Sample(input="What is 1 + 1?", target="2")],
            solver=basic_agent(
                tools=[addition()],
                max_attempts=3,
                message_limit=30,
                incorrect_message=incorrect_message,
            ),
            scorer=compare_quantities(),
        )
        log = eval(addition_task, mockllm_model(["5", "1", "2"]), display="plain")[0]
        assert log.results.scores[0].metrics["accuracy"].value == 1
        user_msgs = [
            m.content for m in log.samples[0].messages if isinstance(m, ChatMessageUser)
        ]
        assert user_msgs == [
            "What is 1 + 1?",
            "Your response to the input 'What is 1 + 1?' was incorrect: Answer is too high",
            "Your response to the input 'What is 1 + 1?' was incorrect: Answer is too low",
        ]

    check_task(custom_incorrect_message)
    check_task(async_custom_incorrect_message)


def test_basic_agent_provide_answer():
    @solver
    def validate_answer() -> Solver:
        async def execute(state: TaskState, generate: Generate) -> TaskState:
            if state.output.completion == "2":
                raise RuntimeError("Submitted answer not properly concatenated")
            return state

        return execute

    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target=["2", "2.0", "Two"])],
        solver=[
            basic_agent(
                tools=[addition()],
                max_attempts=1,
                message_limit=30,
                submit_append=True,
            ),
            validate_answer(),
        ],
        scorer=includes(),
    )
    log = eval(task, mockllm_model(["2"]))[0]
    assert log.results.scores[0].metrics["accuracy"].value == 1


def test_basic_agent_respects_token_limit():
    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target=["2", "2.0", "Two"])],
        solver=basic_agent(token_limit=10),
        scorer=includes(),
    )
    model_output = ModelOutput.from_content(model="mockllm", content="hello")
    model_output.usage = ModelUsage(total_tokens=7)
    model = get_model("mockllm/model", custom_outputs=[model_output] * 5)

    log = eval(task, model)[0]

    assert log.status == "success"
    assert sum(usage.total_tokens for usage in log.stats.model_usage.values()) == 14


def test_basic_agent_respects_message_limit():
    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target=["2", "2.0", "Two"])],
        solver=basic_agent(message_limit=3),
        scorer=includes(),
    )
    model = get_model("mockllm/model")

    log = eval(task, model)[0]

    assert log.status == "success"
    assert len(log.samples[0].messages) == 3


def test_basic_agent_uses_task_message_limit():
    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target=["2", "2.0", "Two"])],
        solver=basic_agent(),
        scorer=includes(),
        message_limit=3,
    )
    model = get_model("mockllm/model")

    log = eval(task, model)[0]

    assert log.status == "success"
    assert len(log.samples[0].messages) == 3


def test_basic_agent_defaults_to_50_message_limit():
    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target=["2", "2.0", "Two"])],
        solver=basic_agent(),
        scorer=includes(),
    )
    model = get_model("mockllm/model")

    log = eval(task, model)[0]

    assert log.status == "success"
    assert len(log.samples[0].messages) == 50


if __name__ == "__main__":
    test_basic_agent_retries_with_custom_incorrect_message()
