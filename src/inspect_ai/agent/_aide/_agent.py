import json
import random
import time
from pathlib import Path
from typing import cast

import yaml
from pydantic import BaseModel, Field, computed_field
from rich import print
from rich.panel import Panel
from shortuuid import uuid

from inspect_ai import Task, eval, task
from inspect_ai.agent import Agent, AgentState, agent
from inspect_ai.agent._aide._journal import (
    ExecutionInfo,
    Journal,
    MetricValue,
    Node,
)
from inspect_ai.agent._aide._prompts import (
    PromptConfig,
    get_debug_prompt,
    get_draft_prompt,
    get_exec_result_prompt,
    get_improve_prompt,
)
from inspect_ai.agent._aide._tree_export import generate_tree
from inspect_ai.agent._aide._utils import (
    compile_prompt_to_md,
    extract_code,
    extract_text_up_to_code,
    get_data_preview_in_container,
    setup_sandbox_workspace,
)
from inspect_ai.dataset import Sample
from inspect_ai.log import transcript
from inspect_ai.model import ChatMessageSystem, ChatMessageUser, get_model
from inspect_ai.tool import Tool, ToolFunction, ToolResult, tool, tool_with, web_browser
from inspect_ai.util import StoreModel, sandbox, store_as


@agent
def web_surfer() -> Agent:
    async def execute(state: AgentState) -> AgentState:
        """Web research assistant."""
        # some general guidance for the agent
        state.messages.append(
            ChatMessageSystem(
                content="You are a tenacious web researcher that is "
                + "expert at using a web browser to answer questions."
            )
        )

        # run a tool loop w/ the web_browser then update & return state
        messages, state.output = await get_model().generate_loop(
            state.messages, tools=web_browser()
        )
        state.messages.extend(messages)
        return state

    return execute


class AgentConfig(BaseModel):
    goal: str | None = Field(
        default=None,
        description="The goal of the agent. Can be provided along with `evaluation_metric` to evaluate the agent's performance. Both of these values will be used to build the task description. If running via an inspect solver, this value will be overridden by `sample.input`.",
    )

    evaluation_metric: str | None = Field(
        default=None,
        description="The evaluation metric for the agent. Can be provided along with `goal` to evaluate the agent's performance. Both of these values will be used to build the task description. If running via an inspect solver, this value will be overridden by `sample.input`.",
    )

    task_description: str | None = Field(
        default=None,
        description="The task description for the agent. Can be provided directly, or if left empty, will be generated from `goal` and `evaluation_metric`. If running via an inspect solver, this value will be overridden by `sample.input`.",
    )

    data_dir: Path | None = Field(
        default=Path("/home/ubuntu/workspace/aideml-inspect/aide_inspect/assets/test"),
        description="A local data directory to copy files from to the agent workspace. This will be copied to the workspace directory.",
    )

    num_drafts: int = Field(
        default=1,
        description="The number of drafts to generate before improving nodes.",
    )

    debug_prob: float = Field(
        default=0.5,
        description="The probability of debugging a node instead of drafting a new one at each step.",
    )

    agent_steps: int = Field(
        default=10,
        description="The number of steps the agent should run for.",
        ge=1,
    )

    exec_timeout: int = Field(
        default=600,
        description="The maximum time in seconds that the agent should allow for code execution.",
        ge=1,
    )

    # prompt_config: PromptConfig = PromptConfig()
    prompt_config: PromptConfig = Field(
        default_factory=PromptConfig,
        description="The configuration for the prompts used by the agent.",
    )

    exp_name: str | None = Field(
        default_factory=lambda: uuid(),
        description="The name of the experiment. If not provided, a random name will be generated.",
    )

    workspace_dir: Path = Field(
        default=Path("/app/workspaces/workspace"),
        description="The directory where the agent will execute code. Defaults to /app/workspaces/workspace.",
    )

    preproc_data: bool = Field(
        default=True,
        description="Whether to preprocess the data in the data_dir before copying it to the workspace.",
    )

    @computed_field
    @property
    def log_dir(self) -> Path:
        top_log_dir = Path("aide_logs")
        exp_name = self.exp_name or uuid()
        return (top_log_dir / exp_name).resolve()

    @computed_field
    @property
    def log_cmd(self) -> str:
        return f"python3 -m http.server 8000 --directory {self.log_dir}"

    def model_post_init(self, __context):
        if self.task_description is None and self.goal is not None:
            td = {"Task goal": self.goal}
            if self.evaluation_metric:
                td["Task evaluation metric"] = self.evaluation_metric
            self.task_description = compile_prompt_to_md(td)


class AideState(StoreModel):
    journal: Journal = Field(default_factory=Journal)
    config: AgentConfig = Field(default_factory=AgentConfig)
    data_preview: str = Field(default_factory=str)
    task_description: str = Field(default_factory=str)
    inspect_agent_state: AgentState | None = Field(default=None)
    instance: str | None = Field(default=None)
    best_node: Node | None = Field(default=None)

    class Config:
        arbitrary_types_allowed = True


async def search_policy(state: AideState) -> Node | None:
    journal, config = state.journal, state.config
    # draft a new node if we haven't drafted enough nodes
    if len(journal.draft_nodes) < config.num_drafts:
        transcript().info("Drafting a new node")
        return None
    # select a random node to debug with p(config.debug_prob)
    if random.random() < config.debug_prob:
        transcript().info("Selecting a random debuggable node")
        debuggable_nodes = journal.buggy_nodes
        if debuggable_nodes:
            return random.choice(debuggable_nodes)
        return None
    # otherwise, keep drafting new nodes if there are no nodes to improve
    good_nodes = journal.good_nodes
    if not good_nodes:
        transcript().info("Drafting a new node")
        return None
    # otherwise, greedily get the best node to improve
    transcript().info("Selecting the best node to improve")
    return journal.get_best_node(only_good=True)


async def plan_and_code_query(
    state: AideState, prompt: str, retries: int = 3
) -> tuple[str, str]:
    completion_text = None
    for _ in range(retries):
        completion = await get_model().generate(
            input=prompt,
        )
        if state.inspect_agent_state is not None:
            state.inspect_agent_state.messages.append(completion.message)
        completion_text = completion.completion
        code = extract_code(completion_text)
        nl_text = extract_text_up_to_code(completion_text)

        if code and nl_text:
            return nl_text, code

        transcript().info("Retrying due to missing code or text")
    transcript().info("Failed to generate code and text, giving up")
    return "", cast(str, completion_text)


async def draft(state: AideState) -> Node:
    prompt = get_draft_prompt(state)
    plan, code = await plan_and_code_query(state, prompt)
    return Node(plan=plan, code=code, step=len(state.journal))


async def improve(state: AideState, parent: Node) -> Node:
    prompt = get_improve_prompt(state, parent)
    plan, code = await plan_and_code_query(state, prompt)
    return Node(plan=plan, code=code, parent=parent, step=len(state.journal))


async def debug(state: AideState, parent: Node) -> Node:
    prompt = get_debug_prompt(state, parent)
    plan, code = await plan_and_code_query(state, prompt)
    return Node(
        plan=plan,
        code=code,
        parent=parent,
        is_buggy=True,
        step=len(state.journal),
    )


async def generate_new_node(parent: Node, state: AideState) -> Node:
    transcript().info(
        f"Generating new node with parent {parent.stage_name if parent else 'draft'}"
    )
    if parent is None:
        node = await draft(state)
    elif parent.is_buggy:
        node = await debug(state, parent)
    else:
        node = await improve(state, parent)
    return node


async def execute_node(node: Node, state: AideState) -> ExecutionInfo:
    sbox = sandbox()

    # make workspace dir if it doesn't exist
    await sbox.exec(["mkdir", "-p", str(state.config.workspace_dir)])

    # write tmp file to workspace
    tmp_file_name = f"{uuid()}.py"
    tmp_file_path = f"{state.config.workspace_dir}/{tmp_file_name}"
    await sbox.write_file(file=tmp_file_path, contents=node.code)

    # execute the code
    start = time.time()
    exec_result = await sbox.exec(
        ["python3", tmp_file_name],
        timeout=state.config.exec_timeout,
        cwd=str(state.config.workspace_dir),
    )
    exec_time = time.time() - start

    # cleanup
    await sbox.exec(["rm", tmp_file_path])

    # return execution info
    return ExecutionInfo(
        return_code=exec_result.returncode,
        stdout=exec_result.stdout,
        stderr=exec_result.stderr,
        exec_time=exec_time,
    )


async def parse_exec_result(
    state: AideState, node: Node, exec_result: ExecutionInfo
) -> Node:
    # submit_review tool is used for structured output
    @tool
    def submit_review() -> Tool:
        """Submit tool for the agent."""

        async def execute(
            is_bug: bool, summary: str, metric: float, lower_is_better: bool
        ) -> str:
            """Submit an answer for evaluation.

            Args:
                is_bug (bool): Whether the code contains a bug.
                summary (str): A summary of the evaluation.
                metric (float): The evaluation metric.
                lower_is_better (bool): Whether a lower metric value is better.

            Returns:
            The output of the Python code.
            """
            return "Review submitted."

        return execute

    transcript().info(f"Agent is parsing execution results for node {node.id}")
    node.execution_info = exec_result
    prompt_str = get_exec_result_prompt(state, node)
    completion = await get_model().generate(
        input=prompt_str,
        tools=[
            tool_with(
                submit_review(),
                name="submit_review",
                description=state.config.prompt_config.submit_review_tool_description,
            )
        ],
        tool_choice=ToolFunction("submit_review"),
    )
    tool_calls = completion.message.tool_calls
    assert len(tool_calls) == 1
    tool_call = tool_calls[0]
    if tool_call.parse_error:
        raise ValueError(f"Error parsing tool call: {tool_call.parse_error}")
    assert tool_call.function == "submit_review"
    response = tool_call.arguments
    if not isinstance(response["metric"], float):
        response["metric"] = None
    node.analysis = response["summary"]
    node.is_buggy = (
        response["is_bug"]
        or node.execution_info.return_code != 0
        or response["metric"] is None
    )
    node.metric = MetricValue(
        value=response["metric"], maximize=not response["lower_is_better"]
    )
    return node


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


@agent
def aide_agent(instance: str | None = uuid()) -> Agent:
    async def execute(state: AgentState) -> AgentState:
        """AideML agent"""
        agent_state = store_as(AideState, instance=instance)
        agent_state.instance = instance
        agent_state.inspect_agent_state = state
        task_description = get_first_user_message(state)
        if task_description is None:
            raise ValueError("No task description found in state.")
        agent_state.task_description = task_description

        print(
            Panel(
                f"Starting AIDE agent. Logs saving to [bold blue]aide_logs/{agent_state.config.exp_name}[/bold blue].\n\nRun the following command:\n\n[bold]{agent_state.config.log_cmd}[/bold], then open [bold blue]http://localhost:8000[/bold blue] in your browser to view the logs.",
            )
        )

        global_step = 0

        # setup workspace
        await setup_sandbox_workspace(
            data_dir=agent_state.config.data_dir,
            workspace_dir=agent_state.config.workspace_dir,
            preproc_data=agent_state.config.preproc_data,
        )

        # run the agent loop
        while global_step < agent_state.config.agent_steps:
            agent_state = await aide_step(agent_state)
            await save_run(agent_state)
            global_step = len(agent_state.journal)

        # return the best solution
        best_node = agent_state.journal.get_best_node()

        agent_state.best_node = best_node

        # make a final call to the model to ask it to prepare the final submission
        prompt = (
            agent_state.config.prompt_config.final_answer_introduction_prompt.format(
                task_description=task_description,
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


@task
def hello_world():
    from inspect_ai.scorer import exact

    return Task(
        dataset=[
            Sample(
                input="Just reply with Hello World",
                target="Hello World",
            )
        ],
        solver=[
            aide_agent(),
        ],
        scorer=exact(),
        sandbox="docker",
    )


if __name__ == "__main__":
    from inspect_ai import eval

    log = eval(hello_world(), model="anthropic/claude-3-7-sonnet-20250219")
    print(".")
