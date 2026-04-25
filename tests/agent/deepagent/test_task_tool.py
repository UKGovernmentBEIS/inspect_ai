"""Tests for task() multiplexer tool."""

from test_helpers.tool_call_utils import get_tool_event

from inspect_ai import Task, eval
from inspect_ai._util.registry import is_registry_object, registry_info
from inspect_ai.agent._deepagent.subagent import Subagent, subagent
from inspect_ai.agent._deepagent.task_tool import (
    SUBAGENT_ALIASES,
    _build_task_description,
    _resolve_tools,
    task_tool,
)
from inspect_ai.dataset import Sample
from inspect_ai.model import ModelOutput, get_model
from inspect_ai.solver import generate, use_tools


def _test_subagent(
    name: str = "research", description: str = "Gather info."
) -> Subagent:
    return subagent(
        name=name,
        description=description,
        prompt="You are a helpful research assistant.",
    )


class TestBuildTaskDescription:
    def test_includes_all_subagent_names(self) -> None:
        subagents = [
            _test_subagent("research", "Gather info."),
            _test_subagent("plan", "Make plans."),
            _test_subagent("general", "General work."),
        ]
        desc = _build_task_description(subagents)
        assert "research" in desc
        assert "plan" in desc
        assert "general" in desc
        assert "Gather info." in desc
        assert "Make plans." in desc
        assert "General work." in desc

    def test_includes_delegation_guidance(self) -> None:
        desc = _build_task_description([_test_subagent()])
        assert "Delegate" in desc or "delegate" in desc


class TestAliasHandling:
    def test_general_purpose_alias(self) -> None:
        assert SUBAGENT_ALIASES.get("general_purpose") == "general"


class TestTaskToolConstructibility:
    def test_constructible(self) -> None:
        tool = task_tool(subagents=[_test_subagent()])
        assert tool is not None


class TestTaskToolDispatch:
    def test_via_mockllm(self) -> None:
        sa = _test_subagent("research", "Read-only information gathering.")
        tt = task_tool(subagents=[sa])

        task = Task(
            dataset=[Sample(input="Do some research")],
            solver=[use_tools(tt), generate()],
            message_limit=10,
        )

        model = get_model(
            "mockllm/model",
            custom_outputs=[
                # 1. Outer agent calls task() tool
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="task",
                    tool_arguments={
                        "subagent_type": "research",
                        "prompt": "Find relevant information.",
                    },
                ),
                # 2. Inner subagent (research) generates a response (no tools, so it stops)
                ModelOutput.from_content(
                    "mockllm/model", "I found the relevant information."
                ),
                # 3. Outer agent generates final response
                ModelOutput.from_content("mockllm/model", "Done"),
            ],
        )

        log = eval(task, model=model)[0]
        assert log.status == "success"

        tool_event = get_tool_event(log)
        assert tool_event is not None
        assert tool_event.function == "task"

    def test_invalid_subagent_type(self) -> None:
        sa = _test_subagent("research", "Gather info.")
        tt = task_tool(subagents=[sa])

        task = Task(
            dataset=[Sample(input="Do something")],
            solver=[use_tools(tt), generate()],
            message_limit=10,
        )

        model = get_model(
            "mockllm/model",
            custom_outputs=[
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="task",
                    tool_arguments={
                        "subagent_type": "nonexistent",
                        "prompt": "Do something.",
                    },
                ),
                ModelOutput.from_content("mockllm/model", "Done"),
            ],
        )

        log = eval(task, model=model)[0]
        assert log.status == "success"
        tool_event = get_tool_event(log)
        assert tool_event is not None
        assert tool_event.error is not None
        assert "Unknown subagent_type" in tool_event.error.message

    def test_alias_dispatch(self) -> None:
        sa = _test_subagent("general", "General work.")
        tt = task_tool(subagents=[sa])

        task = Task(
            dataset=[Sample(input="Do work")],
            solver=[use_tools(tt), generate()],
            message_limit=10,
        )

        model = get_model(
            "mockllm/model",
            custom_outputs=[
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="task",
                    tool_arguments={
                        "subagent_type": "general_purpose",
                        "prompt": "Do general work.",
                    },
                ),
                ModelOutput.from_content("mockllm/model", "Did the work."),
                ModelOutput.from_content("mockllm/model", "Done"),
            ],
        )

        log = eval(task, model=model)[0]
        assert log.status == "success"
        tool_event = get_tool_event(log)
        assert tool_event is not None
        assert tool_event.error is None


class TestRecursionGuard:
    def _tool_registry_names(self, tools: list) -> list[str]:
        names = []
        for t in tools:
            if is_registry_object(t):
                name = registry_info(t).name
                names.append(name.split("/")[-1])
        return names

    def test_task_tool_included_below_max_depth(self) -> None:
        sa = _test_subagent("research", "Gather info.")
        sas = [sa]
        tools = _resolve_tools(sa, sas, None, depth=0, max_depth=1, get_messages=None)
        assert "task" in self._tool_registry_names(tools)

    def test_task_tool_excluded_at_max_depth(self) -> None:
        sa = _test_subagent("research", "Gather info.")
        sas = [sa]
        tools = _resolve_tools(sa, sas, None, depth=1, max_depth=1, get_messages=None)
        assert "task" not in self._tool_registry_names(tools)


class TestForkedDispatch:
    def test_forked_via_mockllm(self) -> None:
        from inspect_ai.model._chat_message import ChatMessage, ChatMessageUser

        sa = subagent(
            name="forked_agent",
            description="A forked agent.",
            prompt="You are a forked helper.",
            fork=True,
        )
        parent_messages: list[ChatMessage] = [
            ChatMessageUser(content="Original context.", id="msg-1")
        ]
        tt = task_tool(
            subagents=[sa],
            get_messages=lambda: parent_messages,
        )

        task = Task(
            dataset=[Sample(input="Do work with fork")],
            solver=[use_tools(tt), generate()],
            message_limit=10,
        )

        model = get_model(
            "mockllm/model",
            custom_outputs=[
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="task",
                    tool_arguments={
                        "subagent_type": "forked_agent",
                        "prompt": "Continue the work.",
                    },
                ),
                # Inner forked agent generates a response
                ModelOutput.from_content("mockllm/model", "Completed forked work."),
                # Outer agent finishes
                ModelOutput.from_content("mockllm/model", "Done"),
            ],
        )

        log = eval(task, model=model)[0]
        assert log.status == "success"

        tool_event = get_tool_event(log)
        assert tool_event is not None
        assert tool_event.function == "task"
        assert tool_event.error is None
