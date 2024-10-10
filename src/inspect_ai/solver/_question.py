from inspect_ai.model._chat_message import ChatMessageUser
from inspect_ai.solver._solver import Generate, Solver, solver
from inspect_ai.solver._task_state import TaskState
from inspect_ai.util import resource


@solver
def no_solver() -> Solver:
    r"Identity solver. Keeps the task state intact."

    # do nothing
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        return state

    # return solve
    return solve


DEFAULT_CHAT_TEMPLATE = "{messages}\n\n<assistant>\n(Please reply in the role of the assistant.)"
DEFAULT_MESSAGE_TEMPLATE = "<{role}>\n{content}"

@solver
def chat_summary(
    message_template: str | None = None,
    chat_template: str | None = None,
) -> Solver:
    r"""
    Solver which summarizes the whole conversation, up to the last user message,
    and writes it onto the first user prompt.
    The solver can be used when evaluating a multi-turn chat.

    Args:
      message_template (str | None): String or path to file containing
         template used for one message. The template uses two variables:
         `content`, and `role`.
      chat_template (str | None): String or path to file containing
         template used for the whole chat. The template uses one variable:
         `messages`.
    """

    # resolve template
    message_template = resource(message_template or DEFAULT_MESSAGE_TEMPLATE)
    chat_template = resource(chat_template or DEFAULT_CHAT_TEMPLATE)

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        # determine the location of the last user message
        last_user_index = 0
        for i, message in enumerate(state.messages):
            if isinstance(message, ChatMessageUser):
                last_user_index = i

        # summarize all the messages up to the last user message
        messages = "\n\n".join([
            message_template.format(
                content=message.content,
                role=message.role,
            )
            for i, message in enumerate(state.messages)
            if i <= last_user_index
        ])
        state.messages = [ChatMessageUser(content=chat_template.format(
            messages=messages,
        ))]
        return state

    return solve
