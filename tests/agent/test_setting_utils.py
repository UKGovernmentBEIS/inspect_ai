import pytest

from inspect_ai.agent._react import _default_workspace_tools
from inspect_ai.agent._setting import Setting, Workspace
from inspect_ai.agent._setting_utils import handle_on_turn, tools_from_setting
from inspect_ai.model import ChatMessageUser, ModelName
from inspect_ai.solver._task_state import TaskState, set_sample_state
from inspect_ai.tool import tool
from inspect_ai.tool._tool_def import ToolDef
from inspect_ai.tool._tool_with import tool_with
from inspect_ai.tool._tools._execute import bash, python


@pytest.fixture(autouse=True)
def _clear_sample_state():
    """Clear sample state before each test to avoid leaking between tests."""
    from inspect_ai.solver._task_state import _sample_state

    token = _sample_state.set(None)  # type: ignore[arg-type]
    yield
    _sample_state.reset(token)


@tool
def my_tool():
    async def execute(x: str) -> str:
        """A custom tool.

        Args:
            x: Input string.
        """
        return x

    return execute


def _setup_setting(s: Setting) -> None:
    """Helper to set up a sample state with the given Setting."""
    state = TaskState(
        model=ModelName("mockllm/model"),
        sample_id=0,
        epoch=1,
        input="test",
        messages=[ChatMessageUser(content="test")],
        setting=s,
    )
    set_sample_state(state)


def test_tools_from_setting_no_setting():
    """When there is no setting, solver tools are returned unchanged."""
    solver_tools = [my_tool()]
    result = tools_from_setting(solver_tools, _default_workspace_tools)
    assert len(result) == 1


def test_tools_from_setting_single_default_workspace():
    """Default workspace creates a 'bash' tool."""
    _setup_setting(Setting(workspaces=(Workspace(description="Test workspace"),)))
    result = tools_from_setting([], _default_workspace_tools)
    names = [ToolDef(t).name if not isinstance(t, ToolDef) else t.name for t in result]
    assert "bash" in names


def test_tools_from_setting_multi_workspace_naming():
    """Non-default workspaces get bash_{name} tools."""
    _setup_setting(
        Setting(
            workspaces=(
                Workspace(name="default", description="Main"),
                Workspace(name="db", description="Database server"),
            )
        )
    )
    result = tools_from_setting([], _default_workspace_tools)
    names = [ToolDef(t).name if not isinstance(t, ToolDef) else t.name for t in result]
    assert "bash" in names
    assert "bash_db" in names
    assert len([n for n in names if n.startswith("bash")]) == 2


def test_tools_from_setting_description_in_tool():
    """Workspace description is injected into tool description."""
    _setup_setting(
        Setting(
            workspaces=(
                Workspace(
                    name="default",
                    description="Debian workspace with target at port 8080",
                ),
            )
        )
    )
    result = tools_from_setting([], _default_workspace_tools)
    bash_tools = [
        t
        for t in result
        if (ToolDef(t).name if not isinstance(t, ToolDef) else t.name) == "bash"
    ]
    assert len(bash_tools) == 1
    desc = (
        ToolDef(bash_tools[0]).description
        if not isinstance(bash_tools[0], ToolDef)
        else bash_tools[0].description
    )
    assert "Debian workspace with target at port 8080" in desc


def test_tools_from_setting_custom_tools_prepended():
    """Setting.tools are prepended before workspace tools."""
    _setup_setting(
        Setting(
            workspaces=(Workspace(),),
            tools=(my_tool(),),
        )
    )
    result = tools_from_setting([], _default_workspace_tools)
    names = [ToolDef(t).name if not isinstance(t, ToolDef) else t.name for t in result]
    assert names[0] == "my_tool"


def test_tools_from_setting_dedup_solver_tools():
    """Solver tools with same name as setting tools are removed."""
    _setup_setting(Setting(tools=(my_tool(),)))
    solver_tools = [my_tool()]
    result = tools_from_setting(solver_tools, _default_workspace_tools)
    names = [ToolDef(t).name if not isinstance(t, ToolDef) else t.name for t in result]
    assert names.count("my_tool") == 1


def test_tools_from_setting_lockdown_drops_solver_tools():
    """When Setting exists, non-framework solver tools are dropped."""
    _setup_setting(Setting(tools=(my_tool(),)))
    solver_tools = [my_tool(), bash()]
    result = tools_from_setting(solver_tools, _default_workspace_tools)
    names = [ToolDef(t).name if not isinstance(t, ToolDef) else t.name for t in result]
    assert "my_tool" in names
    assert "bash" not in names


def test_tools_from_setting_framework_tools_survive():
    """Framework tools survive even when Setting controls the surface."""
    _setup_setting(Setting(tools=(my_tool(),)))
    solver_tools = [my_tool(), bash()]
    result = tools_from_setting(
        solver_tools, _default_workspace_tools, framework_tools={"bash"}
    )
    names = [ToolDef(t).name if not isinstance(t, ToolDef) else t.name for t in result]
    assert "my_tool" in names
    assert "bash" in names


def test_tools_from_setting_empty_setting_drops_solver_tools():
    """Empty Setting (no workspaces, no tools) drops all non-framework solver tools."""
    _setup_setting(Setting())
    solver_tools = [bash()]
    result = tools_from_setting(solver_tools, _default_workspace_tools)
    assert len(result) == 0


def test_tools_from_setting_custom_workspace_tools_factory():
    """Custom workspace_tools factory creates the tools it returns."""
    _setup_setting(
        Setting(
            workspaces=(
                Workspace(name="default", description="Main"),
                Workspace(name="db", description="Database"),
            )
        )
    )

    def my_factory(ws: Workspace, index: int) -> list:
        prefix = "" if index == 0 else f"_{ws.name}"
        return [
            tool_with(bash(sandbox=ws.name, user=ws.user), name=f"bash{prefix}"),
            tool_with(python(sandbox=ws.name, user=ws.user), name=f"python{prefix}"),
        ]

    result = tools_from_setting([], my_factory)
    names = [ToolDef(t).name if not isinstance(t, ToolDef) else t.name for t in result]
    assert "bash" in names
    assert "python" in names
    assert "bash_db" in names
    assert "python_db" in names
    assert len(names) == 4


async def test_handle_on_turn_no_setting():
    """Returns 'proceed' when no setting."""
    result = await handle_on_turn()
    assert result.action == "proceed"
    assert result.message is None


async def test_handle_on_turn_no_callback():
    """Returns 'proceed' when setting has no on_turn."""
    _setup_setting(Setting())
    result = await handle_on_turn()
    assert result.action == "proceed"


async def test_handle_on_turn_returns_none():
    """on_turn returning None means proceed."""

    async def noop() -> None:
        return None

    _setup_setting(Setting(on_turn=noop))
    result = await handle_on_turn()
    assert result.action == "proceed"


async def test_handle_on_turn_returns_true():
    """on_turn returning True means proceed."""

    async def ok() -> bool:
        return True

    _setup_setting(Setting(on_turn=ok))
    result = await handle_on_turn()
    assert result.action == "proceed"


async def test_handle_on_turn_returns_false():
    """on_turn returning False means break and sets completed."""

    async def stop() -> bool:
        return False

    _setup_setting(Setting(on_turn=stop))
    from inspect_ai.solver._task_state import sample_state

    state = sample_state()
    result = await handle_on_turn()
    assert result.action == "break"
    assert result.message is None
    assert state.completed is True


async def test_handle_on_turn_returns_string():
    """on_turn returning str means continue with message (caller injects)."""

    async def inject() -> str:
        return "Try harder"

    _setup_setting(Setting(on_turn=inject))
    result = await handle_on_turn()
    assert result.action == "continue"
    assert result.message == "Try harder"


async def test_handle_on_turn_returns_empty_string():
    """on_turn returning empty string means continue with empty message."""

    async def empty() -> str:
        return ""

    _setup_setting(Setting(on_turn=empty))
    result = await handle_on_turn()
    assert result.action == "continue"
    assert result.message == ""
