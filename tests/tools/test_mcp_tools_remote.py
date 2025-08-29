import pytest
from test_helpers.utils import (
    skip_if_no_anthropic,
    skip_if_no_google,
    skip_if_no_openai,
)

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.model import ContentToolUse
from inspect_ai.solver import generate, use_tools
from inspect_ai.tool import mcp_server_http


@skip_if_no_openai
@pytest.mark.flaky
def test_openai_remote_mcp() -> None:
    check_remote_mcp("openai/gpt-4o")


@skip_if_no_anthropic
@pytest.mark.flaky
def test_anthropic_remote_mcp() -> None:
    # This test is flaky because, sometimes, the model gets confused and does not
    # make do a remote tool use.
    check_remote_mcp("anthropic/claude-3-7-sonnet-latest")


@skip_if_no_google
def test_google_remote_mcp() -> None:
    with pytest.raises(RuntimeError, match="Remote MCP"):
        check_remote_mcp("google/gemini-2.0-flash", debug_errors=True)


def check_remote_mcp(model: str, debug_errors: bool = False) -> None:
    deepwiki = mcp_server_http(
        name="deepwiki", url="https://mcp.deepwiki.com/mcp", execution="remote"
    )

    task = Task(
        dataset=[
            Sample(
                input="What transport protocols are supported in the 2025-03-26 version of the MCP spec?",
            )
        ],
        solver=[use_tools(deepwiki), generate()],
    )

    log = eval(task, model=model, debug_errors=debug_errors)[0]
    assert log.status == "success"
    assert log.samples
    content = log.samples[0].output.message.content
    assert isinstance(content, list)
    assert any(isinstance(c, ContentToolUse) for c in content)
