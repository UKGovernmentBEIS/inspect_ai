"""Tests for system prompt assembly."""

from inspect_ai.agent._deepagent.prompt import (
    CORE_BEHAVIOR,
    MEMORY_INSTRUCTIONS,
    MEMORY_ONLY_INSTRUCTIONS,
    PLAN_ONLY_INSTRUCTIONS,
    build_subagent_dispatch,
    build_system_prompt,
    expand_prompt_placeholders,
)
from inspect_ai.agent._deepagent.subagent import subagent


def _test_subagent(name: str = "research", description: str = "Gather info."):
    return subagent(name=name, description=description, prompt="prompt")


class TestBuildSystemPrompt:
    def test_default_includes_core_behavior(self) -> None:
        prompt = build_system_prompt()
        assert CORE_BEHAVIOR in prompt

    def test_with_subagents(self) -> None:
        sas = [_test_subagent("research", "Gather info.")]
        prompt = build_system_prompt(subagents=sas)
        assert "research" in prompt
        assert "Gather info." in prompt
        assert "task tool" in prompt.lower() or "delegate" in prompt.lower()

    def test_without_subagents(self) -> None:
        prompt = build_system_prompt(subagents=None)
        assert "delegate" not in prompt.lower()
        assert "subagent" not in prompt.lower()

    def test_empty_subagents(self) -> None:
        prompt = build_system_prompt(subagents=[])
        assert "delegate" not in prompt.lower()

    def test_with_memory_and_todo_write(self) -> None:
        prompt = build_system_prompt(memory=True, todo_write=True)
        assert "memory" in prompt.lower()
        assert "plan" in prompt.lower()

    def test_with_memory_only(self) -> None:
        prompt = build_system_prompt(memory=True, todo_write=False)
        assert MEMORY_ONLY_INSTRUCTIONS in prompt
        assert MEMORY_INSTRUCTIONS not in prompt

    def test_with_todo_write_only(self) -> None:
        prompt = build_system_prompt(memory=False, todo_write=True)
        assert PLAN_ONLY_INSTRUCTIONS in prompt
        assert MEMORY_INSTRUCTIONS not in prompt

    def test_without_memory_or_todo_write(self) -> None:
        prompt = build_system_prompt(memory=False, todo_write=False)
        assert "memory tool" not in prompt.lower()
        assert "plan tool" not in prompt.lower()

    def test_with_instructions(self) -> None:
        prompt = build_system_prompt(instructions="Focus on security.")
        assert "Focus on security." in prompt
        assert prompt.endswith("Focus on security.")

    def test_instructions_at_end(self) -> None:
        prompt = build_system_prompt(
            subagents=[_test_subagent()],
            instructions="Custom instructions here.",
        )
        assert prompt.index(CORE_BEHAVIOR) < prompt.index("Custom instructions here.")


class TestBuildSubagentDispatch:
    def test_includes_all_subagents(self) -> None:
        sas = [
            _test_subagent("research", "Read-only info gathering."),
            _test_subagent("plan", "Structured planning."),
            _test_subagent("general", "General work."),
        ]
        dispatch = build_subagent_dispatch(sas)
        assert "research" in dispatch
        assert "plan" in dispatch
        assert "general" in dispatch
        assert "Read-only info gathering." in dispatch

    def test_includes_delegation_guidance(self) -> None:
        dispatch = build_subagent_dispatch([_test_subagent()])
        assert "delegate" in dispatch.lower() or "Delegate" in dispatch


class TestExpandPromptPlaceholders:
    def test_all_placeholders(self) -> None:
        template = (
            "CORE:\n{core_behavior}\n\n"
            "DISPATCH:\n{subagent_dispatch}\n\n"
            "MEMORY:\n{memory_instructions}\n\n"
            "USER:\n{instructions}"
        )
        result = expand_prompt_placeholders(
            template,
            subagents=[_test_subagent("research", "Gather info.")],
            memory=True,
            todo_write=True,
            instructions="Be thorough.",
        )
        assert CORE_BEHAVIOR in result
        assert "research" in result
        assert "memory" in result.lower()
        assert "Be thorough." in result

    def test_missing_placeholders_harmless(self) -> None:
        template = "Just a simple prompt with no placeholders."
        result = expand_prompt_placeholders(template)
        assert result == template

    def test_partial_placeholders(self) -> None:
        template = "Start here.\n\n{core_behavior}\n\nEnd here."
        result = expand_prompt_placeholders(template)
        assert "Start here." in result
        assert CORE_BEHAVIOR in result
        assert "End here." in result

    def test_no_subagents_clears_placeholder(self) -> None:
        template = "Before {subagent_dispatch} After"
        result = expand_prompt_placeholders(template, subagents=None)
        assert "Before  After" in result

    def test_no_memory_clears_placeholder(self) -> None:
        template = "Before {memory_instructions} After"
        result = expand_prompt_placeholders(template, memory=False, todo_write=False)
        assert "Before  After" in result


class TestTaskAgnosticPrompts:
    def test_core_behavior_no_code_references(self) -> None:
        assert "codebase" not in CORE_BEHAVIOR.lower()
        assert "code review" not in CORE_BEHAVIOR.lower()
        assert "git" not in CORE_BEHAVIOR.lower()

    def test_memory_instructions_no_code_references(self) -> None:
        assert "codebase" not in MEMORY_INSTRUCTIONS.lower()
        assert "code review" not in MEMORY_INSTRUCTIONS.lower()
