import pytest

from inspect_ai.agent import Subagent, subagent


class TestSubagentDefaults:
    def test_required_fields_only(self) -> None:
        s = subagent(name="test", description="A test agent.", prompt="Do the thing.")
        assert s.name == "test"
        assert s.description == "A test agent."
        assert s.prompt == "Do the thing."
        assert s.tools is None
        assert s.extra_tools is None
        assert s.model is None
        assert s.fork is False
        assert s.skills is None
        assert s.memory == "readonly"
        assert s.limits is None

    def test_isinstance_subagent(self) -> None:
        s = subagent(name="test", description="desc", prompt="prompt")
        assert isinstance(s, Subagent)


class TestSubagentAllFields:
    def test_all_fields_set(self) -> None:
        s = subagent(
            name="reviewer",
            description="Reviews code.",
            prompt="Review carefully.",
            tools=[],
            extra_tools=[],
            model="anthropic/claude-sonnet-4",
            fork=True,
            skills=[],
            memory="readwrite",
            limits=[],
        )
        assert s.name == "reviewer"
        assert s.description == "Reviews code."
        assert s.prompt == "Review carefully."
        assert s.tools == []
        assert s.extra_tools == []
        assert s.model == "anthropic/claude-sonnet-4"
        assert s.fork is True
        assert s.skills == []
        assert s.memory == "readwrite"
        assert s.limits == []


class TestSubagentNameValidation:
    def test_empty_name(self) -> None:
        with pytest.raises(ValueError, match="valid Python identifier"):
            subagent(name="", description="desc", prompt="prompt")

    def test_name_with_spaces(self) -> None:
        with pytest.raises(ValueError, match="valid Python identifier"):
            subagent(name="my agent", description="desc", prompt="prompt")

    def test_name_starts_with_digit(self) -> None:
        with pytest.raises(ValueError, match="valid Python identifier"):
            subagent(name="123start", description="desc", prompt="prompt")

    def test_name_with_hyphens(self) -> None:
        with pytest.raises(ValueError, match="valid Python identifier"):
            subagent(name="my-agent", description="desc", prompt="prompt")

    def test_valid_name_with_underscores(self) -> None:
        s = subagent(name="my_agent_2", description="desc", prompt="prompt")
        assert s.name == "my_agent_2"


class TestSubagentDescriptionValidation:
    def test_empty_description(self) -> None:
        with pytest.raises(ValueError, match="description must not be empty"):
            subagent(name="test", description="", prompt="prompt")


class TestSubagentPromptValidation:
    def test_empty_prompt(self) -> None:
        with pytest.raises(ValueError, match="prompt must not be empty"):
            subagent(name="test", description="desc", prompt="")


class TestSubagentMemoryValidation:
    def test_readwrite(self) -> None:
        s = subagent(name="test", description="desc", prompt="p", memory="readwrite")
        assert s.memory == "readwrite"

    def test_readonly(self) -> None:
        s = subagent(name="test", description="desc", prompt="p", memory="readonly")
        assert s.memory == "readonly"

    def test_false(self) -> None:
        s = subagent(name="test", description="desc", prompt="p", memory=False)
        assert s.memory is False

    def test_true_rejected(self) -> None:
        with pytest.raises(ValueError, match="memory"):
            subagent(name="test", description="desc", prompt="p", memory=True)

    def test_invalid_string_rejected(self) -> None:
        with pytest.raises(ValueError, match="memory"):
            subagent(name="test", description="desc", prompt="p", memory="write")  # type: ignore[arg-type]
