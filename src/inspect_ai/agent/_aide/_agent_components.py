import random
import time
from typing import cast

from shortuuid import uuid

from inspect_ai.agent._aide._data_models import (
    AideState,
)
from inspect_ai.agent._aide._journal import (
    ExecutionInfo,
    MetricValue,
    Node,
)
from inspect_ai.agent._aide._utils import (
    compile_prompt_to_md,
    extract_code,
    extract_text_up_to_code,
    wrap_code,
)
from inspect_ai.log import transcript
from inspect_ai.model import get_model
from inspect_ai.tool import Tool, ToolFunction, tool, tool_with
from inspect_ai.util import sandbox


def get_draft_prompt(state: AideState) -> str:
    journal = state.journal
    config = state.config
    data_preview = state.data_preview
    prompt_config = config.prompt_config
    pkgs = prompt_config.available_packages
    random.shuffle(pkgs)
    pkg_str = ", ".join([f"`{p}`" for p in pkgs])
    prompt = {
        "Introduction": prompt_config.draft_introduction_prompt,
        "Task description": state.task_description,
        "Memory": journal.generate_summary(),
        "Instructions": {
            "Response format": prompt_config.response_format_prompt,
            "Solution sketch guideline": prompt_config.solution_sketch_guideline_prompt,
            "Implementation guideline": prompt_config.implementation_guideline_prompt.format(
                timeout=config.exec_timeout
            ),
            "Installed Packages": prompt_config.available_packages_prompt.format(
                packages=pkg_str
            ),
        },
    }
    if data_preview:
        prompt["Data Overview"] = data_preview
    return compile_prompt_to_md(prompt)


def get_improve_prompt(state: AideState, parent: Node) -> str:
    journal = state.journal
    config = state.config
    prompt_config = config.prompt_config
    prompt = {
        "Introduction": prompt_config.improvement_introduction_prompt,
        "Task description": state.task_description,
        "Memory": journal.generate_summary(),
        "Instructions": {
            "Response format": prompt_config.response_format_prompt,
            "Solution improvement sketch guideline": prompt_config.solution_improvement_sketch_guideline_prompt,
            "Implementation guideline": prompt_config.implementation_guideline_prompt.format(
                timeout=config.exec_timeout
            ),
        },
        "Previous solution": {
            "Code": wrap_code(parent.code),
        },
    }
    return compile_prompt_to_md(prompt)


def get_debug_prompt(state: AideState, parent: Node) -> str:
    config = state.config
    prompt_config = config.prompt_config
    data_preview = state.data_preview
    execution_output = (
        parent.execution_info.term_out if parent.execution_info else "NO OUTPUT"
    )
    prompt = {
        "Introduction": prompt_config.debug_introduction_prompt,
        "Task description": state.task_description,
        "Previous (buggy) implementation": wrap_code(parent.code),
        "Execution output": wrap_code(execution_output, lang=""),
        "Instructions": {
            "Response format": prompt_config.response_format_prompt,
            "Bugfix improvement sketch guideline": prompt_config.bugfix_improvement_sketch_guideline_prompt,
            "Implementation guideline": prompt_config.implementation_guideline_prompt.format(
                timeout=config.exec_timeout
            ),
        },
    }
    if data_preview:
        prompt["Data Overview"] = data_preview
    return compile_prompt_to_md(prompt)


def get_exec_result_prompt(state: AideState, node: Node) -> str:
    prompt = {
        "Introduction": state.config.prompt_config.execution_result_introduction_prompt,
        "Task description": state.task_description,
        "Implementation": wrap_code(node.code),
        "Execution output": wrap_code(node.execution_info.term_out, lang=""),
    }
    return compile_prompt_to_md(prompt)


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
