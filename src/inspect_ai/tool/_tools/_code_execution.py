from typing import Any, Literal, TypeAlias, TypedDict, get_args

from inspect_ai.tool._tool import Tool, ToolResult, tool
from inspect_ai.tool._tool_def import ToolDef
from inspect_ai.tool._tools._execute import bash, code_viewer

CodeExecutionProvider: TypeAlias = Literal[
    "openai", "anthropic", "google", "grok", "bash"
]
"""Model providers that support native `code_execution()` tools."""

valid_providers = set(get_args(CodeExecutionProvider))


class CodeExecutionProviders(TypedDict, total=False):
    """Provider configuration for `code_execution()` tool.

    The `code_execution()` tool provides models the ability to execute code using an sandboxed environment. Several model providers including OpenAI, Anthropic, Google, and Grok have native support for code execution (where code is executed on the provider's servers).

    By default, native code execution is enabled for all providers that support it. If you are using a provider that doesn't support code execution then a fallback using the `bash()` tool is available. Additionally, you can optionally disable code execution for a provider with a native implementation and use the `bash()` tool instead.

    Each model provider has a field that can be used to disable native code execution. For some providers (e.g. OpenAI) a `dict` of provider specific options may also be passed.

    When falling back to the `bash()` provider you should ensure that your `Task` has a `sandbox` enabled.
    """

    openai: dict[str, Any] | bool
    """Use OpenAI native code interpreter. Defaults to `True`. Pass `False` to use a sandbox instead or pass a `dict` of OpenAI container options (see  <https://platform.openai.com/docs/guides/tools-code-interpreter> options)."""

    anthropic: bool
    """Use Anthropoic native code execution. Defaults to `True`. Pass `False` to use a sandbox instead."""

    google: bool
    """Use Google native code execution. Defaults to `True`. Pass `False` to use a sandbox instead."""

    grok: bool
    """Use Grok native code execution. Defaults to `True`. Pass `False` to use a sandbox instead."""

    bash: dict[str, Any] | bool
    """Use `bash()` tool as a fallback for providers that don't support code execution. Defaults to `True`. Pass `False` to disable the fallback or pass a `dict` with `bash()` tool options (`timeout` and `sandbox`)"""


@tool(viewer=code_viewer("python", "cmd", title="code_execution"))
def code_execution(
    *,
    providers: CodeExecutionProviders | None = None,
) -> Tool:
    """Code execution tool.

    The `code_execution()` tool provides models the ability to execute code using a sandboxed environment. Several model providers including OpenAI, Anthropic, Google, and Grok have native support for code execution (where the code is executed on the provider's servers).

    By default, native code execution is enabled for all providers that support it. If you are using a provider that doesn't support code execution then a fallback using the `bash()` tool is available. Additionally, you can optionally disable code execution for a provider with a native implementation and use the `bash()` tool instead.

    The `providers` option enables selective disabling of native code execution for providers. For some providers (e.g. OpenAI) a `dict` of provider specific options may also be provided.

    When falling back to the `bash()` provider you should ensure that your `Task` has a `sandbox` enabled.

    See further documentation at <https://inspect.aisi.org.uk/tools-standard.html#sec-code-execution>.

    Args:
      providers: Configuration for the code execution providers to use. Currently supported providers are "openai", "anthropic", "google", "grok", and "bash". For example:

        ```python
        # default (native interpreter for all providers, `bash` as fallback):
        code_interpeter()

        # disable native code interpeter for some providers:
        code_interpeter({ "grok": False, "openai": False })

        # disable bash fallback
        code_interpeter({ "bash": False })

        # provide openai container options
        code_interpeter({ "openai" { "memory_limit": "4g" }})

        # provider openai options and disable bash fallback
        code_interpeter({ "openai" { "memory_limit": "4g" }, "bash": False })
        ```
    """
    # normalize various config syntaxes
    normalized_providers = _normalize_config(providers)

    # default implementation is just the bash tool
    bash_tool: Tool | None = None
    bash_sandbox: str | None = None
    bash_timeout: int | None = None
    if "bash" in normalized_providers.keys():
        bash_options = normalized_providers["bash"]
        bash_timeout = bash_options.get("timeout", None)
        bash_sandbox = bash_options.get("sandbox", None)
        bash_tool = bash(timeout=bash_timeout, sandbox=bash_sandbox)

    async def execute(cmd: str) -> ToolResult:
        """
        Use this function to execute bash commands.

        Args:
          cmd: The bash command to execute.

        Returns:
          The output of the command.
        """
        if bash_tool is not None:
            return await bash_tool(cmd)
        else:
            raise RuntimeError(
                "Fallback for `code_execution()` tool requires that `bash` be enabled."
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
    bash: dict[str, Any]


def _normalize_config(
    providers: CodeExecutionProviders | None = None,
) -> _NormalizedProviders:
    # default to all providers enabled
    normalized = _NormalizedProviders(
        openai={}, anthropic={}, google={}, grok={}, bash={}
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
