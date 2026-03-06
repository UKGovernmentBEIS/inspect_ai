from typing import Any, Literal, TypeAlias, TypedDict, get_args

from inspect_ai.tool._tool import Tool, ToolResult, tool
from inspect_ai.tool._tool_def import ToolDef
from inspect_ai.tool._tools._execute import code_viewer, python

CodeExecutionProvider: TypeAlias = Literal[
    "openai", "anthropic", "google", "grok", "mistral", "python"
]
"""Model providers that support native `code_execution()` tools."""

valid_providers = set(get_args(CodeExecutionProvider))


class CodeExecutionProviders(TypedDict, total=False):
    """Provider configuration for `code_execution()` tool.

    The `code_execution()` tool provides models the ability to execute code using an sandboxed environment. Several model providers including OpenAI, Anthropic, Google, Grok, and Mistral have native support for code execution (where code is executed on the provider's servers).

    By default, native code execution is enabled for all providers that support it. If you are using a provider that doesn't support code execution then a fallback using the `python()` tool is available. Additionally, you can optionally disable code execution for a provider with a native implementation and use the `python()` tool instead.

    Each model provider has a field that can be used to disable native code execution. For some providers (e.g. OpenAI) a `dict` of provider specific options may also be passed.

    When falling back to the `python()` provider you should ensure that your `Task` has a `sandbox` with support for executing Python code enabled.
    """

    openai: dict[str, Any] | bool
    """Use OpenAI native code interpreter. Defaults to `True`. Pass `False` to use a sandbox instead or pass a `dict` with custom options (see  <https://platform.openai.com/docs/guides/tools-code-interpreter>)."""

    anthropic: bool
    """Use Anthropoic native code execution. Defaults to `True`. Pass `False` to use a sandbox instead."""

    google: bool
    """Use Google native code execution. Defaults to `True`. Pass `False` to use a sandbox instead."""

    grok: bool
    """Use Grok native code execution. Defaults to `True`. Pass `False` to use a sandbox instead."""

    mistral: bool
    """Use Mistral native code execution. Defaults to `True`. Pass `False` to use a sandbox instead."""

    python: dict[str, Any] | bool
    """Use `python()` tool as a fallback for providers that don't support code execution. Defaults to `True`. Pass `False` to disable the fallback or pass a `dict` with `python()` tool options (`timeout` and `sandbox`)"""


@tool(viewer=code_viewer("python", "code", title="code_execution"))
def code_execution(
    *,
    providers: CodeExecutionProviders | None = None,
) -> Tool:
    """Code execution tool.

    The `code_execution()` tool provides models the ability to execute code using a sandboxed environment. Several model providers including OpenAI, Anthropic, Google, Grok, and Mistral have native support for code execution (where the code is executed on the provider's servers).

    By default, native code execution is enabled for all providers that support it. If you are using a provider that doesn't support code execution then a fallback using the `python()` tool is available. Additionally, you can optionally disable code execution for a provider with a native implementation and use the `python()` tool instead.

    The `providers` option enables selective disabling of native code execution for providers. For some providers (e.g. OpenAI) a `dict` of provider specific options may also be provided.

    When falling back to the `python()` provider you should ensure that your `Task` has a `sandbox` with support for executing Python code enabled.

    See further documentation at <https://inspect.aisi.org.uk/tools-standard.html#sec-code-execution>.

    Args:
      providers: Configuration for the code execution providers to use. Currently supported providers are "openai", "anthropic", "google", "grok", "mistral", and "python". For example:

        ```python
        # default (native interpreter for all providers, `python()` as fallback):
        code_interpreter()

        # disable native code interpeter for some providers:
        code_interpreter({ "grok": False, "openai": False })

        # disable python fallback
        code_interpreter({ "python": False })

        # provide openai container options
        code_interpreter(
            {"openai": {"container": {"type": "auto", "memory_limit": "4g" }}}
        )
        ```
    """
    # normalize various config syntaxes
    normalized_providers = _normalize_config(providers)

    # default implementation is just the python tool
    python_tool: Tool | None = None
    python_sandbox: str | None = None
    python_timeout: int | None = None
    if "python" in normalized_providers.keys():
        python_options = normalized_providers["python"]
        python_timeout = python_options.get("timeout", None)
        python_sandbox = python_options.get("sandbox", None)
        python_tool = python(timeout=python_timeout, sandbox=python_sandbox)

    async def execute(code: str) -> ToolResult:
        """
        Use the python function to execute Python code.

        The Python tool executes single-run Python scripts. Important notes:
        1. Each execution is independent - no state is preserved between runs
        2. You must explicitly use print() statements to see any output
        3. Simply writing expressions (like in notebooks) will not display results
        4. The script cannot accept interactive input during execution
        5. Return statements alone won't produce visible output
        6. All variables and imports are cleared between executions
        7. Standard output (via print()) is the only way to see results

        Args:
          code (str): The python code to execute.

        Returns:
          The output of the Python code.
        """
        if python_tool is not None:
            return await python_tool(code)
        else:
            raise RuntimeError(
                "Fallback for `code_execution()` tool requires that `python` be enabled."
            )

    return ToolDef(
        execute,
        name="code_execution",
        options=dict(providers=normalized_providers),
    ).as_tool()


class _NormalizedProviders(TypedDict, total=False):
    openai: dict[str, Any]
    anthropic: dict[str, Any]
    google: dict[str, Any]
    grok: dict[str, Any]
    mistral: dict[str, Any]
    python: dict[str, Any]


def _normalize_config(
    providers: CodeExecutionProviders | None = None,
) -> _NormalizedProviders:
    # default to all providers enabled
    normalized = _NormalizedProviders(
        openai={}, anthropic={}, google={}, grok={}, mistral={}, python={}
    )
    for provider, options in (providers or {}).items():
        # dict means explicit options
        if isinstance(options, dict):
            normalized[provider] = options  # type: ignore[literal-required]

        # False means blank it out
        elif options is False:
            normalized.pop(provider)  # type: ignore[misc]

        # else leave it alone
        else:
            pass

    return normalized
