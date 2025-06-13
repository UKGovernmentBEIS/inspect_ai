import logging
import textwrap
from pathlib import Path

from inspect_ai.model import ChatMessageTool, ChatMessageUser
from inspect_ai.solver import Generate, Solver, TaskState, solver
from inspect_ai.tool import Tool, ToolFunction, ToolResult, python, tool
from inspect_ai.util import store

PROJECT_ROOT = Path(__file__).resolve().parent

logger = logging.getLogger(__name__)

PYTHON_TOOL_TIMEOUT = 30
ANSWER_FUNC_TIMEOUT = 30


@solver
def frontiermath_agent(
    token_limit: int = 100_000,
    forced_submit_tokens: int = 66_000,
) -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        if forced_submit_tokens >= token_limit:
            raise ValueError("forced_submit_tokens must be less than token_limit")

        store().set("submitted_answer", None)
        state.token_limit = token_limit
        state.tools = [python(timeout=PYTHON_TOOL_TIMEOUT), submit_answer()]
        state.tool_choice = "auto"

        state.messages = [
            ChatMessageUser(
                content=initial_prompt(
                    question=state.user_prompt.text,
                    answer_type=state.metadata["answer_type"],
                    token_limit=token_limit,
                    forced_submit_tokens=forced_submit_tokens,
                ),
            ),
        ]

        while state.token_usage < token_limit:
            state = await generate(state, tool_calls="single")

            if store().get("submitted_answer") is not None:
                break

            if state.token_usage >= forced_submit_tokens:
                if state.model.name and state.model.name.startswith(
                    "claude-3-7-sonnet"
                ):
                    state.tools = [submit_answer()]
                else:
                    state.tool_choice = ToolFunction("submit_answer")
                warning_message = (
                    f"You have used {state.token_usage:,} tokens, which is above the forced "
                    f"submission threshold of {forced_submit_tokens:,} tokens. (Hard limit: {token_limit:,} tokens). "
                    f"You must submit your answer now using the `submit_answer` tool. "
                )
                state.messages.append(ChatMessageUser(content=warning_message))
                continue

            state = insert_tool_call_help_message(state)

            message = (
                f"You have used {state.token_usage:,} tokens (forced submission: {forced_submit_tokens:,} tokens, "
                f"hard limit: {token_limit:,} tokens). "
                f"Continue exploring the problem, or submit your answer "
                f"using the `submit_answer` tool when you are confident in your answer."
            )
            state.messages.append(ChatMessageUser(content=message))

        return state

    return solve


@tool
def submit_answer() -> Tool:
    async def execute(answer_fn_code: str) -> ToolResult:
        store().set("submitted_answer", answer_fn_code)
        return "Your answer has been recorded. No feedback is provided."

    return execute


def insert_tool_call_help_message(state: TaskState) -> TaskState:
    message = state.messages[-1]
    if not isinstance(message, ChatMessageTool):
        return state

    if message.function == "python":
        if message.error and message.error.type in [
            "parsing",
            "timeout",
            "unicode_decode",
            "output_limit",
        ]:
            return state

        output = str(message.content)
        if output.strip() == "":
            help_message = (
                "I notice you used the Python tool but got no output. "
                "Remember, the tool only shows stdout (and stderr). You must include "
                "print() statements to see results.\n\n"
                "❌ Incorrect (no output):\n"
                "```python\n"
                "x = 5 * 12  # Calculation happens but not shown\n"
                "```\n\n"
                "✅ Correct (output shown):\n"
                "```python\n"
                "x = 5 * 12\n"
                "print(x)  # Shows: 60\n"
                "```\n"
            )
            state.messages.append(ChatMessageUser(content=help_message))

    return state


def initial_prompt(
    question: str, answer_type: str, token_limit: int, forced_submit_tokens: int
) -> str:
    requirements_path = PROJECT_ROOT / "agent-python-requirements.txt"
    with open(requirements_path) as f:
        requirements = f.read()

    requirements = requirements.strip()
    requirements = textwrap.indent(requirements, "\t" * 2)

    return TEMPLATE.format(
        question=question,
        answer_type=answer_type,
        token_limit=token_limit,
        forced_submit_tokens=forced_submit_tokens,
        requirements=requirements,
        python_tool_timeout=PYTHON_TOOL_TIMEOUT,
        answer_func_timeout=ANSWER_FUNC_TIMEOUT,
    )


TEMPLATE = r"""
You will be solving a challenging mathematics question. Here's how it works:
1. You can:
   - Think out loud and explore the problem
   - Use the `python` tool to execute arbitrary Python code
   - Submit your answer using the `submit_answer` tool when you are confident in your answer.

2. Token limits:
    - There is a hard limit of {token_limit:,} tokens. If you exceed this, the conversation will end
      immediately (even if you haven't submitted an answer).
    - If you reach {forced_submit_tokens:,} tokens (but less than the hard limit of {token_limit:,}),
      you will be forced to use the `submit_answer` tool in your next message. This forced submission
      stage is designed to give you the best chance of submitting an answer before reaching the
      hard token limit. But it is not a guarantee. It is still your responsibility to avoid hitting
      the hard limit.
    - Both input and output tokens count towards the limits.
3. Scoring:
   - If your answer is correct you will get 1 point. If it is incorrect, or if you don't submit an
     answer, you will get 0 points.
4. Explain your reasoning to me before submitting an answer.
5. Tips
    - I strongly recommend that you start by making a high-level plan for how you will attack the
      problem. If you can, think about different approaches that could be used to solve the problem.
      To help you stay on track, periodically summarize your key findings and potentially revise
      your plan.
    - Before submitting, verify your answer satisfies all problem requirements. It may be worth trying
      a different approach if you can see that your current answer is not correct.
6. For using the `submit_answer` tool:
   - Pass in the code of a Python function named 'answer' that:
       - Takes no parameters
       - Returns your answer as a {answer_type}
       - Prints no output
       - Contains no code comments
    - When scoring your answer, the maximum runtime for the `answer` function is
      {answer_func_timeout} seconds. The code is executed on typical commodity hardware for the year
       2025.
7. For using the `python` tool:
    * The tool will only return stdout (and stderr), so you must make sure to
     use print() to see your results. If you don't get any output from a `python` tool call, you
     probably forgot to print.
     * Example:
       ```python
       x = 5 * 12
       print("The result is", x)
       ```
       In this example, you must include the print statement. Otherwise, you won't see the value of
       x.
     * The tool is completely stateless and doesn't come with anything pre-imported. This is very
     important. If you need modules (e.g. math, sympy), you must import them each time. You cannot
     access variables defined in a previous call to `python`, so you must re-define anything you
     need in each call.
     * You have access to the standard library, and the following libraries (expressed in
     `requirements.txt` format):
       ```
{requirements}
       ```
     * Do not submit your answer using the `python` tool. Use the `submit_answer`
       tool when you're ready to submit
     * The maximum runtime for a `python` tool call is {python_tool_timeout} seconds. The code is
       executed on typical commodity hardware for the year 2025.
Here is the problem to solve. The answer type is {answer_type}.
{question}
"""
