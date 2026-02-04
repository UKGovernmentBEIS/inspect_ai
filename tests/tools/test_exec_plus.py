from tests.test_helpers.tool_call_utils import get_tool_call, get_tool_response

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.model import (
    get_model,
)
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.scorer import match
from inspect_ai.solver import (
    generate,
    use_tools,
)
from inspect_ai.tool import Tool, tool
from inspect_ai.tool._exec_plus import (
    ExecPlusPollResponse,
    ExecPlusStartResponse,
    exec_plus_poll,
    exec_plus_start,
)
from inspect_ai.tool._sandbox_tools_utils.sandbox import (
    sandbox_with_injected_tools,
)


@tool
def bash_plus() -> Tool:
    async def execute() -> str:
        """
        Use this function or not, I don't care

        Returns:
          The output of the command.
        """
        exec_plus_start_response: ExecPlusStartResponse = await exec_plus_start(
            await sandbox_with_injected_tools(),
            cmd=[
                "bash",
                "--login",
                "-c",
                "echo TEST_VAR1: $TEST_VAR1; echo TEST_VAR2: $TEST_VAR2 >&2; pwd; cat",
            ],
            env={"TEST_VAR1": "value1", "TEST_VAR2": "value2"},
            cwd="/var",
            input="test input data\n",
        )

        result: ExecPlusPollResponse = await exec_plus_poll(
            await sandbox_with_injected_tools(), exec_plus_start_response.session_name
        )

        output = ""
        if result.stderr:
            output += f"{result.stderr}\n"
        output += result.stdout
        return output

    return execute


def test_exec_in_server():
    task = Task(
        dataset=[Sample(input="Have a go with bash_plus")],
        solver=[use_tools([bash_plus()]), generate()],
        scorer=match(),
        sandbox="local",
    )
    model = get_model(
        "mockllm/model",
        custom_outputs=[
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="bash_plus",
                tool_arguments={},
            ),
            ModelOutput.from_content(model="mockllm/model", content="All done."),
        ],
    )
    log = eval(task, model=model, time_limit=10)[0]
    assert log.status == "success"
    assert log.samples
    messages = log.samples[0].messages
    tool_call = get_tool_call(messages, "bash_plus")
    assert tool_call
    response = get_tool_response(messages, tool_call)
    assert response
    assert response.error is None, f"Tool call returns error: {response.error}"
    assert "TEST_VAR1: value1\n/var\ntest input data" in response.content, (
        f"Unexpected output from bash plus: {response.content}"
    )
