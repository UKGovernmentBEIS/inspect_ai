import json

import yaml
from rich import print
from rich.panel import Panel
from shortuuid import uuid

from inspect_ai.agent import Agent, AgentState, agent
from inspect_ai.agent._aide._agent_components import (
    execute_node,
    generate_new_node,
    parse_exec_result,
    search_policy,
)
from inspect_ai.agent._aide._data_models import AideConfig, AideState
from inspect_ai.agent._aide._tree_export import generate_tree
from inspect_ai.agent._aide._utils import (
    get_data_preview_in_container,
    setup_sandbox_workspace,
)
from inspect_ai.model import ChatMessageUser, get_model
from inspect_ai.tool import Tool, ToolFunction, ToolResult, tool, tool_with
from inspect_ai.util import store_as


async def aide_step(state: AideState) -> AideState:
    state.data_preview = await get_data_preview_in_container(
        str(state.config.workspace_dir),
    )

    # run the search policy to determine the next node to execute
    parent = await search_policy(state)

    # generate a new node
    node = await generate_new_node(parent, state)

    # execute the node
    exec_result = await execute_node(node, state)
    node = await parse_exec_result(state, node, exec_result)

    # update state
    state.journal.append(node)
    return state


async def save_run(state: AideState) -> AideState:
    config, journal = state.config, state.journal
    config.log_dir.mkdir(parents=True, exist_ok=True)

    # save journal
    json_data = journal.model_dump_json()
    with open(config.log_dir / "journal.json", "w") as f:
        json.dump(json_data, f)
    # save config
    with open(config.log_dir / "config.yaml", "w") as f:
        yaml.dump(config.model_dump(), f)

    # create the tree + code visualization
    generate_tree(config, journal, config.log_dir / "index.html")

    # save the best found solution
    best_node = journal.get_best_node(only_good=False)
    with open(config.log_dir / "best_solution.py", "w") as f:
        f.write(best_node.code)


def get_first_user_message(state: AgentState) -> str | None:
    """Get the first user message from the state."""
    for message in state.messages:
        if isinstance(message, ChatMessageUser):
            return message.content
    return None


@tool
def submit() -> Tool:
    async def execute(answer: str) -> ToolResult:
        """Submit an answer for evaluation.

        Args:
            answer (str): Submitted answer
        """
        return answer

    return execute


def initialize_aide_state(
    instance: str, agent_state: AgentState, **aide_config_kwargs
) -> AideState:
    """Initialize the AIDE state."""
    aide_state = store_as(AideState, instance=instance)
    aide_state.instance = instance
    aide_state.inspect_agent_state = agent_state
    task_description = get_first_user_message(agent_state)
    if task_description is None:
        raise ValueError("No task description found in state.")
    aide_state.task_description = task_description
    # raise error if any kwargs are passed not in aide_state.config.__fields__
    for key in aide_config_kwargs.keys():
        if key not in AideConfig.model_fields:
            raise ValueError(f"Invalid config key: {key}")

    # set kwargs
    for key, value in aide_config_kwargs.items():
        setattr(aide_state.config, key, value)

    return aide_state


@agent
def aide_agent(instance: str | None = uuid(), **aide_config_kwargs) -> Agent:
    async def execute(state: AgentState) -> AgentState:
        """AideML agent"""
        # initialize state
        aide_state = initialize_aide_state(
            instance=instance,
            agent_state=state,
            **aide_config_kwargs,
        )

        # setup workspace
        await setup_sandbox_workspace(
            data_dir=aide_state.config.data_dir,
            workspace_dir=aide_state.config.workspace_dir,
            preproc_data=aide_state.config.preproc_data,
        )

        # run the agent loop
        print(
            Panel(
                f"Starting AIDE agent. Logs saving to [bold blue]aide_logs/{aide_state.config.exp_name}[/bold blue].\n\nRun the following command:\n\n[bold]{aide_state.config.log_cmd}[/bold], then open [bold blue]http://localhost:8000[/bold blue] in your browser to view the logs.",
            )
        )
        global_step = 0
        while global_step < aide_state.config.agent_steps:
            aide_state = await aide_step(aide_state)
            await save_run(aide_state)
            global_step = len(aide_state.journal)

        # return the best solution
        best_node = aide_state.journal.get_best_node()

        aide_state.best_node = best_node

        # make a final call to the model to ask it to prepare the final submission
        prompt = (
            aide_state.config.prompt_config.final_answer_introduction_prompt.format(
                task_description=aide_state.task_description,
                best_node_details=best_node.model_dump(
                    exclude_unset=True, exclude_defaults=True
                ),
            )
        )
        tools = [tool_with(submit(), "submit", "Submit the final answer.")]
        final_message = await get_model().generate(
            input=prompt,
            tools=tools,
            tool_choice=ToolFunction("submit"),
        )
        assert len(final_message.message.tool_calls) == 1, (
            "Expected exactly one tool call."
        )
        answer = final_message.message.tool_calls[0].arguments["answer"]
        assert answer is not None, "No answer was submitted."
        state.output.completion = answer

        return state

    return execute
