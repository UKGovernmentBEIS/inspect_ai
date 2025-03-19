from inspect_ai.agent import Agent, AgentState, agent, as_tool
from inspect_ai.tool import ToolDef


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


def test_agent_as_tool():
    tool = as_tool(web_surfer())
    tool_def = ToolDef(tool)
    assert tool_def.name == "web_surfer"
    assert (
        tool_def.description == "Web surfer for conducting web research into a topic."
    )
    assert len(tool_def.parameters.properties) == 2
    assert "input" in tool_def.parameters.properties
    assert "max_searches" in tool_def.parameters.properties
