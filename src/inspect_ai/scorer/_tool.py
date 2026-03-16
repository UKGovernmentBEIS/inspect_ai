from inspect_ai.model._chat_message import ChatMessageAssistant
from inspect_ai.scorer import Score, Scorer, Target, accuracy, scorer, stderr
from inspect_ai.solver import TaskState


@scorer(metrics=[accuracy(), stderr()])
def require_tool(
    base_scorer: Scorer, tool_name: str = "submit", fail_value: str = "I"
) -> Scorer:
    """
    A modifier that wraps a scorer to prevent false positives from aborted agent loops.

    It verifies that the specified tool was explicitly called in the agent's final action.
    """
    assert base_scorer is not None, "base_scorer must be provided"

    async def score(state: TaskState, target: Target) -> Score | None:
        # 1. Immediate failure for hard aborts (limits)
        if state.output.error is not None:
            return Score(
                value=fail_value,
                answer=state.output.completion,
                explanation=f"Run aborted due to {state.output.error}. Required tool '{tool_name}' was not the final action.",
            )

        # 2. Check whether the tool was used in the LAST action
        tool_used = False
        for msg in reversed(state.messages):
            if isinstance(msg, ChatMessageAssistant):
                if msg.tool_calls:
                    if any(tc.function == tool_name for tc in msg.tool_calls):
                        tool_used = True
                break  # Only check the last agent turn!

        # 3. If the loop ended without using the tool as the final action -> fail
        if not tool_used:
            return Score(
                value=fail_value,
                answer=state.output.completion,
                explanation=f"Agent finished without explicitly calling the '{tool_name}' tool in its final turn.",
            )

        # 4. All good: let the base_scorer verify the answer (already extracted by the agent)
        return await base_scorer(state, target)

    return score
