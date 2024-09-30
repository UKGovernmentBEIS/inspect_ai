from pathlib import Path
from typing import Literal

import pytest
from test_helpers.tool_call_utils import get_tool_call, get_tool_response
from test_helpers.utils import skip_if_no_docker

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.model import ModelOutput, get_model
from inspect_ai.solver import generate, use_tools
from inspect_ai.tool import web_browser_tools


@skip_if_no_docker
@pytest.mark.slow
def test_web_browser():
    task = Task(
        dataset=[Sample(input="Please use the web_browser tool")],
        solver=[use_tools(web_browser_tools()), generate()],
        sandbox=(
            "docker",
            (Path(__file__).parent / "test_web_browser_compose.yaml").as_posix(),
        ),
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
                    tool_arguments={
                        "url": "https://inspect.ai-safety-institute.org.uk/"
                    },
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
        return (
            'RootWebArea "Inspect" [focused: True, url: https://inspect.ai-safety-institute.org.uk/]'
            in page
        )

    def is_inspect_repo(page: str) -> bool:
        return (
            'RootWebArea "GitHub - UKGovernmentBEIS/inspect_ai: Inspect: A framework for large language model evaluations" [focused: True, url: https://github.com/UKGovernmentBEIS/inspect_ai]'
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
