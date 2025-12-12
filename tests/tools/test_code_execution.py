import pytest
from test_helpers.utils import (
    skip_if_no_anthropic,
    skip_if_no_docker,
    skip_if_no_google,
    skip_if_no_grok,
    skip_if_no_mistral,
    skip_if_no_openai,
)

from inspect_ai import Task, eval, task
from inspect_ai._util.content import ContentToolUse
from inspect_ai.dataset import Sample
from inspect_ai.event._tool import ToolEvent
from inspect_ai.solver import generate, use_tools, user_message
from inspect_ai.tool import code_execution
from inspect_ai.tool._tools._code_execution import (
    CodeExecutionProviders,
    _normalize_config,
)


@task
def code_execution_task(providers: CodeExecutionProviders | None = None):
    return Task(
        dataset=[
            Sample(
                "Please use your available tools to execute Python code that adds 435678 + 23457 and then prints the result."
            )
        ],
        solver=[
            use_tools(code_execution(providers=providers)),
            generate(),
            user_message(
                "Now, use your available tools to execute Python code that adds 34125 and 98267 and prints the result."
            ),
            generate(),
        ],
    )


def check_code_execution(model: str, sandbox: str | None = None) -> None:
    log = eval(code_execution_task(), model=model, sandbox=sandbox)[0]
    assert log.status == "success"

    assert log.samples
    output = log.samples[0].output
    assert isinstance(output.message.content, list)
    tool_use = next(
        (c for c in output.message.content if isinstance(c, ContentToolUse)), None
    )
    assert tool_use
    assert tool_use.tool_type == "code_execution"


def check_python_code_execution(provider: str, model: str) -> None:
    log = eval(
        code_execution_task(providers=CodeExecutionProviders({provider: False})),  # type: ignore[misc]
        model=f"{provider}/{model}",
        sandbox="docker",
    )[0]
    assert log.status == "success"
    assert log.samples
    tool_events = [ev for ev in log.samples[0].events if isinstance(ev, ToolEvent)]
    assert len(tool_events) == 2
    assert all(ev.function == "code_execution" for ev in tool_events)


@skip_if_no_grok
def test_grok_code_execution() -> None:
    check_code_execution("grok/grok-4-fast")


@pytest.mark.slow
@skip_if_no_grok
@skip_if_no_docker
def test_grok_code_execution_python() -> None:
    check_python_code_execution("grok", "grok-4-fast")


@skip_if_no_mistral
def test_mistral_code_execution() -> None:
    check_code_execution("mistral/mistral-large-latest")


@pytest.mark.slow
@skip_if_no_mistral
@skip_if_no_docker
def test_mistral_code_execution_python() -> None:
    check_python_code_execution("mistral", "mistral-large-latest")


@skip_if_no_google
def test_google_code_execution() -> None:
    check_code_execution("google/gemini-3-pro-preview")


@pytest.mark.slow
@skip_if_no_google
@skip_if_no_docker
def test_google_code_execution_python() -> None:
    check_python_code_execution("google", "gemini-2.5-flash")


@skip_if_no_openai
def test_openai_code_execution() -> None:
    check_code_execution("openai/gpt-5-mini")


@pytest.mark.slow
@skip_if_no_openai
@skip_if_no_docker
def test_openai_code_execution_python() -> None:
    check_python_code_execution("openai", "gpt-5-mini")


@skip_if_no_anthropic
def test_anthropic_code_execution() -> None:
    check_code_execution("anthropic/claude-sonnet-4-5")


@pytest.mark.slow
@skip_if_no_anthropic
@skip_if_no_docker
def test_anthropic_code_execution_python() -> None:
    check_python_code_execution("anthropic", "claude-sonnet-4-5")


def test_normalize_config_default_all_providers_enabled() -> None:
    """Test that None input enables all providers with empty dicts."""
    result = _normalize_config(None)

    assert "openai" in result
    assert "anthropic" in result
    assert "google" in result
    assert "grok" in result
    assert "python" in result

    assert result["openai"] == {}
    assert result["anthropic"] == {}
    assert result["google"] == {}
    assert result["grok"] == {}
    assert result["python"] == {}


def test_normalize_config_empty_dict_same_as_none() -> None:
    """Test that empty dict input is equivalent to None."""
    result = _normalize_config({})
    assert result == _normalize_config(None)


def test_normalize_config_disable_single_provider() -> None:
    """Test that False removes a provider from the result."""
    result = _normalize_config({"python": False})

    assert "python" not in result
    assert "openai" in result
    assert "anthropic" in result
    assert "google" in result
    assert "grok" in result


def test_normalize_config_disable_multiple_providers() -> None:
    """Test disabling multiple providers."""
    result = _normalize_config({"grok": False, "openai": False})

    assert "grok" not in result
    assert "openai" not in result
    assert "anthropic" in result
    assert "google" in result
    assert "python" in result


def test_normalize_config_disable_all_providers() -> None:
    """Test disabling all providers results in empty dict."""
    result = _normalize_config(
        {
            "openai": False,
            "anthropic": False,
            "google": False,
            "grok": False,
            "mistral": False,
            "python": False,
        }
    )
    assert result == {}


def test_normalize_config_dict_options_for_openai() -> None:
    """Test providing dict options for openai."""
    options = {"memory_limit": "4g", "timeout": 300}
    result = _normalize_config({"openai": options})

    assert result["openai"] == options
    assert result["anthropic"] == {}
    assert result["google"] == {}
    assert result["grok"] == {}
    assert result["python"] == {}


def test_normalize_config_dict_options_for_python() -> None:
    """Test providing dict options for python."""
    options = {"timeout": 60, "sandbox": "foo"}
    result = _normalize_config({"python": options})

    assert result["python"] == options
    assert result["openai"] == {}


def test_normalize_config_true_leaves_provider_enabled() -> None:
    """Test that True keeps the provider enabled with empty dict."""
    result = _normalize_config({"openai": True, "anthropic": True})

    assert result["openai"] == {}
    assert result["anthropic"] == {}


def test_normalize_config_mixed_configuration() -> None:
    """Test mixed configuration with dict, True, and False values."""
    result = _normalize_config(
        {
            "openai": {"memory_limit": "8g"},
            "anthropic": True,
            "grok": False,
            "python": {"timeout": 120},
        }
    )

    assert result["openai"] == {"memory_limit": "8g"}
    assert result["anthropic"] == {}
    assert "grok" not in result
    assert result["google"] == {}
    assert result["python"] == {"timeout": 120}


def test_normalize_config_empty_dict_options() -> None:
    """Test that providing an empty dict keeps provider enabled."""
    result = _normalize_config({"openai": {}})

    assert result["openai"] == {}
    assert "openai" in result


@pytest.mark.parametrize(
    "provider", ["openai", "anthropic", "google", "grok", "python"]
)
def test_normalize_config_disable_each_provider(provider: str) -> None:
    """Test that each provider can be individually disabled."""
    result = _normalize_config({provider: False})  # type: ignore[arg-type, misc]

    assert provider not in result
    all_providers = {"openai", "anthropic", "google", "grok", "python"}
    for other in all_providers - {provider}:
        assert other in result
