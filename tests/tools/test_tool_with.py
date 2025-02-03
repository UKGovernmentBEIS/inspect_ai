from test_helpers.tools import addition

from inspect_ai.tool import ToolDef, tool_with

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
