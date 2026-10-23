import re
import subprocess
import sys
from itertools import count
from pathlib import Path
from typing import Any, Literal

import pytest
from test_helpers.tool_call_utils import get_tool_call, get_tool_response
from test_helpers.utils import flaky_retry, skip_if_no_docker, skip_if_no_openai

from inspect_ai import Task, eval
from inspect_ai._util.content import ContentText
from inspect_ai._util.error import PrerequisiteError
from inspect_ai.dataset import Sample
from inspect_ai.model import ModelOutput, get_model
from inspect_ai.model._chat_message import ChatMessage, ChatMessageTool
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.solver import generate, use_tools
from inspect_ai.tool import web_browser
from inspect_ai.tool._tool_call import ToolCall
from inspect_ai.tool._tool_choice import ToolChoice
from inspect_ai.tool._tool_def import ToolDef
from inspect_ai.tool._tool_info import ToolInfo
from inspect_ai.tool._tools._web_browser import _web_browser as web_browser_module
from inspect_ai.util import Store, tool_state_instance, tool_state_scope
from inspect_ai.util._store import init_subtask_store


def find_element_id(input: list[ChatMessage], pattern: str) -> int:
    r"""Finds an element id from the accessibility tree in the most recent tool message.

    Args:
        input: The conversation messages.
        pattern: Regex pattern to match after the element id bracket (e.g. r'button\s*"Submit"').

    Returns:
        The integer element id.
    """
    most_recent_message = input[-1]
    assert isinstance(most_recent_message, ChatMessageTool)
    if isinstance(most_recent_message.content, str):
        text = most_recent_message.content
    else:
        at_content = most_recent_message.content[-1]
        assert isinstance(at_content, ContentText)
        text = at_content.text
    match = re.search(rf"\[(\d+)\]\s*{pattern}", text)
    assert match, f"Could not find element matching {pattern} in accessibility tree"
    return int(match.group(1))


def test_web_browser_logs_deprecation_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # deprecation_warning() emits once per call site, so call exactly once here
    tools = web_browser()

    deprecations = [r for r in caplog.records if r.message.startswith("DEPRECATED:")]
    assert len(deprecations) == 1, [r.message for r in caplog.records]
    message = deprecations[0].message
    assert "`web_browser()` tool is deprecated" in message
    assert "https://github.com/UKGovernmentBEIS/inspect_ai/issues/5497" in message
    assert Path(__file__).name in message

    # behaviour is otherwise unchanged: the full tool list is still returned
    assert len(tools) == 8


def test_web_browser_import_does_not_warn() -> None:
    """Importing the symbol (as inspect_evals does at registry load) stays silent."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import logging; logging.basicConfig(level=logging.WARNING); "
            "from inspect_ai.tool import web_browser",
        ],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert "DEPRECATED" not in result.stderr, result.stderr


def _named_tools(tools: list[Any]) -> dict[str, ToolDef]:
    return {ToolDef(t).name: ToolDef(t) for t in tools}


async def test_web_browser_default_instance_is_per_tool_state_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    new_sessions: list[str] = []
    used_sessions: list[tuple[str | None, object]] = []

    class FakeTransport:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

    async def fake_legacy_tool_support_sandbox(*args: Any) -> tuple[object, None]:
        return (object(), None)

    async def fake_exec_model_request(method: str, **kwargs: Any) -> Any:
        if method == "web_new_session":
            new_sessions.append(f"session-{len(new_sessions) + 1}")
            return web_browser_module.NewSessionResult(session_name=new_sessions[-1])
        session = kwargs["params"]["session_name"]
        used_sessions.append((tool_state_instance(None), session))
        return web_browser_module.CrawlerResult(
            web_url="https://example.com",
            web_at=f"[1] RootWebArea {session}\n  [7] button {session}",
        )

    monkeypatch.setattr(
        web_browser_module,
        "legacy_tool_support_sandbox",
        fake_legacy_tool_support_sandbox,
    )
    monkeypatch.setattr(web_browser_module, "SandboxJSONRPCTransport", FakeTransport)
    monkeypatch.setattr(
        web_browser_module, "exec_model_request", fake_exec_model_request
    )

    init_subtask_store(Store())
    tools = _named_tools(web_browser())
    go = tools["web_browser_go"].tool
    click_viewer = tools["web_browser_click"].viewer
    assert click_viewer is not None
    click = ToolCall(id="1", function="web_browser_click", arguments={"element_id": 7})

    for scope in ["w-1", "w-2", "w-1"]:
        with tool_state_scope(scope):
            await go(url="https://example.com")
    with tool_state_scope("w-2"):
        view = click_viewer(click)
        assert view.context is not None and "session-2" in str(view.context.content)
    with tool_state_scope("w-3"):
        assert click_viewer(click).context is None

    assert new_sessions == ["session-1", "session-2"]
    assert used_sessions == [
        ("@w-1", "session-1"),
        ("@w-2", "session-2"),
        ("@w-1", "session-1"),
    ]


async def test_web_browser_legacy_sandbox_refused_in_tool_state_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    legacy_calls: list[str] = []
    legacy_sandbox_present = True

    async def no_tool_support_sandbox(*args: Any) -> Any:
        raise PrerequisiteError("no tool support sandbox")

    async def fake_web_browser_sandbox() -> object:
        if not legacy_sandbox_present:
            raise PrerequisiteError("no legacy sandbox")
        return object()

    async def fake_old_web_browser_cmd(cmd: str, *args: str) -> str:
        legacy_calls.append(cmd)
        return "legacy"

    monkeypatch.setattr(
        web_browser_module, "legacy_tool_support_sandbox", no_tool_support_sandbox
    )
    monkeypatch.setattr(
        web_browser_module, "_web_browser_sandbox", fake_web_browser_sandbox
    )
    monkeypatch.setattr(
        web_browser_module, "old_web_browser_cmd", fake_old_web_browser_cmd
    )

    init_subtask_store(Store())
    go = _named_tools(web_browser())["web_browser_go"].tool

    # outside a scope the legacy sandbox is still used
    assert await go(url="https://example.com") == "legacy"

    # inside a scope it is refused
    with tool_state_scope("w-1"):
        with pytest.raises(PrerequisiteError, match="legacy web browser sandbox"):
            await go(url="https://example.com")
    assert legacy_calls == ["web_go"]

    # an explicit shared instance is refused inside a scope too
    shared = _named_tools(web_browser(instance="team"))["web_browser_go"].tool
    with tool_state_scope("w-1"):
        with pytest.raises(PrerequisiteError, match="legacy web browser sandbox"):
            await shared(url="https://example.com")
    assert legacy_calls == ["web_go"]

    # an explicit instance reserved for scopes is refused, as with the
    # tool-support image
    reserved = _named_tools(web_browser(instance="@notes"))["web_browser_go"].tool
    with pytest.raises(ValueError, match="reserved for tool state scopes"):
        await reserved(url="https://example.com")
    assert legacy_calls == ["web_go"]

    # with no browser sandbox at all, the original error is kept
    legacy_sandbox_present = False
    with tool_state_scope("w-1"):
        with pytest.raises(PrerequisiteError, match="no tool support sandbox"):
            await go(url="https://example.com")


@skip_if_no_docker
@pytest.mark.slow
def test_web_browser_navigation():
    task = Task(
        dataset=[Sample(input="Please use the web_browser tool")],
        solver=[use_tools(web_browser()), generate()],
        sandbox=web_browser_sandbox(),
    )

    log = eval(
        task,
        model=get_model(
            "mockllm/model",
            custom_outputs=[
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="web_browser_go",
                    tool_arguments={
                        "url": "https://github.com/UKGovernmentBEIS/inspect_ai"
                    },
                ),
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="web_browser_scroll",
                    tool_arguments={"direction": "down"},
                ),
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="web_browser_scroll",
                    tool_arguments={"direction": "up"},
                ),
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="web_browser_go",
                    tool_arguments={"url": "https://inspect.aisi.org.uk/"},
                ),
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="web_browser_back",
                    tool_arguments={},
                ),
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="web_browser_forward",
                    tool_arguments={},
                ),
                ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="web_browser_refresh",
                    tool_arguments={},
                ),
                ModelOutput.from_content(
                    model="mockllm/model", content="We are all done here."
                ),
            ],
        ),
    )[0]

    def is_inspect_website(page: str) -> bool:
        return 'link "Anchor"  [url: https://inspect.aisi.org.uk/#welcome]' in page

    def is_inspect_repo(page: str) -> bool:
        return (
            'link "Skip to content"  [url: https://github.com/UKGovernmentBEIS/inspect_ai#start-of-content]'
            in page
        )

    assert log.samples

    def check_tool_call_page(tool: str, page: Literal["website", "repo"]) -> None:
        call = get_tool_call(log.samples[0].messages, tool)
        assert call
        response = get_tool_response(log.samples[0].messages, call)
        assert response
        if page == "website":
            assert is_inspect_website(response.text)
        elif page == "repo":
            assert is_inspect_repo(response.text)

    check_tool_call_page("web_browser_go", "repo")
    check_tool_call_page("web_browser_back", "repo")
    check_tool_call_page("web_browser_forward", "website")
    check_tool_call_page("web_browser_refresh", "website")


@skip_if_no_docker
@pytest.mark.slow
def test_web_browser_type_submit():
    call_number_gen = count()

    def custom_outputs_generator(
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        match next(call_number_gen):
            case 0:
                return ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="web_browser_go",
                    tool_arguments={
                        "url": "https://www.selenium.dev/selenium/web/web-form.html"
                    },
                )
            case 1:
                return ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="web_browser_type_submit",
                    tool_arguments={
                        "element_id": submit_id(input),
                        "text": "A submission",
                    },
                )
            case _:
                return ModelOutput.from_content(
                    model="mockllm/model", content="We are all done here."
                )

    def submit_id(input: list[ChatMessage]) -> int:
        """Fishes out the submit button element id from what should be the accessibility tree returned by the tool"""
        return find_element_id(input, r"button\s*\"Submit\"")

    task = Task(
        dataset=[Sample(input="Please use the web_browser tool")],
        solver=[use_tools(web_browser()), generate()],
        sandbox=web_browser_sandbox(),
    )

    log = eval(
        task,
        model=get_model(
            "mockllm/model",
            custom_outputs=custom_outputs_generator,
        ),
    )[0]

    assert log.samples

    assert "Form submitted" in log.samples[0].messages[4].text


@skip_if_no_docker
@pytest.mark.slow
@flaky_retry(max_retries=3)
def test_web_browser_open_new_page():
    call_number_gen = count()

    def custom_outputs_generator(
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput:
        match next(call_number_gen):
            case 0:
                return ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="web_browser_go",
                    tool_arguments={
                        "url": "https://www.selenium.dev/selenium/web/window_switching_tests/page_with_frame.html"
                    },
                )
            case 1:
                return ModelOutput.for_tool_call(
                    model="mockllm/model",
                    tool_name="web_browser_click",
                    tool_arguments={
                        "element_id": find_element_id(
                            input, r'link\s*"Open new window"'
                        ),
                    },
                )
            case _:
                return ModelOutput.from_content(
                    model="mockllm/model", content="We are all done here."
                )

    task = Task(
        dataset=[Sample(input="Please use the web_browser tool")],
        solver=[use_tools(web_browser()), generate()],
        sandbox=web_browser_sandbox(),
    )

    log = eval(
        task,
        model=get_model(
            "mockllm/model",
            custom_outputs=custom_outputs_generator,
        ),
    )[0]

    assert log.samples

    assert "Simple page with simple test." in log.samples[0].messages[4].text
    assert "Open new window" not in log.samples[0].messages[4].text


@skip_if_no_docker
@skip_if_no_openai
@pytest.mark.slow
def test_web_browser_click():
    task = Task(
        dataset=[
            Sample(
                input="Please use the web browser tool to navigate to https://inspect.aisi.org.uk/. Then, once there, use the web_browser_click tool to click the link to the documentation on Solvers."
            )
        ],
        solver=[use_tools(web_browser()), generate()],
        sandbox=web_browser_sandbox(),
    )

    log = eval(task, model="openai/gpt-4o")[0]

    click_call = get_tool_call(log.samples[0].messages, "web_browser_click")
    assert click_call
    click_response = get_tool_response(log.samples[0].messages, click_call)
    assert click_response


@skip_if_no_docker
@skip_if_no_openai
@pytest.mark.slow
def test_web_browser_input():
    task = Task(
        dataset=[
            Sample(
                input="Please use the web browser tool to navigate to https://www.google.com. Then, once there, use the page's search interface to search for 'large language models'"
            )
        ],
        solver=[use_tools(web_browser()), generate()],
        sandbox=web_browser_sandbox(),
    )

    log = eval(task, model="openai/gpt-4o")[0]

    type_call = get_tool_call(log.samples[0].messages, "web_browser_type_submit")
    assert type_call


def web_browser_sandbox() -> tuple[str, str]:
    return (
        "docker",
        (Path(__file__).parent / "test_inspect_tool_support.yaml").as_posix(),
    )
