from typing import Any

from test_helpers.tools import addition

from inspect_ai.tool import (
    Content,
    ToolCall,
    ToolCallView,
    ToolDef,
    ToolParam,
    ToolParams,
    tool_with,
)
from inspect_ai.tool._tool_call import ToolCallModelInputHints
from inspect_ai.tool._tool_def import tool_registry_info

NAME = "my_addition"
DESCRIPTION = "my description"
X_DESCRIPTION = "my x description"
Y_DESCRIPTION = "my y description"


def test_tool_with():
    tool = tool_with(
        addition(),
        name=NAME,
        description=DESCRIPTION,
        parameters={"x": X_DESCRIPTION, "y": Y_DESCRIPTION},
    )

    tdef = ToolDef(tool)

    assert tdef.name == NAME
    assert tdef.description == DESCRIPTION
    assert tdef.parameters.properties["x"].description == X_DESCRIPTION
    assert tdef.parameters.properties["y"].description == Y_DESCRIPTION


def test_tool_with_validation():
    try:
        tool_with(
            addition(),
            parameters={"p": X_DESCRIPTION, "q": Y_DESCRIPTION},
        )
        assert False
    except Exception:
        pass


def test_tool_with_name_keeps_tool_def_description() -> None:
    async def execute(**kwargs: Any) -> str:
        return ""

    tool = ToolDef(
        execute,
        name="search",
        description="Search the web.",
        parameters=ToolParams(
            properties={"query": ToolParam(type="string", description="The query.")},
            required=["query"],
        ),
    ).as_tool()

    tdef = ToolDef(tool_with(tool, name=NAME))

    assert tdef.name == NAME
    assert tdef.description == "Search the web."
    assert tdef.parameters.properties["query"].description == "The query."


def _viewer(call: ToolCall) -> ToolCallView:
    return ToolCallView()


def _model_input(
    index: int, total: int, content: str | list[Content], hints: ToolCallModelInputHints
) -> str | list[Content]:
    return content


def test_tool_with_parallel_and_viewer() -> None:
    info = tool_registry_info(tool_with(addition(), parallel=True, viewer=_viewer))

    assert info.parallel is True
    assert info.viewer is _viewer
    assert info.model_input is None


def test_tool_with_viewer_and_model_input() -> None:
    info = tool_registry_info(
        tool_with(addition(), viewer=_viewer, model_input=_model_input)
    )

    assert info.viewer is _viewer
    assert info.model_input is _model_input


def test_tool_with_parallel_viewer_and_model_input() -> None:
    info = tool_registry_info(
        tool_with(addition(), parallel=True, viewer=_viewer, model_input=_model_input)
    )

    assert info.parallel is True
    assert info.viewer is _viewer
    assert info.model_input is _model_input


def test_tool_with_attributes_alone() -> None:
    assert tool_registry_info(tool_with(addition(), parallel=True)).parallel is True
    assert tool_registry_info(tool_with(addition(), viewer=_viewer)).viewer is _viewer
    assert (
        tool_registry_info(tool_with(addition(), model_input=_model_input)).model_input
        is _model_input
    )


def test_tool_with_keeps_earlier_tool_with_changes() -> None:
    tool = tool_with(addition(), name=NAME, parameters={"x": X_DESCRIPTION})
    tool = tool_with(tool, description=DESCRIPTION, parameters={"y": Y_DESCRIPTION})

    tdef = ToolDef(tool)

    assert tdef.name == NAME
    assert tdef.description == DESCRIPTION
    assert tdef.parameters.properties["x"].description == X_DESCRIPTION
    assert tdef.parameters.properties["y"].description == Y_DESCRIPTION
