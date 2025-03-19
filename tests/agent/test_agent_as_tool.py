from inspect_ai.agent._agent import Agent, AgentState, agent


@agent
def web_surfer() -> Agent:
    async def execute(state: AgentState, max_searches: int = 3) -> AgentState:
        """Web surfer for conducting web research into a topic.

        Args:
            state: Input state (conversation)
            max_searches: Maximum number of web searches to conduct

        Retruns:
            Ouput state (additions to conversation)
        """
        return state

    return execute
