import anyio
import pytest

from inspect_ai.util import (
    private_tool_instance,
    tool_state_instance,
    tool_state_scope,
)


def test_explicit_instance_returned_as_given() -> None:
    assert tool_state_instance("team") == "team"
    with tool_state_scope("w-1"):
        assert tool_state_instance("team") == "team"


def test_default_instance_resolves_to_scope() -> None:
    assert tool_state_instance(None) is None
    with tool_state_scope("w-1"):
        assert tool_state_instance(None) == "w-1"
    assert tool_state_instance(None) is None


def test_nested_scopes_join_names() -> None:
    with tool_state_scope("outer"):
        with tool_state_scope("inner"):
            assert tool_state_instance(None) == "outer/inner"
            assert private_tool_instance("general") == "outer/inner/general"
        assert tool_state_instance(None) == "outer"


def test_private_tool_instance() -> None:
    assert private_tool_instance("general") == "general"
    with tool_state_scope("w-1"):
        assert private_tool_instance("general") == "w-1/general"


def test_scope_reset_on_error() -> None:
    with pytest.raises(RuntimeError):
        with tool_state_scope("w-1"):
            raise RuntimeError("boom")
    assert tool_state_instance(None) is None


@pytest.mark.parametrize("name", ["", "a/b"])
def test_invalid_scope_name(name: str) -> None:
    with pytest.raises(ValueError, match="Tool state scope name"):
        with tool_state_scope(name):
            pass


async def test_scope_does_not_leak_into_sibling_task() -> None:
    entered = anyio.Event()
    checked = anyio.Event()
    seen: dict[str, str | None] = {}

    async def scoped() -> None:
        with tool_state_scope("w-1"):
            async with anyio.create_task_group() as tg:

                async def child() -> None:
                    seen["child"] = tool_state_instance(None)

                tg.start_soon(child)
            entered.set()
            await checked.wait()
            seen["scoped"] = tool_state_instance(None)

    async def sibling() -> None:
        await entered.wait()
        seen["sibling"] = tool_state_instance(None)
        checked.set()

    async with anyio.create_task_group() as tg:
        tg.start_soon(scoped)
        tg.start_soon(sibling)

    assert seen == {"child": "w-1", "sibling": None, "scoped": "w-1"}
    assert tool_state_instance(None) is None
