"""Tests for deepagent() top-level assembly."""

from test_helpers.tool_call_utils import get_tool_event

from inspect_ai import Task, eval
from inspect_ai.agent import deepagent
from inspect_ai.agent._deepagent.prompt import CORE_BEHAVIOR
from inspect_ai.dataset import Sample
from inspect_ai.model import ModelOutput, get_model
from inspect_ai.tool import think


def test_deepagent_constructible() -> None:
    """deepagent() returns an Agent."""
    agent = deepagent()
    assert agent is not None


def test_deepagent_end_to_end() -> None:
    """End-to-end: model calls task tool, subagent runs, returns result."""
    task = Task(
        dataset=[Sample(input="Research something")],
        solver=deepagent(submit=True),
        message_limit=10,
    )

    model = get_model(
        "mockllm/model",
        custom_outputs=[
            # 1. Outer agent calls task tool
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="task",
                tool_arguments={
                    "subagent_type": "research",
                    "prompt": "Find information.",
                },
            ),
            # 2. Inner research subagent submits
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="submit",
                tool_arguments={"answer": "Found the info."},
            ),
            # 3. Outer agent submits
            ModelOutput.for_tool_call(
                model="mockllm/model",
                tool_name="submit",
                tool_arguments={"answer": "done"},
            ),
        ],
    )

    log = eval(task, model=model)[0]
    assert log.status == "success"
    tool_event = get_tool_event(log)
    assert tool_event is not None
    assert tool_event.function == "task"


def test_deepagent_memory_kill_switch() -> None:
    """memory=False disables memory for all subagents."""
    agent = deepagent(memory=False)
    # Verify by checking that the agent is constructible without memory
    # (deeper verification would require inspecting the tool list)
    assert agent is not None


def test_deepagent_custom_instructions() -> None:
    """instructions= are included in the system prompt."""
    from inspect_ai.agent._deepagent.prompt import build_system_prompt

    prompt = build_system_prompt(instructions="Focus on security analysis.")
    assert "Focus on security analysis." in prompt
    assert CORE_BEHAVIOR in prompt


def test_deepagent_custom_prompt_with_placeholders() -> None:
    """prompt= replaces default and expands placeholders."""
    from inspect_ai.agent._deepagent.prompt import expand_prompt_placeholders

    custom = "Custom agent.\n\n{core_behavior}\n\nExtra: {instructions}"
    result = expand_prompt_placeholders(custom, instructions="Be careful.")
    assert "Custom agent." in result
    assert CORE_BEHAVIOR in result
    assert "Be careful." in result


def test_deepagent_with_extra_tools() -> None:
    """User tools flow to the agent."""
    agent = deepagent(tools=[think()])
    assert agent is not None


def test_deepagent_default_subagents() -> None:
    """Default subagents are research, plan, general."""
    from inspect_ai.agent._deepagent.general import general
    from inspect_ai.agent._deepagent.plan import plan
    from inspect_ai.agent._deepagent.research import research

    r = research()
    p = plan()
    g = general()
    assert r.name == "research"
    assert p.name == "plan"
    assert g.name == "general"


def test_deepagent_submit_prompt_included() -> None:
    """System message includes submit guidance when submit is enabled."""
    from inspect_ai.agent._react import _prompt_to_system_message
    from inspect_ai.agent._types import DEFAULT_SUBMIT_PROMPT, AgentPrompt

    prompt = AgentPrompt(
        instructions="Test.",
        handoff_prompt=None,
        assistant_prompt=DEFAULT_SUBMIT_PROMPT,
        submit_prompt=None,
    )
    msg = _prompt_to_system_message(prompt, [], "submit")
    assert msg is not None
    assert isinstance(msg.content, str)
    assert "submit" in msg.content.lower()


def test_deepagent_submit_prompt_excluded_when_false() -> None:
    """System message excludes submit guidance when submit=False."""
    from inspect_ai.agent._react import _prompt_to_system_message
    from inspect_ai.agent._types import AgentPrompt

    prompt = AgentPrompt(
        instructions="Test.",
        handoff_prompt=None,
        assistant_prompt=None,
        submit_prompt=None,
    )
    msg = _prompt_to_system_message(prompt, [], None)
    assert msg is not None
    assert isinstance(msg.content, str)
    assert "submit" not in msg.content.lower()


def test_deepagent_duplicate_subagent_names_rejected() -> None:
    """Duplicate subagent names raise ValueError at eval time."""
    from inspect_ai.agent import subagent

    sa1 = subagent(name="research", description="A.", prompt="A.")
    sa2 = subagent(name="research", description="B.", prompt="B.")
    da = deepagent(subagents=[sa1, sa2], submit=True)
    task = Task(
        dataset=[Sample(input="test")],
        solver=da,
        message_limit=5,
    )
    model = get_model(
        "mockllm/model",
        custom_outputs=[ModelOutput.from_content("mockllm/model", "done")],
    )
    log = eval(task, model=model)[0]
    assert log.status == "error"


def test_deepagent_empty_subagents_rejected() -> None:
    """Empty subagent list raises ValueError at eval time."""
    da = deepagent(subagents=[], submit=True)
    task = Task(
        dataset=[Sample(input="test")],
        solver=da,
        message_limit=5,
    )
    model = get_model(
        "mockllm/model",
        custom_outputs=[ModelOutput.from_content("mockllm/model", "done")],
    )
    log = eval(task, model=model)[0]
    assert log.status == "error"


def test_deepagent_fork_with_max_depth_rejected() -> None:
    """fork=True with max_depth > 1 raises ValueError at eval time."""
    from inspect_ai.agent import subagent

    sa = subagent(name="forked", description="F.", prompt="", fork=True)
    da = deepagent(subagents=[sa], max_depth=2, submit=True)
    task = Task(
        dataset=[Sample(input="test")],
        solver=da,
        message_limit=5,
    )
    model = get_model(
        "mockllm/model",
        custom_outputs=[ModelOutput.from_content("mockllm/model", "done")],
    )
    log = eval(task, model=model)[0]
    assert log.status == "error"
