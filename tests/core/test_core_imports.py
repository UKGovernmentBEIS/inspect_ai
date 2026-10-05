import ast
import sys
from pathlib import Path

import inspect_ai.core

# Public symbols defined in `inspect_ai.core` (exported via its `__all__` and
# via `__all__` of the public package in parentheses):
#
# _chat_message (inspect_ai.model): ChatMessage, ChatMessageAssistant,
#   ChatMessageBase, ChatMessageSystem, ChatMessageTool, ChatMessageUser
# content (inspect_ai.model, inspect_ai.tool): Content, ContentAudio,
#   ContentData, ContentDocument, ContentImage, ContentReasoning, ContentText,
#   ContentToolUse, ContentVideo
# _tool_call (inspect_ai.tool): ToolCall, ToolCallContent, ToolCallError,
#   ToolCallModelInput, ToolCallView, ToolCallViewer
# _tool_info (inspect_ai.tool): INTERNAL_TOOL_TYPE, ToolInfo, internal_tool_type
# _tool_choice (inspect_ai.tool): ToolChoice, ToolFunction
# _tool_params (inspect_ai.tool): ToolParam, ToolParams
# _model_output (inspect_ai.model): ChatCompletionChoice, Logprob, Logprobs,
#   ModelFallback, ModelOutput, ModelUsage, StopCategory, StopDetails,
#   StopReason, TopLogprob
# _generate_config (inspect_ai.model): BatchConfig, GenerateConfig,
#   GenerateConfigArgs, ImageOutput, OutputModality, ResponseSchema
# _cache_policy (inspect_ai.model): CachePolicy
# _adaptive_concurrency (inspect_ai.util): AdaptiveConcurrency
# _json (inspect_ai.util): JSONSchema, JSONType
# citation (inspect_ai.model, inspect_ai.tool): Citation, CitationBase,
#   ContentCitation, DocumentCitation, UrlCitation

CORE_DIR = Path(inspect_ai.core.__file__).parent

ALLOWED_THIRD_PARTY = {"pydantic", "pydantic_core", "typing_extensions", "shortuuid"}

# Function-level imports from outside `inspect_ai.core` that are still allowed,
# keyed by file relative to the core package. Remove entries as they are fixed.
KNOWN_EXCEPTIONS = {
    "_chat_message.py": {"inspect_ai._util.logger"},
    "_model_output.py": {"inspect_ai.model._model"},
}


def _module_name(path: Path) -> str:
    parts = path.relative_to(CORE_DIR).with_suffix("").parts
    return ".".join(
        ("inspect_ai.core", *(parts[:-1] if parts[-1] == "__init__" else parts))
    )


def _imported_modules(path: Path) -> set[tuple[str, bool]]:
    """Every module imported in the file, and whether the import is inside a function.

    Relative imports are resolved to absolute module names.
    """
    module = _module_name(path)
    package = module if path.name == "__init__.py" else module.rpartition(".")[0]
    tree = ast.parse(path.read_text())
    in_function = {
        id(node)
        for scope in ast.walk(tree)
        if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef))
        for node in ast.walk(scope)
    }
    nodes = list(ast.walk(tree))
    return {
        (alias.name, id(node) in in_function)
        for node in nodes
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        (
            ".".join(
                filter(
                    None,
                    (
                        package.rsplit(".", node.level - 1)[0] if node.level else None,
                        node.module,
                    ),
                )
            ),
            id(node) in in_function,
        )
        for node in nodes
        if isinstance(node, ast.ImportFrom)
    }


def _is_allowed(module: str) -> bool:
    top = module.split(".")[0]
    return (
        module == "inspect_ai.core"
        or module.startswith("inspect_ai.core.")
        or top in sys.stdlib_module_names
        or top in ALLOWED_THIRD_PARTY
    )


def test_core_imports_only_allowed_modules() -> None:
    disallowed = {
        str(path.relative_to(CORE_DIR)): {
            (module, in_function)
            for module, in_function in _imported_modules(path)
            if not _is_allowed(module)
        }
        for path in sorted(CORE_DIR.rglob("*.py"))
    }
    excepted = {
        file: {(module, True) for module in modules}
        for file, modules in KNOWN_EXCEPTIONS.items()
    }
    unexpected = {
        file: sorted(module for module, _ in imports - excepted.get(file, set()))
        for file, imports in disallowed.items()
        if imports - excepted.get(file, set())
    }
    stale = {
        file: sorted(module for module, _ in imports - disallowed.get(file, set()))
        for file, imports in excepted.items()
        if imports - disallowed.get(file, set())
    }
    assert not unexpected, f"inspect_ai.core imports disallowed modules: {unexpected}"
    assert not stale, f"remove fixed entries from KNOWN_EXCEPTIONS: {stale}"
