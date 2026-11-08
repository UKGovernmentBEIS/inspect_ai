from typing import Any

from test_helpers.tools import addition

from inspect_ai.tool import ToolDef, ToolParam, ToolParams, tool_with

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


def test_tool_with_keeps_earlier_tool_with_changes() -> None:
    tool = tool_with(addition(), name=NAME, parameters={"x": X_DESCRIPTION})
    tool = tool_with(tool, description=DESCRIPTION, parameters={"y": Y_DESCRIPTION})

    tdef = ToolDef(tool)

    assert tdef.name == NAME
    assert tdef.description == DESCRIPTION
    assert tdef.parameters.properties["x"].description == X_DESCRIPTION
    assert tdef.parameters.properties["y"].description == Y_DESCRIPTION


def _viewer(call: Any) -> Any:
    from inspect_ai.tool._tool_call import ToolCallView

    return ToolCallView()


def _model_input(index: int, total: int, content: Any, hints: Any) -> Any:
    return content


def test_tool_with_applies_parallel_viewer_and_model_input_together():
    """The three attributes are independent; none of them displaces another."""
    tool = tool_with(
        addition(), parallel=True, viewer=_viewer, model_input=_model_input
    )

    tdef = ToolDef(tool)

    assert tdef.parallel is True
    assert tdef.viewer is _viewer
    assert tdef.model_input is _model_input


def test_tool_with_applies_viewer_and_model_input_without_parallel():
    tool = tool_with(addition(), viewer=_viewer, model_input=_model_input)

    tdef = ToolDef(tool)

    assert tdef.viewer is _viewer
    assert tdef.model_input is _model_input


def test_tool_with_disabling_parallel_keeps_the_viewer():
    """`parallel=False` is an explicit value, so it must not shadow the other attributes."""
    tool = tool_with(addition(), parallel=False, viewer=_viewer)

    tdef = ToolDef(tool)

    assert tdef.parallel is False
    assert tdef.viewer is _viewer


def test_tool_with_keeps_a_viewer_set_by_an_earlier_call():
    tool = tool_with(addition(), viewer=_viewer)

    tool_with(tool, model_input=_model_input)

    tdef = ToolDef(tool)
    assert tdef.viewer is _viewer
    assert tdef.model_input is _model_input
