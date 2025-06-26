from textwrap import dedent

from pydantic import Field
from shortuuid import uuid

from inspect_ai.model import ChatMessage, ChatMessageSystem, ChatMessageUser, get_model
from inspect_ai.tool import Tool, tool, web_browser
from inspect_ai.util import StoreModel, store_as


class WebSurferState(StoreModel):
    messages: list[ChatMessage] = Field(default_factory=list)


@tool
def web_surfer(instance: str | None = None) -> Tool:
    """Stateful web surfer tool for researching topics.

    The web_surfer tool builds on the web_browser tool to complete sequences of
    web_browser actions in service of researching a topic. Input can either
    be requests to do research or questions about previous research.
    """
    instance = instance if instance is not None else uuid()

    async def execute(input: str, clear_history: bool = False) -> str:
        """Use the web to research a topic.

        You may ask the web surfer any question. These questions can either
        prompt new web searches or be clarifying or follow up questions
        about previous web searches.

        Args:
           input: Message to the web surfer. This can either be a prompt
              to do research or a question about previous research.
           clear_history: Clear memory of previous questions and responses.

        Returns:
           Answer to research prompt or question.
        """
        # keep track of message history in the store
        surfer_state = store_as(WebSurferState, instance=instance)

        # clear history if requested.
        if clear_history:
            surfer_state.messages.clear()

        # provide system prompt if we are at the beginning
        if len(surfer_state.messages) == 0:
            surfer_state.messages.append(
                ChatMessageSystem(
                    content=dedent("""
                You are a helpful assistant that can use a web browser to
                answer questions. You don't need to answer the questions with
                a single web browser request, rather, you can perform searches,
                follow links, backtrack, and otherwise use the browser to its
                fullest capability to help answer the question.

                In some cases questions will be about your previous web searches,
                in those cases you don't always need to use the web browser tool
                but can answer by consulting previous conversation messages.
                """)
                )
            )

        # append the latest question
        surfer_state.messages.append(ChatMessageUser(content=input))

        # run tool loop with web browser
        messages, output = await get_model().generate_loop(
            surfer_state.messages, tools=web_browser(instance=instance)
        )

        # update state
        surfer_state.messages.extend(messages)

        # return response
        return output.completion

    return execute
