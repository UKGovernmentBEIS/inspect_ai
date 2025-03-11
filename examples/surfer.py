from inspect_ai.model import ChatMessage, ChatMessageSystem, ChatMessageUser, get_model
from inspect_ai.tool import Tool, web_browser
from inspect_ai.util import StoreModel, store_as


class WebSurferState(StoreModel):
    messages: list[ChatMessage]


def web_surfer(context: str | None) -> Tool:
    """Stateful web surfer tool for researching topics.

    The web_surfer tool builds on the web_browser tool to complete sequences of
    web_browser actions in service of researching a topic. Input can either
    be requests to do research or questions about previous research.

    Args:
       context: Optional context used if you are creating multiple
         web_surfer tools within the scope of a single sample (e.g. one
         for each of two 'teams').
    """

    async def execute(input: str, clear_history: bool = False) -> str:
        """Use the web to research a topic.

        You may ask the web surfer any question. These questions can either
        prompt new web searches or be clarifying or follow up questions
        about previous web searches.

        Args:
           input: Message to the web server. This can either be a prompt
              to do research or a question about previous research.
           clear_history: Clear memory of previous questions and responses.

        Returns:
           Answer to research prompt or question.
        """
        # keep track of message history in the store
        state = store_as(WebSurferState, context)

        # clear history if requested.
        if clear_history:
            state.messages.clear()

        # provide system prompt if we are at the beginning
        if len(state.messages) == 0:
            state.messages.append(
                ChatMessageSystem(
                    content="""
                You are a helpful assistant that can use a web browser to
                answer questions. You don't need to answer the questions with
                a single web browser request, rather, you can perform searches,
                follow links, backtrack, and otherwise use the browser to its
                fullest capability to help answer the question.

                In some cases questions will be about your previous web searches,
                in those cases you don't always need to use the web browser tool
                but can answer by consulting previous conversation messages.
                """
                )
            )

        # append the latest question
        state.messages.append(ChatMessageUser(content=input))

        # web browser session
        output, messages = await get_model().generate_loop(
            state.messages, tools=web_browser()
        )

        # update state
        state.messages = messages

        # return response
        return output.completion

    return execute
