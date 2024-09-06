from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.scorer import includes
from inspect_ai.solver import basic_agent
from inspect_ai.tool import tool


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


AGENT_SYSTEM_PROMPT = """
You are a helpful assistant attempting to submit the correct answer. When you have completed the task and have a result, call the agent_submit() function to communicate it.
"""


AGENT_INCORRECT_MESSAGE = "Your submission was incorrect."

AGENT_CONTINUE_MESSAGE = "Please proceed."

AGENT_SUBMIT_TOOL_NAME = "agent_submit"
AGENT_SUBMIT_TOOL_DESCRIPTION = "Submit an answer."
AGENT_SUBMIT_TOOL_RESPONSE = "Your submission will be evaluated."


def test_basic_agent_custom_text():
    task = Task(
        dataset=[Sample(input="What is 1 + 1?", target=["2", "2.0", "Two"])],
        plan=basic_agent(
            tools=[addition()],
            system_prompt=AGENT_SYSTEM_PROMPT,
            submit_tool_name=AGENT_SUBMIT_TOOL_NAME,
            submit_tool_description=AGENT_SUBMIT_TOOL_DESCRIPTION,
            submit_tool_response=AGENT_SUBMIT_TOOL_RESPONSE,
        ),
        scorer=includes(),
    )

    log = eval(task, model="mockllm/model")[0]
    assert log.status == "success"


if __name__ == "__main__":
    test_basic_agent_custom_text()
