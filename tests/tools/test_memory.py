"""Tests for memory tool."""

import pytest

from inspect_ai.tool import ToolError, memory
from inspect_ai.util import Store
from inspect_ai.util._store import init_subtask_store


@pytest.fixture(autouse=True)
def reset_store() -> None:
    """Reset store between tests to ensure isolation."""
    init_subtask_store(Store())


@pytest.mark.asyncio
async def test_create_file() -> None:
    """Test basic file creation."""
    tool = memory()
    result = await tool(command="create", path="/memories/test.txt", file_text="hello")
    assert isinstance(result, str)
    assert "created" in result.lower() or "test.txt" in result


@pytest.mark.asyncio
async def test_view_nonexistent_path() -> None:
    """Test viewing a path that doesn't exist."""
    tool = memory()
    with pytest.raises(ToolError, match="does not exist"):
        await tool(command="view", path="/memories/nonexistent.txt")


@pytest.mark.asyncio
async def test_view_file_basic() -> None:
    """Test viewing a created file."""
    tool = memory()
    await tool(
        command="create", path="/memories/test.txt", file_text="line1\nline2\nline3"
    )
    result = await tool(command="view", path="/memories/test.txt")
    assert isinstance(result, str)
    assert "line1" in result
    assert "line2" in result
    assert "line3" in result


@pytest.mark.asyncio
async def test_view_file_with_range() -> None:
    """Test viewing file with line range."""
    tool = memory()
    await tool(
        command="create",
        path="/memories/test.txt",
        file_text="line1\nline2\nline3\nline4",
    )
    result = await tool(command="view", path="/memories/test.txt", view_range=[2, 3])
    assert isinstance(result, str)
    assert "line2" in result
    assert "line3" in result
    assert "line1" not in result
    assert "line4" not in result


@pytest.mark.asyncio
async def test_str_replace_basic() -> None:
    """Test basic string replacement."""
    tool = memory()
    await tool(command="create", path="/memories/test.txt", file_text="hello world")
    result = await tool(
        command="str_replace",
        path="/memories/test.txt",
        old_str="hello",
        new_str="goodbye",
    )
    assert isinstance(result, str)
    assert "edited" in result.lower()
    # Verify change
    content = await tool(command="view", path="/memories/test.txt")
    assert isinstance(content, str)
    assert "goodbye" in content
    assert "hello" not in content


@pytest.mark.parametrize(
    "file_text,old_str,match",
    [
        ("hello world", "foo", "did not appear"),
        ("hello hello", "hello", "Multiple occurrences"),
    ],
)
@pytest.mark.asyncio
async def test_str_replace_errors(file_text: str, old_str: str, match: str) -> None:
    """Test str_replace error cases."""
    tool = memory()
    await tool(command="create", path="/memories/test.txt", file_text=file_text)
    with pytest.raises(ToolError, match=match):
        await tool(
            command="str_replace",
            path="/memories/test.txt",
            old_str=old_str,
            new_str="bar",
        )


@pytest.mark.asyncio
async def test_insert_basic() -> None:
    """Test inserting text at line number."""
    tool = memory()
    await tool(command="create", path="/memories/test.txt", file_text="line1\nline2")
    result = await tool(
        command="insert",
        path="/memories/test.txt",
        insert_line=1,
        insert_text="inserted",
    )
    assert isinstance(result, str)
    assert "edited" in result.lower()
    # Verify insertion
    content = await tool(command="view", path="/memories/test.txt")
    assert isinstance(content, str)
    assert "line1" in content and "inserted" in content and "line2" in content
    # Check order by line numbers
    assert content.index("line1") < content.index("inserted") < content.index("line2")


@pytest.mark.asyncio
async def test_delete_file() -> None:
    """Test deleting a file."""
    tool = memory()
    await tool(command="create", path="/memories/test.txt", file_text="hello")
    result = await tool(command="delete", path="/memories/test.txt")
    assert isinstance(result, str)
    assert "deleted" in result.lower() or "removed" in result.lower()
    # Verify deletion
    with pytest.raises(ToolError, match="does not exist"):
        await tool(command="view", path="/memories/test.txt")


@pytest.mark.asyncio
async def test_rename_file() -> None:
    """Test renaming a file."""
    tool = memory()
    await tool(command="create", path="/memories/old.txt", file_text="content")
    result = await tool(
        command="rename", old_path="/memories/old.txt", new_path="/memories/new.txt"
    )
    assert isinstance(result, str)
    assert "renamed" in result.lower() or "moved" in result.lower()
    # Verify rename
    with pytest.raises(ToolError, match="does not exist"):
        await tool(command="view", path="/memories/old.txt")
    content = await tool(command="view", path="/memories/new.txt")
    assert isinstance(content, str)
    assert "content" in content


@pytest.mark.asyncio
async def test_view_directory() -> None:
    """Test viewing directory contents."""
    tool = memory()
    await tool(command="create", path="/memories/dir/test.txt", file_text="hello")
    result = await tool(command="view", path="/memories/dir")
    assert isinstance(result, str)
    assert "test.txt" in result


@pytest.mark.parametrize(
    "path,match",
    [
        ("/tmp/test.txt", "/memories"),
        ("/memories/../etc/passwd", "Invalid path|traversal"),
    ],
)
@pytest.mark.asyncio
async def test_path_validation(path: str, match: str) -> None:
    """Test path validation."""
    tool = memory()
    with pytest.raises(ToolError, match=match):
        await tool(command="create", path=path, file_text="bad")


@pytest.mark.asyncio
async def test_create_with_parent_dirs() -> None:
    """Test that parent directories are created automatically."""
    tool = memory()
    result = await tool(
        command="create", path="/memories/a/b/c/test.txt", file_text="nested"
    )
    assert isinstance(result, str)
    assert "created" in result.lower()
    # Verify file exists
    content = await tool(command="view", path="/memories/a/b/c/test.txt")
    assert isinstance(content, str)
    assert "nested" in content


@pytest.mark.asyncio
async def test_delete_directory_recursive() -> None:
    """Test recursive directory deletion."""
    tool = memory()
    await tool(command="create", path="/memories/dir/test.txt", file_text="hello")
    result = await tool(command="delete", path="/memories/dir")
    assert isinstance(result, str)
    assert "deleted" in result.lower() or "removed" in result.lower()
    # Verify deletion
    with pytest.raises(ToolError, match="does not exist"):
        await tool(command="view", path="/memories/dir")


@pytest.mark.asyncio
async def test_initial_data_single_file() -> None:
    """Test seeding with a single file."""
    tool = memory(initial_data={"/memories/seeded.txt": "initial content"})
    content = await tool(command="view", path="/memories/seeded.txt")
    assert isinstance(content, str)
    assert "initial content" in content


@pytest.mark.asyncio
async def test_initial_data_multiple_files() -> None:
    """Test seeding with multiple files."""
    tool = memory(
        initial_data={
            "/memories/file1.txt": "content1",
            "/memories/file2.txt": "content2",
            "/memories/file3.txt": "content3",
        }
    )
    for path, expected in [
        ("/memories/file1.txt", "content1"),
        ("/memories/file2.txt", "content2"),
        ("/memories/file3.txt", "content3"),
    ]:
        content = await tool(command="view", path=path)
        assert isinstance(content, str)
        assert expected in content


@pytest.mark.asyncio
async def test_initial_data_nested_paths() -> None:
    """Test seeding with nested paths creates parent dirs."""
    tool = memory(
        initial_data={
            "/memories/a/b/c.txt": "nested1",
            "/memories/x/y/z.txt": "nested2",
        }
    )
    for path, expected in [
        ("/memories/a/b/c.txt", "nested1"),
        ("/memories/x/y/z.txt", "nested2"),
    ]:
        content = await tool(command="view", path=path)
        assert isinstance(content, str)
        assert expected in content


@pytest.mark.asyncio
async def test_initial_data_empty_dict() -> None:
    """Test empty initial_data works."""
    tool = memory(initial_data={})
    # Should be able to create files normally
    result = await tool(
        command="create", path="/memories/test.txt", file_text="created"
    )
    assert isinstance(result, str)
    assert "created" in result.lower()


@pytest.mark.asyncio
async def test_initial_data_seeding_once() -> None:
    """Test that seeding only happens on first call."""
    tool = memory(initial_data={"/memories/seed.txt": "original"})
    # First call triggers seeding
    await tool(command="view", path="/memories/seed.txt")
    # Modify the file
    await tool(
        command="str_replace",
        path="/memories/seed.txt",
        old_str="original",
        new_str="modified",
    )
    # Verify modification persists (seeding doesn't happen again)
    content = await tool(command="view", path="/memories/seed.txt")
    assert isinstance(content, str)
    assert "modified" in content
    assert "original" not in content


@pytest.mark.asyncio
async def test_initial_data_none() -> None:
    """Test default case with initial_data=None."""
    tool = memory(initial_data=None)
    # Create file normally
    result = await tool(
        command="create", path="/memories/test.txt", file_text="normal create"
    )
    assert isinstance(result, str)
    assert "created" in result.lower()
    # Verify file exists
    content = await tool(command="view", path="/memories/test.txt")
    assert isinstance(content, str)
    assert "normal create" in content


@pytest.mark.asyncio
async def test_initial_data_then_modify() -> None:
    """Test modifying seeded files with str_replace."""
    tool = memory(initial_data={"/memories/modify.txt": "line1\nline2\nline3"})
    # Modify seeded file
    result = await tool(
        command="str_replace",
        path="/memories/modify.txt",
        old_str="line2",
        new_str="CHANGED",
    )
    assert isinstance(result, str)
    assert "edited" in result.lower()
    # Verify change
    content = await tool(command="view", path="/memories/modify.txt")
    assert isinstance(content, str)
    assert "CHANGED" in content
    assert "line2" not in content


@pytest.mark.asyncio
async def test_initial_data_view_with_range() -> None:
    """Test viewing seeded files with line range."""
    tool = memory(initial_data={"/memories/lines.txt": "line1\nline2\nline3\nline4"})
    # View with range
    content = await tool(command="view", path="/memories/lines.txt", view_range=[2, 3])
    assert isinstance(content, str)
    assert "line2" in content
    assert "line3" in content
    assert "line1" not in content
    assert "line4" not in content


@pytest.mark.parametrize(
    "invalid_path,match",
    [
        ("/tmp/bad.txt", "/memories"),
        ("/memories/../etc/passwd", "Invalid path|outside"),
    ],
)
@pytest.mark.asyncio
async def test_initial_data_invalid_paths(invalid_path: str, match: str) -> None:
    """Test that invalid paths in initial_data raise errors."""
    tool = memory(initial_data={invalid_path: "content"})
    # Seeding happens on first execute call
    with pytest.raises(ToolError, match=match):
        await tool(command="view", path="/memories")
