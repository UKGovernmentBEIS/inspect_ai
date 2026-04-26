"""Tests for built-in subagent factories (research, plan, general)."""

from inspect_ai.agent import Subagent, general, plan, research
from inspect_ai.tool import think


class TestResearchDefaults:
    def test_returns_subagent(self) -> None:
        sa = research()
        assert isinstance(sa, Subagent)

    def test_name(self) -> None:
        assert research().name == "research"

    def test_default_tools_is_none(self) -> None:
        assert research().tools is None

    def test_default_memory(self) -> None:
        assert research().memory == "readonly"

    def test_default_fork(self) -> None:
        assert research().fork is False

    def test_prompt_not_empty(self) -> None:
        assert len(research().prompt) > 0


class TestPlanDefaults:
    def test_returns_subagent(self) -> None:
        sa = plan()
        assert isinstance(sa, Subagent)

    def test_name(self) -> None:
        assert plan().name == "plan"

    def test_default_tools_is_none(self) -> None:
        assert plan().tools is None

    def test_default_memory(self) -> None:
        assert plan().memory == "readonly"

    def test_default_fork(self) -> None:
        assert plan().fork is False

    def test_prompt_not_empty(self) -> None:
        assert len(plan().prompt) > 0


class TestGeneralDefaults:
    def test_returns_subagent(self) -> None:
        sa = general()
        assert isinstance(sa, Subagent)

    def test_name(self) -> None:
        assert general().name == "general"

    def test_default_tools_is_none(self) -> None:
        assert general().tools is None

    def test_default_memory(self) -> None:
        assert general().memory == "readwrite"

    def test_default_fork(self) -> None:
        assert general().fork is False

    def test_prompt_not_empty(self) -> None:
        assert len(general().prompt) > 0


class TestInstructionsMerge:
    def test_research_instructions(self) -> None:
        sa = research(instructions="Focus on security vulnerabilities.")
        assert "Focus on security vulnerabilities." in sa.prompt
        assert "research agent" in sa.prompt.lower()

    def test_plan_instructions(self) -> None:
        sa = plan(instructions="Consider performance constraints.")
        assert "Consider performance constraints." in sa.prompt
        assert "planning agent" in sa.prompt.lower()

    def test_general_instructions(self) -> None:
        sa = general(instructions="Be thorough.")
        assert "Be thorough." in sa.prompt
        assert "general-purpose agent" in sa.prompt.lower()


class TestCustomTools:
    def test_tools_replace_defaults(self) -> None:
        custom = [think()]
        sa = research(tools=custom)
        assert sa.tools is not None
        assert len(sa.tools) == 1

    def test_empty_tools(self) -> None:
        sa = research(tools=[])
        assert sa.tools is not None
        assert len(sa.tools) == 0

    def test_extra_tools_added(self) -> None:
        sa = research(extra_tools=[think()])
        assert sa.extra_tools is not None
        assert len(sa.extra_tools) == 1
        assert sa.tools is None  # defaults still None

    def test_tools_and_extra_tools(self) -> None:
        sa = plan(tools=[think()], extra_tools=[think()])
        assert sa.tools is not None
        assert len(sa.tools) == 1
        assert sa.extra_tools is not None
        assert len(sa.extra_tools) == 1


class TestSkills:
    def test_skills_on_research(self) -> None:
        from inspect_ai.tool import Skill

        sk = Skill(name="test-skill", description="A test.", instructions="Do stuff.")
        sa = research(skills=[sk])
        assert sa.skills is not None
        assert len(sa.skills) == 1
        skill = sa.skills[0]
        assert isinstance(skill, Skill)
        assert skill.name == "test-skill"

    def test_skills_on_general(self) -> None:
        from inspect_ai.tool import Skill

        sk = Skill(name="test-skill", description="A test.", instructions="Do stuff.")
        sa = general(skills=[sk])
        assert sa.skills is not None
        assert len(sa.skills) == 1

    def test_skills_default_none(self) -> None:
        assert research().skills is None
        assert plan().skills is None
        assert general().skills is None


class TestOverrides:
    def test_model_override(self) -> None:
        sa = research(model="anthropic/claude-sonnet-4")
        assert sa.model == "anthropic/claude-sonnet-4"

    def test_fork_override(self) -> None:
        sa = research(fork=True)
        assert sa.fork is True

    def test_memory_override(self) -> None:
        sa = research(memory="readwrite")
        assert sa.memory == "readwrite"

    def test_memory_false(self) -> None:
        sa = general(memory=False)
        assert sa.memory is False


class TestTaskAgnosticPrompts:
    def test_research_no_code_references(self) -> None:
        prompt = research().prompt
        assert "codebase" not in prompt.lower()
        assert "code review" not in prompt.lower()

    def test_plan_no_code_references(self) -> None:
        prompt = plan().prompt
        assert "codebase" not in prompt.lower()
        assert "code review" not in prompt.lower()

    def test_general_no_code_references(self) -> None:
        prompt = general().prompt
        assert "codebase" not in prompt.lower()
        assert "code review" not in prompt.lower()
