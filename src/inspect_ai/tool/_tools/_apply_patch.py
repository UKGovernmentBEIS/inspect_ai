from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Literal, Sequence

from inspect_ai.tool import ToolResult
from inspect_ai.tool._tool import Tool, ToolError, tool
from inspect_ai.tool._tool_call import ApplyPatchOperation, validate_apply_patch_operation
from inspect_ai.util import sandbox as sandbox_env
from inspect_ai.util._sandbox.environment import SandboxEnvironment

__all__ = ["apply_patch", "ApplyPatchError"]


class ApplyPatchError(ToolError):
    """Error applying an apply_patch operation."""


@dataclass
class _UnifiedHunkLine:
    prefix: Literal[" ", "+", "-"]
    text: str
    has_newline: bool = True


@dataclass
class _UnifiedHunk:
    src_start: int
    src_len: int
    dst_start: int
    dst_len: int
    lines: list[_UnifiedHunkLine]


@dataclass
class _Workspace:
    sandbox: SandboxEnvironment
    user: str | None = None
    allow_delete: bool = True

    def _normalize_path(self, relative_path: str) -> str:
        """Normalize and validate path for sandbox operations.
        
        Prevents directory traversal while allowing relative paths.
        Returns a path string suitable for sandbox operations.
        """
        # Remove any leading/trailing whitespace
        path = relative_path.strip()
        
        # Prevent directory traversal
        if ".." in path:
            raise ApplyPatchError(
                f"Path '{relative_path}' contains '..' which is not allowed."
            )
            
        return path

    async def file_exists(self, path: str) -> bool:
        """Check if file exists in sandbox."""
        try:
            result = await self.sandbox.exec(
                cmd=["test", "-f", path],
                user=self.user
            )
            return result.returncode == 0
        except Exception:
            return False
    
    async def read_file(self, path: str) -> str:
        """Read file from sandbox."""
        return await self.sandbox.read_file(path, text=True)
    
    async def write_file(self, path: str, content: str) -> None:
        """Write file to sandbox (parent directories created automatically)."""
        await self.sandbox.write_file(path, content)
    
    async def delete_file(self, path: str) -> None:
        """Delete file from sandbox."""
        await self.sandbox.exec(
            cmd=["rm", "-f", path],
            user=self.user
        )


@tool(name="apply_patch", parallel=False)
def apply_patch(user: str | None = None, sandbox: str | None = None) -> Tool:
    """Apply create, update, and delete operations described via V4A diffs.

    Operates within the sandbox environment, making it compatible with other
    sandbox tools like bash and python.

    Args:
        sandbox: Optional sandbox environment name.
        user: Optional user to run operations as in the sandbox.

    Returns:
        Tool for handling apply_patch calls from the Responses API.
    """
    async def execute(operation: dict[str, object]) -> ToolResult:
        """Apply a single apply_patch operation to the workspace.

        Args:
            operation (dict[str, object]): Operation payload matching the OpenAI
                Responses `apply_patch` tool schema.
        """
        # Get the sandbox environment
        environment = sandbox_env(sandbox)

        # Create workspace bound to sandbox
        workspace = _Workspace(sandbox=environment, user=user)
        
        patch_operation = validate_apply_patch_operation(operation)
        if patch_operation.type == "create_file":
            return await _create_file(workspace, patch_operation)
        elif patch_operation.type == "update_file":
            return await _update_file(workspace, patch_operation)
        else:  # delete_file
            return await _delete_file(workspace, patch_operation)

    return execute


async def _create_file(workspace: _Workspace, operation: ApplyPatchOperation) -> str:
    if operation.diff is None:
        raise ApplyPatchError("create_file operation requires a diff payload.")
    
    path = workspace._normalize_path(operation.path)
    
    if await workspace.file_exists(path):
        raise ApplyPatchError(f"File '{operation.path}' already exists.")
    
    # Parse diff and generate content
    content = _apply_patch_to_text("", operation.diff.splitlines())
    
    # Write file to sandbox (parent directories created automatically)
    await workspace.write_file(path, content)
    
    return f"Created {operation.path}"


async def _update_file(workspace: _Workspace, operation: ApplyPatchOperation) -> str:
    if operation.diff is None:
        raise ApplyPatchError("update_file operation requires a diff payload.")
    
    path = workspace._normalize_path(operation.path)
    
    if not await workspace.file_exists(path):
        raise ApplyPatchError(f"File '{operation.path}' does not exist.")
    
    # Read current content from sandbox
    original = await workspace.read_file(path)
    
    # Apply diff
    updated = _apply_patch_to_text(original, operation.diff.splitlines())
    
    # Write back to sandbox
    await workspace.write_file(path, updated)
    
    return f"Updated {operation.path}"


async def _delete_file(workspace: _Workspace, operation: ApplyPatchOperation) -> str:
    if not workspace.allow_delete:
        raise ApplyPatchError("File deletion is disabled for apply_patch tool.")
    
    path = workspace._normalize_path(operation.path)
    
    if not await workspace.file_exists(path):
        raise ApplyPatchError(f"File '{operation.path}' does not exist.")
    
    # Delete from sandbox
    await workspace.delete_file(path)
    
    return f"Deleted {operation.path}"


def _apply_patch_to_text(original: str, diff_lines: Sequence[str]) -> str:
    hunks = _parse_unified_hunks(diff_lines)
    if not hunks:
        # Treat diff as full file content prefixed with '+'.
        return _render_create_lines(diff_lines)
    return _apply_hunks(original, hunks)


def _render_create_lines(lines: Sequence[str]) -> str:
    content_lines: list[str] = []
    newline_flags: list[bool] = []
    for line in lines:
        if not line:
            continue
        if line.startswith("\\ No newline at end of file"):
            if newline_flags:
                newline_flags[-1] = False
            continue
        if line[0] != "+":
            raise ApplyPatchError(f"Unexpected line '{line}' in create diff.")
        content_lines.append(line[1:])
        newline_flags.append(True)

    rendered: list[str] = []
    for text, has_newline in zip(content_lines, newline_flags):
        rendered.append(text + ("\n" if has_newline else ""))
    return "".join(rendered)


def _parse_unified_hunks(lines: Sequence[str]) -> list[_UnifiedHunk]:
    hunks: list[_UnifiedHunk] = []
    i = 0
    current_lines: list[_UnifiedHunkLine]
    while i < len(lines):
        line = lines[i]
        if not line:
            i += 1
            continue
        if line.startswith("@@"):
            # Try to parse standard unified diff format first
            match = re.match(
                r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", line.strip()
            )
            if match:
                # Standard unified diff format with line numbers
                src_start = int(match.group(1))
                src_len = int(match.group(2)) if match.group(2) else 1
                dst_start = int(match.group(3))
                dst_len = int(match.group(4)) if match.group(4) else 1
            elif line.strip() == "@@":
                # V4A format: @@ without line numbers
                src_start = 1
                src_len = 0
                dst_start = 1
                dst_len = 0
            else:
                raise ApplyPatchError(
                    f"Malformed hunk header '{line}'. "
                    f"Expected '@@ -start,count +start,count @@' or '@@' (V4A format)."
                )
            current_lines = []
            i += 1
            while i < len(lines):
                current = lines[i]
                if current.startswith("@@") or current.startswith("***"):
                    break
                if current.startswith("\\ No newline at end of file"):
                    if not current_lines:
                        raise ApplyPatchError(
                            "No newline marker appears before any hunk content."
                        )
                    current_lines[-1].has_newline = False
                    i += 1
                    continue
                if not current:
                    current_lines.append(_UnifiedHunkLine(" ", "", True))
                    i += 1
                    continue
                prefix = current[0]
                if prefix not in {" ", "+", "-"}:
                    raise ApplyPatchError(f"Unexpected hunk line '{current}'.")
                current_lines.append(_UnifiedHunkLine(prefix, current[1:], True))
                i += 1
            hunks.append(
                _UnifiedHunk(
                    src_start=src_start,
                    src_len=src_len,
                    dst_start=dst_start,
                    dst_len=dst_len,
                    lines=current_lines,
                )
            )
        else:
            i += 1
    return hunks


def _apply_hunks(original: str, hunks: Sequence[_UnifiedHunk]) -> str:
    original_lines = original.splitlines(keepends=True)
    result: list[str] = []
    index = 0

    for hunk in hunks:
        # Check if this is a V4A format hunk (src_len == 0)
        is_v4a = hunk.src_len == 0
        
        if is_v4a:
            # V4A format: search for context from current position
            # Find where this hunk's deletion pattern starts
            deletion_lines = [line for line in hunk.lines if line.prefix == "-"]
            if deletion_lines:
                # Search for the first deletion line starting from current index
                search_text = deletion_lines[0].text
                found_at = None
                for search_idx in range(index, len(original_lines)):
                    line_text = original_lines[search_idx]
                    comparison = line_text[:-1] if line_text.endswith("\n") else line_text
                    if comparison == search_text:
                        found_at = search_idx
                        break
                
                if found_at is None:
                    raise ApplyPatchError(
                        f"Could not find deletion pattern '{search_text}' in file."
                    )
                
                # Copy everything from index to found_at
                while index < found_at:
                    result.append(original_lines[index])
                    index += 1
            # else: hunk has only additions, apply at current position
        else:
            # Standard unified diff: use line numbers
            target_index = max(hunk.src_start - 1, 0)
            while index < target_index and index < len(original_lines):
                result.append(original_lines[index])
                index += 1

        # Apply the hunk lines
        for line in hunk.lines:
            if line.prefix in {" ", "-"}:
                if index >= len(original_lines):
                    raise ApplyPatchError("Patch extends beyond end of file.")
                original_line = original_lines[index]
                comparison = (
                    original_line[:-1] if original_line.endswith("\n") else original_line
                )
                if comparison != line.text:
                    raise ApplyPatchError(
                        f"Patch hunk context mismatch. Expected '{line.text}', "
                        f"got '{comparison}'."
                    )
                if line.prefix == " ":
                    result.append(original_line if line.has_newline else line.text)
                index += 1
            elif line.prefix == "+":
                text = line.text + ("\n" if line.has_newline else "")
                result.append(text)
            else:
                raise ApplyPatchError(f"Unsupported hunk prefix '{line.prefix}'.")

    result.extend(original_lines[index:])
    return "".join(result)
