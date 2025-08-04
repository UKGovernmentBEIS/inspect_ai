# inspect_ai.tool


## Tools

### bash

Bash shell command execution tool.

Execute bash shell commands using a sandbox environment (e.g. “docker”).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/tool/_tools/_execute.py#L22)

``` python
@tool(viewer=code_viewer("bash", "cmd"))
def bash(
    timeout: int | None = None, user: str | None = None, sandbox: str | None = None
) -> Tool
```

`timeout` int \| None  
Timeout (in seconds) for command.

`user` str \| None  
User to execute commands as.

`sandbox` str \| None  
Optional sandbox environment name.

### python

Python code execution tool.

Execute Python code using a sandbox environment (e.g. “docker”).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/tool/_tools/_execute.py#L62)

``` python
@tool(viewer=code_viewer("python", "code"))
def python(
    timeout: int | None = None, user: str | None = None, sandbox: str | None = None
) -> Tool
```

`timeout` int \| None  
Timeout (in seconds) for command.

`user` str \| None  
User to execute commands as.

`sandbox` str \| None  
Optional sandbox environment name.

### bash_session

Interactive bash shell session tool.

Interact with a bash shell in a long running session using a sandbox
environment (e.g. “docker”). This tool allows sending text to the shell,
which could be a command followed by a newline character or any other
input text such as the response to a password prompt.

To create a separate bash process for each call to `bash_session()`,
pass a unique value for `instance`

See complete documentation at
<https://inspect.aisi.org.uk/tools-standard.html#sec-bash-session>.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/tool/_tools/_bash_session.py#L79)

``` python
@tool()
def bash_session(
    *,
    timeout: int | None = None,  # default is max_wait + 5 seconds
    wait_for_output: int | None = None,  # default is 30 seconds
    user: str | None = None,
    instance: str | None = None,
) -> Tool
```

`timeout` int \| None  
Timeout (in seconds) for command.

`wait_for_output` int \| None  
Maximum time (in seconds) to wait for output. If no output is received
within this period, the function will return an empty string. The model
may need to make multiple tool calls to obtain all output from a given
command.

`user` str \| None  
Username to run commands as

`instance` str \| None  
Instance id (each unique instance id has its own bash process)

### text_editor

Custom editing tool for viewing, creating and editing files.

Perform text editor operations using a sandbox environment
(e.g. “docker”).

IMPORTANT: This tool does not currently support Subtask isolation. This
means that a change made to a file by on Subtask will be visible to
another Subtask.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/tool/_tools/_text_editor.py#L63)

``` python
@tool()
def text_editor(timeout: int | None = None, user: str | None = None) -> Tool
```

`timeout` int \| None  
Timeout (in seconds) for command. Defaults to 180 if not provided.

`user` str \| None  
User to execute commands as.

### web_browser

Tools used for web browser navigation.

To create a separate web browser process for each call to
`web_browser()`, pass a unique value for `instance`.

See complete documentation at
<https://inspect.aisi.org.uk/tools-standard.html#sec-web-browser>.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/tool/_tools/_web_browser/_web_browser.py#L34)

``` python
def web_browser(*, interactive: bool = True, instance: str | None = None) -> list[Tool]
```

`interactive` bool  
Provide interactive tools (enable clicking, typing, and submitting
forms). Defaults to True.

`instance` str \| None  
Instance id (each unique instance id has its own web browser process)

### computer

Desktop computer tool.

See documentation at
<https://inspect.aisi.org.uk/tools-standard.html#sec-computer>.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/tool/_tools/_computer/_computer.py#L38)

``` python
@tool
def computer(max_screenshots: int | None = 1, timeout: int | None = 180) -> Tool
```

`max_screenshots` int \| None  
The maximum number of screenshots to play back to the model as input.
Defaults to 1 (set to `None` to have no limit).

`timeout` int \| None  
Timeout in seconds for computer tool actions. Defaults to 180 (set to
`None` for no timeout).

### web_search

Web search tool.

Web searches are executed using a provider. Providers are split into two
categories:

- Internal providers: “openai”, “anthropic”, “grok”, “gemini”,
  “perplexity”. These use the model’s built-in search capability and do
  not require separate API keys. These work only for their respective
  model provider (e.g. the “openai” search provider works only for
  `openai/*` models).

- External providers: “tavily”, “google”, and “exa”. These are external
  services that work with any model and require separate accounts and
  API keys.

Internal providers will be prioritized if running on the corresponding
model (e.g., “openai” provider will be used when running on `openai`
models). If an internal provider is specified but the evaluation is run
with a different model, a fallback external provider must also be
specified.

See further documentation at
<https://inspect.aisi.org.uk/tools-standard.html#sec-web-search>.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/tool/_tools/_web_search/_web_search.py#L64)

``` python
@tool
def web_search(
    providers: Provider | Providers | list[Provider | Providers] | None = None,
    **deprecated: Unpack[WebSearchDeprecatedArgs],
) -> Tool
```

`providers` Provider \| Providers \| list\[Provider \| Providers\] \| None  
Configuration for the search providers to use. Currently supported
providers are “openai”, “anthropic”, “perplexity”, “tavily”, “gemini”,
“grok”, “google”, and “exa”. The `providers` parameter supports several
formats based on either a `str` specifying a provider or a `dict` whose
keys are the provider names and whose values are the provider-specific
options. A single value or a list of these can be passed. This arg is
optional just for backwards compatibility. New code should always
provide this argument.

Single provider:

    web_search("tavily")
    web_search({"tavily": {"max_results": 5}})  # Tavily-specific options

Multiple providers:

    # "openai" used for OpenAI models, "tavily" as fallback
    web_search(["openai", "tavily"])

    # The True value means to use the provider with default options
    web_search({"openai": True, "tavily": {"max_results": 5}}

Mixed format:

    web_search(["openai", {"tavily": {"max_results": 5}}])

When specified in the `dict` format, the `None` value for a provider
means to use the provider with default options.

Provider-specific options: - openai: Supports OpenAI’s web search
parameters. See
<https://platform.openai.com/docs/guides/tools-web-search?api-mode=responses>

- anthropic: Supports Anthropic’s web search parameters. See
  <https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/web-search-tool#tool-definition>

- perplexity: Supports Perplexity’s web search parameters. See
  <https://docs.perplexity.ai/api-reference/chat-completions-post>

- tavily: Supports options like `max_results`, `search_depth`, etc. See
  <https://docs.tavily.com/documentation/api-reference/endpoint/search>

- exa: Supports options like `text`, `model`, etc. See
  <https://docs.exa.ai/reference/answer>

- google: Supports options like `num_results`, `max_provider_calls`,
  `max_connections`, and `model`

- grok: Supports X-AI’s live search parameters. See
  <https://docs.x.ai/docs/guides/live-search#live-search>

`**deprecated` Unpack\[WebSearchDeprecatedArgs\]  
Deprecated arguments.

### think

Think tool for extra thinking.

Tool that provides models with the ability to include an additional
thinking step as part of getting to its final answer.

Note that the `think()` tool is not a substitute for reasoning and
extended thinking, but rather an an alternate way of letting models
express thinking that is better suited to some tool use scenarios.
Please see the documentation on using the [think
tool](https://inspect.aisi.org.uk/tools-standard.html#sec-think) before
using it in your evaluations.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/tool/_tools/_think.py#L6)

``` python
@tool
def think(
    description: str | None = None,
    thought_description: str | None = None,
) -> Tool
```

`description` str \| None  
Override the default description of the think tool.

`thought_description` str \| None  
Override the default description of the thought parameter.

## MCP

### mcp_connection

Context manager for running MCP servers required by tools.

Any `ToolSource` passed in tools will be examined to see if it
references an MCPServer, and if so, that server will be connected to
upon entering the context and disconnected from upon exiting the
context.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/tool/_mcp/connection.py#L11)

``` python
@contextlib.asynccontextmanager
async def mcp_connection(
    tools: Sequence[Tool | ToolDef | ToolSource] | ToolSource,
) -> AsyncIterator[None]
```

`tools` Sequence\[[Tool](inspect_ai.tool.qmd#tool) \| [ToolDef](inspect_ai.tool.qmd#tooldef) \| [ToolSource](inspect_ai.tool.qmd#toolsource)\] \| [ToolSource](inspect_ai.tool.qmd#toolsource)  
Tools in current context.

### mcp_server_stdio

MCP Server (Stdio).

Stdio interface to MCP server. Use this for MCP servers that run
locally.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/tool/_mcp/server.py#L40)

``` python
def mcp_server_stdio(
    *,
    command: str,
    args: list[str] = [],
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
) -> MCPServer
```

`command` str  
The executable to run to start the server.

`args` list\[str\]  
Command line arguments to pass to the executable.

`cwd` str \| Path \| None  
The working directory to use when spawning the process.

`env` dict\[str, str\] \| None  
The environment to use when spawning the process in addition to the
platform specific set of default environment variables (e.g. “HOME”,
“LOGNAME”, “PATH”, “SHELL”, “TERM”, and “USER” for Posix-based systems).

### mcp_server_sse

MCP Server (SSE).

SSE interface to MCP server. Use this for MCP servers available via a
URL endpoint.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/tool/_mcp/server.py#L13)

``` python
def mcp_server_sse(
    *,
    url: str,
    headers: dict[str, Any] | None = None,
    timeout: float = 5,
    sse_read_timeout: float = 60 * 5,
) -> MCPServer
```

`url` str  
URL to remote server

`headers` dict\[str, Any\] \| None  
Headers to send server (typically authorization is included here)

`timeout` float  
Timeout for HTTP operations

`sse_read_timeout` float  
How long (in seconds) the client will wait for a new event before
disconnecting.

### mcp_server_sandbox

MCP Server (Sandbox).

Interface to MCP server running in an Inspect sandbox.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/tool/_mcp/server.py#L69)

``` python
def mcp_server_sandbox(
    *,
    command: str,
    args: list[str] = [],
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
    sandbox: str | None = None,
    timeout: int | None = None,
) -> MCPServer
```

`command` str  
The executable to run to start the server.

`args` list\[str\]  
Command line arguments to pass to the executable.

`cwd` str \| Path \| None  
The working directory to use when spawning the process.

`env` dict\[str, str\] \| None  
The environment to use when spawning the process in addition to the
platform specific set of default environment variables (e.g. “HOME”,
“LOGNAME”, “PATH”, “SHELL”, “TERM”, and “USER” for Posix-based systems).

`sandbox` str \| None  
The sandbox to use when spawning the process.

`timeout` int \| None  
Timeout (in seconds) for command.

### mcp_tools

Tools from MCP server.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/tool/_mcp/tools.py#L7)

``` python
def mcp_tools(
    server: MCPServer,
    *,
    tools: Literal["all"] | list[str] = "all",
) -> ToolSource
```

`server` [MCPServer](inspect_ai.tool.qmd#mcpserver)  
MCP server created with `mcp_server_stdio()` or `mcp_server_sse()`

`tools` Literal\['all'\] \| list\[str\]  
List of tool names (or globs) (defaults to “all”) which returns all
tools.

### MCPServer

Model Context Protocol server interface.

`MCPServer` can be passed in the `tools` argument as a source of tools
(use the `mcp_tools()` function to filter the list of tools)

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/tool/_mcp/_types.py#L10)

``` python
class MCPServer(ToolSource)
```

#### Methods

tools  
List of all tools provided by this server.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/tool/_mcp/_types.py#L18)

``` python
async def tools(self) -> list[Tool]
```

## Dynamic

### tool_with

Tool with modifications to various attributes.

This function modifies the passed tool in place and returns it. If you
want to create multiple variations of a single tool using `tool_with()`
you should create the underlying tool multiple times.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/tool/_tool_with.py#L14)

``` python
def tool_with(
    tool: Tool,
    name: str | None = None,
    description: str | None = None,
    parameters: dict[str, str] | None = None,
    parallel: bool | None = None,
    viewer: ToolCallViewer | None = None,
    model_input: ToolCallModelInput | None = None,
) -> Tool
```

`tool` [Tool](inspect_ai.tool.qmd#tool)  
Tool instance to modify.

`name` str \| None  
Tool name (optional).

`description` str \| None  
Tool description (optional).

`parameters` dict\[str, str\] \| None  
Parameter descriptions (optional)

`parallel` bool \| None  
Does the tool support parallel execution (defaults to True if not
specified)

`viewer` ToolCallViewer \| None  
Optional tool call viewer implementation.

`model_input` ToolCallModelInput \| None  
Optional function that determines how tool call results are played back
as model input.

### ToolDef

Tool definition.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/tool/_tool_def.py#L36)

``` python
class ToolDef
```

#### Attributes

`tool` Callable\[..., Any\]  
Callable to execute tool.

`name` str  
Tool name.

`description` str  
Tool description.

`parameters` [ToolParams](inspect_ai.tool.qmd#toolparams)  
Tool parameter descriptions.

`parallel` bool  
Supports parallel execution.

`viewer` ToolCallViewer \| None  
Custom viewer for tool call

`model_input` ToolCallModelInput \| None  
Custom model input presenter for tool calls.

`options` dict\[str, object\] \| None  
Optional property bag that can be used by the model provider to
customize the implementation of the tool

#### Methods

\_\_init\_\_  
Create a tool definition.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/tool/_tool_def.py#L39)

``` python
def __init__(
    self,
    tool: Callable[..., Any],
    name: str | None = None,
    description: str | None = None,
    parameters: dict[str, str] | ToolParams | None = None,
    parallel: bool | None = None,
    viewer: ToolCallViewer | None = None,
    model_input: ToolCallModelInput | None = None,
    options: dict[str, object] | None = None,
) -> None
```

`tool` Callable\[..., Any\]  
Callable to execute tool.

`name` str \| None  
Name of tool. Discovered automatically if not specified.

`description` str \| None  
Description of tool. Discovered automatically by parsing doc comments if
not specified.

`parameters` dict\[str, str\] \| [ToolParams](inspect_ai.tool.qmd#toolparams) \| None  
Tool parameter descriptions and types. Discovered automatically by
parsing doc comments if not specified.

`parallel` bool \| None  
Does the tool support parallel execution (defaults to True if not
specified)

`viewer` ToolCallViewer \| None  
Optional tool call viewer implementation.

`model_input` ToolCallModelInput \| None  
Optional function that determines how tool call results are played back
as model input.

`options` dict\[str, object\] \| None  
Optional property bag that can be used by the model provider to
customize the implementation of the tool

as_tool  
Convert a ToolDef to a Tool.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/tool/_tool_def.py#L146)

``` python
def as_tool(self) -> Tool
```

## Types

### Tool

Additional tool that an agent can use to solve a task.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/tool/_tool.py#L90)

``` python
class Tool(Protocol):
    async def __call__(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> ToolResult
```

`*args` Any  
Arguments for the tool.

`**kwargs` Any  
Keyword arguments for the tool.

#### Examples

``` python
@tool
def add() -> Tool:
    async def execute(x: int, y: int) -> int:
        return x + y

    return execute
```

### ToolResult

Valid types for results from tool calls.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/tool/_tool.py#L35)

``` python
ToolResult = (
    str
    | int
    | float
    | bool
    | ContentText
    | ContentReasoning
    | ContentImage
    | ContentAudio
    | ContentVideo
    | ContentData
    | list[
        ContentText
        | ContentReasoning
        | ContentImage
        | ContentAudio
        | ContentVideo
        | ContentData
    ]
)
```

### ToolError

Exception thrown from tool call.

If you throw a `ToolError` form within a tool call, the error will be
reported to the model for further processing (rather than ending the
sample). If you want to raise a fatal error from a tool call use an
appropriate standard exception type (e.g. `RuntimeError`, `ValueError`,
etc.)

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/tool/_tool.py#L58)

``` python
class ToolError(Exception)
```

#### Methods

\_\_init\_\_  
Create a ToolError.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/tool/_tool.py#L68)

``` python
def __init__(self, message: str) -> None
```

`message` str  
Error message to report to the model.

### ToolCallError

Error raised by a tool call.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/tool/_tool_call.py#L60)

``` python
@dataclass
class ToolCallError
```

#### Attributes

`type` Literal\['parsing', 'timeout', 'unicode_decode', 'permission', 'file_not_found', 'is_a_directory', 'limit', 'approval', 'unknown', 'output_limit'\]  
Error type.

`message` str  
Error message.

### ToolChoice

Specify which tool to call.

“auto” means the model decides; “any” means use at least one tool,
“none” means never call a tool; ToolFunction instructs the model to call
a specific function.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/tool/_tool_choice.py#L13)

``` python
ToolChoice = Union[Literal["auto", "any", "none"], ToolFunction]
```

### ToolFunction

Indicate that a specific tool function should be called.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/tool/_tool_choice.py#L5)

``` python
@dataclass
class ToolFunction
```

#### Attributes

`name` str  
The name of the tool function to call.

### ToolInfo

Specification of a tool (JSON Schema compatible)

If you are implementing a ModelAPI, most LLM libraries can be passed
this object (dumped to a dict) directly as a function specification. For
example, in the OpenAI provider:

``` python
ChatCompletionToolParam(
    type="function",
    function=tool.model_dump(exclude_none=True),
)
```

In some cases the field names don’t match up exactly. In that case call
`model_dump()` on the `parameters` field. For example, in the Anthropic
provider:

``` python
ToolParam(
    name=tool.name,
    description=tool.description,
    input_schema=tool.parameters.model_dump(exclude_none=True),
)
```

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/tool/_tool_info.py#L19)

``` python
class ToolInfo(BaseModel)
```

#### Attributes

`name` str  
Name of tool.

`description` str  
Short description of tool.

`parameters` [ToolParams](inspect_ai.tool.qmd#toolparams)  
JSON Schema of tool parameters object.

`options` dict\[str, object\] \| None  
Optional property bag that can be used by the model provider to
customize the implementation of the tool

### ToolParams

Description of tool parameters object in JSON Schema format.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/tool/_tool_params.py#L14)

``` python
class ToolParams(BaseModel)
```

#### Attributes

`type` Literal\['object'\]  
Params type (always ‘object’)

`properties` dict\[str, [ToolParam](inspect_ai.tool.qmd#toolparam)\]  
Tool function parameters.

`required` list\[str\]  
List of required fields.

`additionalProperties` bool  
Are additional object properties allowed? (always `False`)

### ToolParam

Description of tool parameter in JSON Schema format.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/tool/_tool_params.py#L10)

``` python
ToolParam: TypeAlias = JSONSchema
```

### ToolSource

Protocol for dynamically providing a set of tools.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/tool/_tool.py#L117)

``` python
@runtime_checkable
class ToolSource(Protocol)
```

#### Methods

tools  
Retrieve tools from tool source.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/tool/_tool.py#L121)

``` python
async def tools(self) -> list[Tool]
```

## Decorator

### tool

Decorator for registering tools.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/29b6fc4c02eba58d77a46d5ef2ce96808fa620d8/src/inspect_ai/tool/_tool.py#L171)

``` python
def tool(
    func: Callable[P, Tool] | None = None,
    *,
    name: str | None = None,
    viewer: ToolCallViewer | None = None,
    model_input: ToolCallModelInput | None = None,
    parallel: bool = True,
    prompt: str | None = None,
) -> Callable[P, Tool] | Callable[[Callable[P, Tool]], Callable[P, Tool]]
```

`func` Callable\[P, [Tool](inspect_ai.tool.qmd#tool)\] \| None  
Tool function

`name` str \| None  
Optional name for tool. If the decorator has no name argument then the
name of the tool creation function will be used as the name of the tool.

`viewer` ToolCallViewer \| None  
Provide a custom view of tool call and context.

`model_input` ToolCallModelInput \| None  
Provide a custom function for playing back tool results as model input.

`parallel` bool  
Does this tool support parallel execution? (defaults to `True`).

`prompt` str \| None  
Deprecated (provide all descriptive information about the tool within
the tool function’s doc comment)

#### Examples

``` python
@tool
def add() -> Tool:
    async def execute(x: int, y: int) -> int:
        return x + y

    return execute
```
