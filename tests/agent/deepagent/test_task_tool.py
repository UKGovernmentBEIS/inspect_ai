"""Tests for task() multiplexer tool."""

from test_helpers.tool_call_utils import get_tool_event

from inspect_ai import Task, eval
from inspect_ai._util.content import Content, ContentText
from inspect_ai._util.registry import is_registry_object, registry_info
from inspect_ai.agent._deepagent.subagent import Subagent, subagent
from inspect_ai.agent._deepagent.task_tool import (
    _build_task_description,
    _prepare_forked_input,
    _resolve_tools,
    task_tool,
)
from inspect_ai.dataset import Sample
from inspect_ai.model import ModelOutput, get_model
from inspect_ai.model._chat_message import (
    ChatMessage,
    ChatMessageAssistant,
    ChatMessageUser,
)
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
                # 2. Inner subagent (research) submits its findings
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="submit",
                    tool_arguments={"answer": "I found the relevant information."},
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

    def test_general_dispatch(self) -> None:
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
                        "subagent_type": "general",
                        "prompt": "Do general work.",
                    },
                ),
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="submit",
                    tool_arguments={"answer": "Did the work."},
                ),
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

    def test_task_tool_included_when_depth_allows(self) -> None:
        """max_depth=2 at depth=0: child gets task tool (can delegate once)."""
        sa = _test_subagent("research", "Gather info.")
        sas = [sa]
        tools = _resolve_tools(
            sa, sas, None, None, None, depth=0, max_depth=2, get_messages=None
        )
        assert "task" in self._tool_registry_names(tools)

    def test_task_tool_excluded_at_default_depth(self) -> None:
        """max_depth=1 (default) at depth=0: child does NOT get task tool."""
        sa = _test_subagent("research", "Gather info.")
        sas = [sa]
        tools = _resolve_tools(
            sa, sas, None, None, None, depth=0, max_depth=1, get_messages=None
        )
        assert "task" not in self._tool_registry_names(tools)


class TestSkillComposition:
    def _find_skill_tools(self, tools: list) -> list:
        from inspect_ai.tool._tool_def import ToolDef

        result = []
        for t in tools:
            try:
                td = ToolDef(t)
                if td.name == "skill":
                    result.append(td)
            except Exception:
                pass
        return result

    def test_parent_skills_flow_to_subagent(self) -> None:
        from inspect_ai.tool import Skill

        parent_sk = Skill(name="parent-skill", description="P.", instructions="P.")
        sa = _test_subagent("research", "Gather info.")
        sas = [sa]
        tools = _resolve_tools(
            sa, sas, None, None, [parent_sk], depth=0, max_depth=1, get_messages=None
        )
        skill_tools = self._find_skill_tools(tools)
        assert len(skill_tools) == 1
        assert "parent-skill" in skill_tools[0].description

    def test_subagent_skills_merge_with_parent(self) -> None:
        from inspect_ai.tool import Skill

        parent_sk = Skill(name="parent-skill", description="Parent.", instructions="P.")
        child_sk = Skill(name="child-skill", description="Child.", instructions="C.")
        sa = subagent(
            name="custom",
            description="Custom.",
            prompt="Custom.",
            skills=[child_sk],
        )
        sas = [sa]
        tools = _resolve_tools(
            sa, sas, None, None, [parent_sk], depth=0, max_depth=1, get_messages=None
        )
        skill_tools = self._find_skill_tools(tools)
        assert len(skill_tools) == 1
        assert "parent-skill" in skill_tools[0].description
        assert "child-skill" in skill_tools[0].description

    def test_no_skill_tool_when_no_skills(self) -> None:
        sa = _test_subagent("research", "Gather info.")
        sas = [sa]
        tools = _resolve_tools(
            sa, sas, None, None, None, depth=0, max_depth=1, get_messages=None
        )
        skill_tools = self._find_skill_tools(tools)
        assert len(skill_tools) == 0

    def test_duplicate_skill_names_rejected(self) -> None:
        import pytest

        from inspect_ai.agent._deepagent.deepagent import _validate_skill_names
        from inspect_ai.tool import Skill

        parent_sk = Skill(name="pdf", description="Parent PDF.", instructions="P.")
        child_sk = Skill(name="pdf", description="Child PDF.", instructions="C.")
        sa = subagent(
            name="custom",
            description="Custom.",
            prompt="Custom.",
            skills=[child_sk],
        )
        with pytest.raises(ValueError, match="Duplicate skill name"):
            _validate_skill_names([parent_sk], [sa])

    def test_duplicate_across_sibling_subagents_rejected(self) -> None:
        import pytest

        from inspect_ai.agent._deepagent.deepagent import _validate_skill_names
        from inspect_ai.tool import Skill

        sk_a = Skill(name="pdf", description="A.", instructions="A.")
        sk_b = Skill(name="pdf", description="B.", instructions="B.")
        sa_a = subagent(name="agent_a", description="A.", prompt="A.", skills=[sk_a])
        sa_b = subagent(name="agent_b", description="B.", prompt="B.", skills=[sk_b])
        with pytest.raises(ValueError, match="Duplicate skill name"):
            _validate_skill_names(None, [sa_a, sa_b])

    def test_duplicate_in_parent_skills_rejected(self) -> None:
        import pytest

        from inspect_ai.agent._deepagent.deepagent import _validate_skill_names
        from inspect_ai.tool import Skill

        sk1 = Skill(name="pdf", description="First.", instructions="1.")
        sk2 = Skill(name="pdf", description="Second.", instructions="2.")
        with pytest.raises(ValueError, match="Duplicate skill name"):
            _validate_skill_names([sk1, sk2], [])


class TestExtractResult:
    def test_extract_result_with_content_text(self) -> None:
        """_extract_result handles list[ContentText] from providers like Anthropic."""
        from inspect_ai.agent._agent import AgentState
        from inspect_ai.agent._deepagent.task_tool import _extract_result
        from inspect_ai.model._chat_message import ChatMessageAssistant
        from inspect_ai.model._model_output import ChatCompletionChoice, ModelOutput

        content_blocks: list[Content] = [ContentText(text="The answer is 42.")]
        msg = ChatMessageAssistant(content=content_blocks)
        output = ModelOutput(
            model="test",
            choices=[ChatCompletionChoice(message=msg, stop_reason="stop")],
        )
        state = AgentState(messages=[msg])
        state._output = output

        result = _extract_result(state)
        assert result == "The answer is 42."

    def test_extract_result_with_str_content(self) -> None:
        """_extract_result handles plain string content."""
        from inspect_ai.agent._agent import AgentState
        from inspect_ai.agent._deepagent.task_tool import _extract_result
        from inspect_ai.model._chat_message import ChatMessageAssistant

        msg = ChatMessageAssistant(content="Plain string answer.")
        state = AgentState(messages=[msg])

        result = _extract_result(state)
        assert result == "Plain string answer."


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
                # Inner forked agent submits its response
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="submit",
                    tool_arguments={"answer": "Completed forked work."},
                ),
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


class TestPrepareForkedInput:
    def test_keeps_system_messages(self) -> None:
        from inspect_ai.model._chat_message import ChatMessageSystem

        sa = _test_subagent("forked", "Forked agent.")
        messages: list[ChatMessage] = [
            ChatMessageSystem(content="You are helpful."),
            ChatMessageUser(content="Hello", id="msg-1"),
            ChatMessageAssistant(content="Hi there", id="msg-2"),
        ]
        result, from_message = _prepare_forked_input("Do work.", sa, lambda: messages)
        # Branch point is the last parent message before the synthetic prompt
        assert from_message == "msg-1"
        # System message preserved for prompt cache
        sys_msgs = [m for m in result if isinstance(m, ChatMessageSystem)]
        assert len(sys_msgs) == 1
        assert "You are helpful." in str(sys_msgs[0].content)
        # Trailing assistant stripped
        assert not any(isinstance(m, ChatMessageAssistant) for m in result)

    def test_strips_trailing_assistant_keeps_history(self) -> None:
        from inspect_ai.model._chat_message import ChatMessageSystem
        from inspect_ai.tool._tool_call import ToolCall

        sa = _test_subagent("forked", "Forked agent.")
        messages: list[ChatMessage] = [
            ChatMessageSystem(content="System prompt."),
            ChatMessageUser(content="Do two things", id="msg-1"),
            ChatMessageAssistant(
                content="I'll delegate.",
                id="msg-2",
                tool_calls=[
                    ToolCall(
                        id="call-task-1",
                        function="task",
                        arguments={"subagent_type": "forked", "prompt": "x"},
                        type="function",
                    ),
                ],
            ),
        ]
        result, from_message = _prepare_forked_input("Do work.", sa, lambda: messages)
        # Branch point is the user message (assistant was stripped)
        assert from_message == "msg-1"

        # System message preserved
        assert any(isinstance(m, ChatMessageSystem) for m in result)

        # Trailing assistant stripped
        assert not any(isinstance(m, ChatMessageAssistant) for m in result)

        # Original user message preserved
        assert any(
            isinstance(m, ChatMessageUser) and "Do two things" in str(m.content)
            for m in result
        )

    def test_subagent_prompt_prepended_to_task(self) -> None:
        sa = _test_subagent("forked", "Forked agent.")
        messages: list[ChatMessage] = [
            ChatMessageUser(content="Hello", id="msg-1"),
        ]
        result, from_message = _prepare_forked_input(
            "Do the task.", sa, lambda: messages
        )
        assert from_message == "msg-1"
        # Last message is user message with subagent prompt + task prompt
        last = result[-1]
        assert isinstance(last, ChatMessageUser)
        content = str(last.content)
        assert "research assistant" in content.lower()
        assert "Do the task." in content

    def test_empty_prompt_transparent_fork(self) -> None:
        sa = subagent(
            name="transparent",
            description="Transparent fork.",
            prompt="",
            fork=True,
        )
        messages: list[ChatMessage] = [
            ChatMessageUser(content="Hello", id="msg-1"),
        ]
        result, from_message = _prepare_forked_input("Do work.", sa, lambda: messages)
        assert from_message == "msg-1"
        last = result[-1]
        assert isinstance(last, ChatMessageUser)
        # Task prompt present (no prepended sa.prompt since it's empty)
        assert "Do work." in str(last.content)
        # Submit instructions appended
        assert "submit()" in str(last.content)
