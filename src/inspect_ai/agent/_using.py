import inspect
from contextlib import AsyncExitStack, ExitStack
from typing import Any, AsyncContextManager, ContextManager, cast

from inspect_ai._util.registry import is_registry_object, registry_unqualified_name

from ._agent import Agent, AgentState
from ._agent import agent as agent_decorator


def agent_using(
    agent: Agent,
    *cms: ContextManager[Any] | AsyncContextManager[Any],
) -> Agent:
    """Agent wrapped with the use of one or more context managers.

    Args:
      agent: Agent to wrap
      *cms: One or more context managers

    Returns:
      Agent which enters the context managers, executes,
      then exits the context managers.
    """
    # agent must be registered (so we can get its name)
    if not is_registry_object(agent):
        raise RuntimeError(
            "Agent passed to with_mcp_server was not created by an @agent decorated function"
        )
    agent_name = registry_unqualified_name(agent)

    @agent_decorator(name=agent_name)
    def agent_with_contexts() -> Agent:
        async def execute(state: AgentState) -> AgentState:
            # cleave into async and sync context managers
            async_cms: list[AsyncContextManager[Any]] = []
            sync_cms: list[ContextManager[Any]] = []
            for cm in cms:
                if hasattr(cm, "__aenter__") and inspect.iscoroutinefunction(
                    cm.__aenter__
                ):
                    async_cms.append(cast(AsyncContextManager[Any], cm))
                else:
                    sync_cms.append(cast(ContextManager[Any], cm))

            # enter context managers
            async with AsyncExitStack() as async_exit_stack:
                for async_cm in async_cms:
                    await async_exit_stack.enter_async_context(async_cm)

                with ExitStack() as exit_stack:
                    for sync_cm in sync_cms:
                        exit_stack.enter_context(sync_cm)

                    # run the agent
                    state = await agent(state)

            # return updated state
            return state

        return execute

    return agent_with_contexts()
