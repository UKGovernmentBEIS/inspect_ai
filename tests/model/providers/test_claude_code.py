"""Tests for Claude Code CLI provider.

Unit tests use mocking to avoid external dependencies.
Integration tests (marked with pytest.mark.integration) require Claude CLI.
"""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from inspect_ai.model import GenerateConfig
from inspect_ai.model._chat_message import (
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageUser,
)
from inspect_ai.model._providers.claude_code import (
    THINKING_LEVELS,
    ClaudeCodeAPI,
    find_claude_cli,
    messages_to_prompt,
)

# =============================================================================
# Helper fixtures
# =============================================================================


@pytest.fixture
def mock_cli_path():
    """Mock find_claude_cli to return a fake path."""
    with patch(
        "inspect_ai.model._providers.claude_code.find_claude_cli",
        return_value="/usr/bin/claude",
    ):
        yield


@pytest.fixture
def sample_json_response():
    """Sample successful JSON response from Claude CLI."""
    return {
        "result": "The answer is 4.",
        "usage": {
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_creation_input_tokens": 10,
            "cache_read_input_tokens": 5,
        },
        "total_cost_usd": 0.001,
        "duration_ms": 1500,
        "session_id": "test-session-123",
    }


# =============================================================================
# find_claude_cli() tests
# =============================================================================


def test_find_claude_cli_from_path():
    """Test CLI discovery via PATH lookup."""
    with patch("shutil.which", return_value="/usr/local/bin/claude"):
        assert find_claude_cli() == "/usr/local/bin/claude"


def test_find_claude_cli_from_env_var_full_path():
    """Test CLI discovery via CLAUDE_CODE_COMMAND env var with full path."""
    with (
        patch.dict("os.environ", {"CLAUDE_CODE_COMMAND": "/custom/path/claude"}),
        patch("os.path.isfile", return_value=True),
    ):
        assert find_claude_cli() == "/custom/path/claude"


def test_find_claude_cli_from_env_var_command_name():
    """Test CLI discovery via CLAUDE_CODE_COMMAND env var with command name."""
    with (
        patch.dict("os.environ", {"CLAUDE_CODE_COMMAND": "my-claude"}),
        patch("os.path.isfile", return_value=False),
        patch("shutil.which", return_value="/usr/bin/my-claude"),
    ):
        assert find_claude_cli() == "/usr/bin/my-claude"


def test_find_claude_cli_not_found():
    """Test error when CLI is not found anywhere."""
    with (
        patch.dict("os.environ", {}, clear=True),
        patch("shutil.which", return_value=None),
    ):
        with pytest.raises(RuntimeError, match="Claude Code CLI not found"):
            find_claude_cli()


# =============================================================================
# messages_to_prompt() tests
# =============================================================================


def test_messages_to_prompt_basic():
    """Test conversion of multiple message types to prompt string."""
    messages = [
        ChatMessageSystem(content="You are a helpful assistant."),
        ChatMessageUser(content="Hello"),
        ChatMessageAssistant(content="Hi there!", model="test", source="generate"),
    ]

    prompt = messages_to_prompt(messages)

    assert "[System]: You are a helpful assistant." in prompt
    assert "[User]: Hello" in prompt
    assert "[Assistant]: Hi there!" in prompt


def test_messages_to_prompt_single_message():
    """Test conversion of a single message."""
    messages = [ChatMessageUser(content="What is 2+2?")]

    prompt = messages_to_prompt(messages)

    assert prompt == "[User]: What is 2+2?"


def test_messages_to_prompt_empty_list():
    """Test conversion of empty message list."""
    assert messages_to_prompt([]) == ""


# =============================================================================
# THINKING_LEVELS constant tests
# =============================================================================


def test_thinking_levels_contains_all_expected_keys():
    """Test that all expected thinking levels are defined."""
    assert set(THINKING_LEVELS.keys()) == {"none", "think", "megathink", "ultrathink"}


def test_thinking_levels_magic_words():
    """Test that thinking level magic words are correct."""
    assert THINKING_LEVELS["none"] == ""
    assert THINKING_LEVELS["think"] == "think"
    assert THINKING_LEVELS["megathink"] == "megathink"
    assert THINKING_LEVELS["ultrathink"] == "ultrathink"


# =============================================================================
# ClaudeCodeAPI.__init__() tests
# =============================================================================


def test_init_default_model(mock_cli_path):
    """Test that 'default' model name results in None model arg."""
    api = ClaudeCodeAPI(model_name="default")
    assert api._model_arg is None


def test_init_alias_model(mock_cli_path):
    """Test that alias model names are passed through."""
    api = ClaudeCodeAPI(model_name="sonnet")
    assert api._model_arg == "sonnet"


def test_init_full_model_id(mock_cli_path):
    """Test that full model IDs are passed through."""
    api = ClaudeCodeAPI(model_name="claude-sonnet-4-5-20250929")
    assert api._model_arg == "claude-sonnet-4-5-20250929"


def test_init_default_values(mock_cli_path):
    """Test default parameter values."""
    api = ClaudeCodeAPI(model_name="sonnet")

    assert api._skip_permissions is True
    assert api._timeout == 300
    assert api._max_connections == 1
    assert api._thinking_level == ""


def test_init_custom_values(mock_cli_path):
    """Test custom parameter values."""
    api = ClaudeCodeAPI(
        model_name="opus",
        skip_permissions=False,
        timeout=600,
        max_connections=5,
        thinking_level="ultrathink",
    )

    assert api._skip_permissions is False
    assert api._timeout == 600
    assert api._max_connections == 5
    assert api._thinking_level == "ultrathink"


def test_init_invalid_thinking_level(mock_cli_path):
    """Test that invalid thinking level raises ValueError."""
    with pytest.raises(ValueError, match="Invalid thinking_level"):
        ClaudeCodeAPI(model_name="sonnet", thinking_level="invalid")


def test_init_case_insensitive_default(mock_cli_path):
    """Test that 'DEFAULT' (uppercase) is treated as default."""
    api = ClaudeCodeAPI(model_name="DEFAULT")
    assert api._model_arg is None


# =============================================================================
# ClaudeCodeAPI.max_connections() tests
# =============================================================================


def test_max_connections_returns_configured_value(mock_cli_path):
    """Test that max_connections returns the configured value."""
    api = ClaudeCodeAPI(model_name="sonnet", max_connections=10)
    assert api.max_connections() == 10


# =============================================================================
# ClaudeCodeAPI.generate() tests
# =============================================================================


@pytest.mark.anyio
async def test_generate_raises_on_tools(mock_cli_path):
    """Test that generate raises NotImplementedError when tools are provided."""
    api = ClaudeCodeAPI(model_name="sonnet")

    with pytest.raises(NotImplementedError, match="does not support custom tools"):
        await api.generate(
            input=[ChatMessageUser(content="Hello")],
            tools=[MagicMock()],  # Non-empty tools list
            tool_choice="auto",
            config=GenerateConfig(),
        )


@pytest.mark.anyio
async def test_generate_builds_correct_command(mock_cli_path):
    """Test that generate builds the correct CLI command."""
    api = ClaudeCodeAPI(model_name="sonnet")

    with patch.object(api, "_run_cli") as mock_run:
        mock_run.return_value = MagicMock()

        await api.generate(
            input=[ChatMessageUser(content="Hello")],
            tools=[],
            tool_choice="auto",
            config=GenerateConfig(),
        )

        # Check the command was built correctly
        call_args = mock_run.call_args[0]
        cmd = call_args[0]

        assert "/usr/bin/claude" in cmd[0]
        assert "-p" in cmd
        assert "--output-format" in cmd
        assert "json" in cmd
        assert "--tools" in cmd
        assert "" in cmd  # Empty tools
        assert "--model" in cmd
        assert "sonnet" in cmd
        assert "--dangerously-skip-permissions" in cmd


@pytest.mark.anyio
async def test_generate_prepends_thinking_level(mock_cli_path):
    """Test that thinking level is prepended to prompt."""
    api = ClaudeCodeAPI(model_name="sonnet", thinking_level="ultrathink")

    with patch.object(api, "_run_cli") as mock_run:
        mock_run.return_value = MagicMock()

        await api.generate(
            input=[ChatMessageUser(content="Hello")],
            tools=[],
            tool_choice="auto",
            config=GenerateConfig(),
        )

        cmd = mock_run.call_args[0][0]
        prompt_idx = cmd.index("-p") + 1
        prompt = cmd[prompt_idx]

        assert prompt.startswith("ultrathink\n\n")


@pytest.mark.anyio
async def test_generate_omits_model_flag_for_default(mock_cli_path):
    """Test that --model flag is omitted when using default."""
    api = ClaudeCodeAPI(model_name="default")

    with patch.object(api, "_run_cli") as mock_run:
        mock_run.return_value = MagicMock()

        await api.generate(
            input=[ChatMessageUser(content="Hello")],
            tools=[],
            tool_choice="auto",
            config=GenerateConfig(),
        )

        cmd = mock_run.call_args[0][0]
        assert "--model" not in cmd


# =============================================================================
# End-to-end tests (generate with mocked subprocess)
# =============================================================================


@pytest.mark.anyio
async def test_e2e_successful_generation(mock_cli_path, sample_json_response):
    """End-to-end: successful generation through full pipeline."""
    import json

    api = ClaudeCodeAPI(model_name="sonnet")

    with patch(
        "inspect_ai.model._providers.claude_code.subprocess.run"
    ) as mock_subprocess:
        mock_subprocess.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps(sample_json_response),
            stderr="",
        )

        result = await api.generate(
            input=[
                ChatMessageSystem(content="You are helpful."),
                ChatMessageUser(content="What is 2+2?"),
            ],
            tools=[],
            tool_choice="auto",
            config=GenerateConfig(),
        )

        # Verify the full response
        assert result.error is None
        assert result.choices[0].message.content == "The answer is 4."
        assert result.choices[0].stop_reason == "stop"
        assert result.usage.input_tokens == 100
        assert result.usage.output_tokens == 50
        assert result.metadata["cost_usd"] == 0.001
        assert result.metadata["session_id"] == "test-session-123"

        # Verify subprocess was called correctly
        call_args = mock_subprocess.call_args
        cmd = call_args[0][0]
        assert "-p" in cmd
        assert "--output-format" in cmd
        assert "--model" in cmd
        assert "sonnet" in cmd


@pytest.mark.anyio
async def test_e2e_cli_error_propagates(mock_cli_path):
    """End-to-end: CLI error is properly propagated through pipeline."""
    api = ClaudeCodeAPI(model_name="sonnet")

    with patch(
        "inspect_ai.model._providers.claude_code.subprocess.run"
    ) as mock_subprocess:
        mock_subprocess.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="Rate limit exceeded",
        )

        result = await api.generate(
            input=[ChatMessageUser(content="Hello")],
            tools=[],
            tool_choice="auto",
            config=GenerateConfig(),
        )

        assert result.error is not None
        assert "Rate limit exceeded" in result.error
        assert result.choices[0].stop_reason == "unknown"


@pytest.mark.anyio
async def test_e2e_timeout_handling(mock_cli_path):
    """End-to-end: timeout is properly handled through pipeline."""
    api = ClaudeCodeAPI(model_name="sonnet", timeout=10)

    with patch(
        "inspect_ai.model._providers.claude_code.subprocess.run"
    ) as mock_subprocess:
        mock_subprocess.side_effect = subprocess.TimeoutExpired(
            cmd="claude", timeout=10
        )

        result = await api.generate(
            input=[ChatMessageUser(content="Hello")],
            tools=[],
            tool_choice="auto",
            config=GenerateConfig(),
        )

        assert result.error is not None
        assert "timed out" in result.error


@pytest.mark.anyio
async def test_e2e_with_thinking_level(mock_cli_path, sample_json_response):
    """End-to-end: thinking level is prepended to prompt."""
    import json

    api = ClaudeCodeAPI(model_name="sonnet", thinking_level="ultrathink")

    with patch(
        "inspect_ai.model._providers.claude_code.subprocess.run"
    ) as mock_subprocess:
        mock_subprocess.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps(sample_json_response),
            stderr="",
        )

        await api.generate(
            input=[ChatMessageUser(content="Solve this problem")],
            tools=[],
            tool_choice="auto",
            config=GenerateConfig(),
        )

        # Verify prompt has thinking level prepended
        cmd = mock_subprocess.call_args[0][0]
        prompt_idx = cmd.index("-p") + 1
        prompt = cmd[prompt_idx]
        assert prompt.startswith("ultrathink\n\n")
        assert "[User]: Solve this problem" in prompt


@pytest.mark.anyio
async def test_e2e_error_response_from_api(mock_cli_path):
    """End-to-end: API error in JSON response is extracted."""
    import json

    api = ClaudeCodeAPI(model_name="sonnet")

    error_response = {
        "is_error": True,
        "result": "Model overloaded, please retry",
        "usage": {"input_tokens": 0, "output_tokens": 0},
    }

    with patch(
        "inspect_ai.model._providers.claude_code.subprocess.run"
    ) as mock_subprocess:
        mock_subprocess.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps(error_response),
            stderr="",
        )

        result = await api.generate(
            input=[ChatMessageUser(content="Hello")],
            tools=[],
            tool_choice="auto",
            config=GenerateConfig(),
        )

        assert result.error == "Model overloaded, please retry"
        assert result.choices[0].stop_reason == "unknown"


# =============================================================================
# ClaudeCodeAPI._run_cli() tests
# =============================================================================


def test_run_cli_success(mock_cli_path, sample_json_response):
    """Test successful CLI execution."""
    import json

    api = ClaudeCodeAPI(model_name="sonnet")

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps(sample_json_response),
            stderr="",
        )

        result = api._run_cli(["/usr/bin/claude", "-p", "test"], 300)

        assert result.error is None
        assert "4" in result.choices[0].message.content
        assert result.usage.input_tokens == 100
        assert result.usage.output_tokens == 50


def test_run_cli_timeout(mock_cli_path):
    """Test CLI timeout handling."""
    api = ClaudeCodeAPI(model_name="sonnet")

    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="claude", timeout=300)

        result = api._run_cli(["/usr/bin/claude", "-p", "test"], 300)

        assert result.error is not None
        assert "timed out" in result.error


def test_run_cli_not_found(mock_cli_path):
    """Test CLI not found handling."""
    api = ClaudeCodeAPI(model_name="sonnet")

    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = FileNotFoundError()

        result = api._run_cli(["/usr/bin/claude", "-p", "test"], 300)

        assert result.error is not None
        assert "not found" in result.error


def test_run_cli_nonzero_exit(mock_cli_path):
    """Test non-zero exit code handling."""
    api = ClaudeCodeAPI(model_name="sonnet")

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout="",
            stderr="Authentication failed",
        )

        result = api._run_cli(["/usr/bin/claude", "-p", "test"], 300)

        assert result.error is not None
        assert "Authentication failed" in result.error


def test_run_cli_generic_exception(mock_cli_path):
    """Test generic exception handling."""
    api = ClaudeCodeAPI(model_name="sonnet")

    with patch("subprocess.run") as mock_run:
        mock_run.side_effect = OSError("Permission denied")

        result = api._run_cli(["/usr/bin/claude", "-p", "test"], 300)

        assert result.error is not None
        assert "Permission denied" in result.error


# =============================================================================
# ClaudeCodeAPI._parse_json_response() tests
# =============================================================================


def test_parse_json_response_success(mock_cli_path, sample_json_response):
    """Test successful JSON parsing."""
    import json

    api = ClaudeCodeAPI(model_name="sonnet")
    result = api._parse_json_response(json.dumps(sample_json_response))

    assert result.choices[0].message.content == "The answer is 4."
    assert result.usage.input_tokens == 100
    assert result.usage.output_tokens == 50
    assert result.metadata["cost_usd"] == 0.001
    assert result.metadata["session_id"] == "test-session-123"


def test_parse_json_response_empty(mock_cli_path):
    """Test empty response handling."""
    api = ClaudeCodeAPI(model_name="sonnet")
    result = api._parse_json_response("")

    assert result.error is not None
    assert "Empty response" in result.error


def test_parse_json_response_invalid_json(mock_cli_path):
    """Test invalid JSON handling."""
    api = ClaudeCodeAPI(model_name="sonnet")
    result = api._parse_json_response("not valid json {{{")

    assert result.error is not None
    assert "Failed to parse" in result.error


def test_parse_json_response_with_error_flag(mock_cli_path):
    """Test response with is_error flag."""
    import json

    api = ClaudeCodeAPI(model_name="sonnet")
    error_response = {"is_error": True, "result": "Rate limit exceeded"}
    result = api._parse_json_response(json.dumps(error_response))

    assert result.error == "Rate limit exceeded"


def test_parse_json_response_with_error_type(mock_cli_path):
    """Test response with type: error."""
    import json

    api = ClaudeCodeAPI(model_name="sonnet")
    error_response = {"type": "error", "message": "Invalid model"}
    result = api._parse_json_response(json.dumps(error_response))

    assert result.error == "Invalid model"


# =============================================================================
# ClaudeCodeAPI._extract_content() tests
# =============================================================================


def test_extract_content_from_result_field(mock_cli_path):
    """Test content extraction from 'result' field."""
    api = ClaudeCodeAPI(model_name="sonnet")
    assert api._extract_content({"result": "Hello"}) == "Hello"


def test_extract_content_from_content_field(mock_cli_path):
    """Test content extraction from 'content' field when no 'result'."""
    api = ClaudeCodeAPI(model_name="sonnet")
    assert api._extract_content({"content": "Hello"}) == "Hello"


def test_extract_content_from_text_field(mock_cli_path):
    """Test content extraction from 'text' field when no 'result' or 'content'."""
    api = ClaudeCodeAPI(model_name="sonnet")
    assert api._extract_content({"text": "Hello"}) == "Hello"


def test_extract_content_priority_order(mock_cli_path):
    """Test that 'result' takes priority over 'content' and 'text'."""
    api = ClaudeCodeAPI(model_name="sonnet")
    data = {"result": "from_result", "content": "from_content", "text": "from_text"}
    assert api._extract_content(data) == "from_result"


def test_extract_content_from_string(mock_cli_path):
    """Test content extraction when data is a string."""
    api = ClaudeCodeAPI(model_name="sonnet")
    assert api._extract_content("plain string") == "plain string"


def test_extract_content_empty_dict(mock_cli_path):
    """Test content extraction from empty dict."""
    api = ClaudeCodeAPI(model_name="sonnet")
    assert api._extract_content({}) == ""


def test_extract_content_non_dict_non_string(mock_cli_path):
    """Test content extraction from non-dict, non-string type."""
    api = ClaudeCodeAPI(model_name="sonnet")
    assert api._extract_content(123) == ""
    assert api._extract_content(None) == ""
    assert api._extract_content([]) == ""


# =============================================================================
# ClaudeCodeAPI._extract_usage() tests
# =============================================================================


def test_extract_usage_full(mock_cli_path):
    """Test full usage extraction."""
    api = ClaudeCodeAPI(model_name="sonnet")
    data = {
        "usage": {
            "input_tokens": 100,
            "output_tokens": 50,
            "cache_creation_input_tokens": 10,
            "cache_read_input_tokens": 5,
        }
    }

    assert api._extract_usage(data) == {
        "input": 100,
        "output": 50,
        "cache_creation": 10,
        "cache_read": 5,
        "total": 160,
    }


def test_extract_usage_minimal(mock_cli_path):
    """Test usage extraction with only required fields."""
    api = ClaudeCodeAPI(model_name="sonnet")
    data = {"usage": {"input_tokens": 50, "output_tokens": 25}}

    assert api._extract_usage(data) == {
        "input": 50,
        "output": 25,
        "cache_creation": 0,
        "cache_read": 0,
        "total": 75,
    }


def test_extract_usage_missing_usage_field(mock_cli_path):
    """Test usage extraction when 'usage' field is missing."""
    api = ClaudeCodeAPI(model_name="sonnet")

    assert api._extract_usage({}) == {
        "input": 0,
        "output": 0,
        "cache_creation": 0,
        "cache_read": 0,
        "total": 0,
    }


def test_extract_usage_non_dict(mock_cli_path):
    """Test usage extraction from non-dict data."""
    api = ClaudeCodeAPI(model_name="sonnet")

    assert api._extract_usage("not a dict") == {
        "input": 0,
        "output": 0,
        "cache_creation": 0,
        "cache_read": 0,
        "total": 0,
    }


# =============================================================================
# ClaudeCodeAPI._extract_metadata() tests
# =============================================================================


def test_extract_metadata_full(mock_cli_path):
    """Test full metadata extraction."""
    api = ClaudeCodeAPI(model_name="sonnet")
    data = {
        "total_cost_usd": 0.005,
        "duration_ms": 2000,
        "duration_api_ms": 1800,
        "session_id": "abc-123",
    }
    usage = {"cache_creation": 10, "cache_read": 5}

    assert api._extract_metadata(data, usage) == {
        "cost_usd": 0.005,
        "duration_ms": 2000,
        "duration_api_ms": 1800,
        "session_id": "abc-123",
        "cache_creation_input_tokens": 10,
        "cache_read_input_tokens": 5,
    }


def test_extract_metadata_minimal(mock_cli_path):
    """Test metadata extraction with no optional fields."""
    api = ClaudeCodeAPI(model_name="sonnet")
    metadata = api._extract_metadata({}, {"cache_creation": 0, "cache_read": 0})

    assert metadata is None


def test_extract_metadata_partial(mock_cli_path):
    """Test metadata extraction with only some fields."""
    api = ClaudeCodeAPI(model_name="sonnet")
    data = {"total_cost_usd": 0.001}
    usage = {"cache_creation": 0, "cache_read": 0}

    metadata = api._extract_metadata(data, usage)

    assert metadata == {"cost_usd": 0.001}


def test_extract_metadata_non_dict(mock_cli_path):
    """Test metadata extraction from non-dict data."""
    api = ClaudeCodeAPI(model_name="sonnet")
    assert api._extract_metadata("not a dict", {}) is None


# =============================================================================
# ClaudeCodeAPI._extract_error() tests
# =============================================================================


def test_extract_error_is_error_true(mock_cli_path):
    """Test error extraction when is_error is True."""
    api = ClaudeCodeAPI(model_name="sonnet")
    assert api._extract_error({"is_error": True, "result": "Error msg"}) == "Error msg"


def test_extract_error_type_error(mock_cli_path):
    """Test error extraction when type is 'error'."""
    api = ClaudeCodeAPI(model_name="sonnet")
    assert api._extract_error({"type": "error", "message": "Error msg"}) == "Error msg"


def test_extract_error_type_error_with_result(mock_cli_path):
    """Test error extraction prefers 'result' over 'message' for type error."""
    api = ClaudeCodeAPI(model_name="sonnet")
    data = {"type": "error", "result": "from_result", "message": "from_message"}
    assert api._extract_error(data) == "from_result"


def test_extract_error_no_error(mock_cli_path):
    """Test error extraction returns None for non-error response."""
    api = ClaudeCodeAPI(model_name="sonnet")
    assert api._extract_error({"result": "Success"}) is None


def test_extract_error_non_dict(mock_cli_path):
    """Test error extraction from non-dict data."""
    api = ClaudeCodeAPI(model_name="sonnet")
    assert api._extract_error("not a dict") is None
