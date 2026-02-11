# inspect_ai.tool


## Computing Tools

### web_search

Web search tool.

Web searches are executed using a provider. Providers are split into two
categories:

- Internal providers: “openai”, “anthropic”, “grok”, “gemini”,
  “mistral”, “perplexity”. These use the model’s built-in search
  capability and do not require separate API keys. These work only for
  their respective model provider (e.g. the “openai” search provider
  works only for `openai/*` models).

- External providers: “tavily”, “google”, and “exa”. These are external
  services that work with any model and require separate accounts and
  API keys.

By default, all internal providers are enabled if there are no external
providers defined. If an external provider is defined then you need to
explicitly enable internal providers that you want to use.

Internal providers will be prioritized if running on the corresponding
model (e.g., “openai” provider will be used when running on `openai`
models). If an internal provider is specified but the evaluation is run
with a different model, a fallback external provider must also be
specified.

See further documentation at
<https://inspect.aisi.org.uk/tools-standard.html#sec-web-search>.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/6ebcf87dc7c37bd203a9c99d69a7eda944bcfe05/src/inspect_ai/tool/_tools/_web_search/_web_search.py#L106)

``` python
@tool
def web_search(
    providers: WebSearchProvider
    | WebSearchProviders
    | list[WebSearchProvider | WebSearchProviders]
    | None = None,
    **deprecated: Unpack[WebSearchDeprecatedArgs],
) -> Tool
```

`providers` WebSearchProvider \| [WebSearchProviders](inspect_ai.tool.qmd#websearchproviders) \| list\[WebSearchProvider \| [WebSearchProviders](inspect_ai.tool.qmd#websearchproviders)\] \| None  
Configuration for the search providers to use. Currently supported
providers are “openai”, “anthropic”, “perplexity”, “tavily”, “gemini”,
“mistral”, “grok”, “google”, and “exa”. The `providers` parameter
supports several formats based on either a `str` specifying a provider
or a `dict` whose keys are the provider names and whose values are the
provider-specific options. A single value or a list of these can be
passed.

Use built-in search for all providers:

    web_search()

Single external provider:

    web_search("tavily")
    web_search({"tavily": {"max_results": 5}})  # Tavily-specific options

Multiple providers:

    # "openai" used for OpenAI models, "tavily" for other models
    web_search(["openai", "tavily"])

    # The True value means to use the provider with default options
    web_search({"openai": True, "tavily": {"max_results": 5}}

Mixed format:

    web_search(["openai", "anthropic", {"tavily": {"max_results": 5}}])

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

### bash

Bash shell command execution tool.

Execute bash shell commands using a sandbox environment (e.g. “docker”).

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/6ebcf87dc7c37bd203a9c99d69a7eda944bcfe05/src/inspect_ai/tool/_tools/_execute.py#L26)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/6ebcf87dc7c37bd203a9c99d69a7eda944bcfe05/src/inspect_ai/tool/_tools/_execute.py#L66)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/6ebcf87dc7c37bd203a9c99d69a7eda944bcfe05/src/inspect_ai/tool/_tools/_bash_session.py#L80)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/6ebcf87dc7c37bd203a9c99d69a7eda944bcfe05/src/inspect_ai/tool/_tools/_text_editor.py#L68)

``` python
@tool()
def text_editor(timeout: int | None = None, user: str | None = None) -> Tool
```

`timeout` int \| None  
Timeout (in seconds) for command. Defaults to 180 if not provided.

`user` str \| None  
User to execute commands as.

### computer

Desktop computer tool.

See documentation at
<https://inspect.aisi.org.uk/tools-standard.html#sec-computer>.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/6ebcf87dc7c37bd203a9c99d69a7eda944bcfe05/src/inspect_ai/tool/_tools/_computer/_computer.py#L39)

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

### code_execution

Code execution tool.

The `code_execution()` tool provides models the ability to execute code
using a sandboxed environment. Several model providers including OpenAI,
Anthropic, Google, Grok, and Mistral have native support for code
execution (where the code is executed on the provider’s servers).

By default, native code execution is enabled for all providers that
support it. If you are using a provider that doesn’t support code
execution then a fallback using the `python()` tool is available.
Additionally, you can optionally disable code execution for a provider
with a native implementation and use the `python()` tool instead.

The `providers` option enables selective disabling of native code
execution for providers. For some providers (e.g. OpenAI) a `dict` of
provider specific options may also be provided.

When falling back to the `python()` provider you should ensure that your
`Task` has a `sandbox` with support for executing Python code enabled.

See further documentation at
<https://inspect.aisi.org.uk/tools-standard.html#sec-code-execution>.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/6ebcf87dc7c37bd203a9c99d69a7eda944bcfe05/src/inspect_ai/tool/_tools/_code_execution.py#L46)

``` python
@tool(viewer=code_viewer("python", "code", title="code_execution"))
def code_execution(
    *,
    providers: CodeExecutionProviders | None = None,
) -> Tool
```

`providers` [CodeExecutionProviders](inspect_ai.tool.qmd#codeexecutionproviders) \| None  
Configuration for the code execution providers to use. Currently
supported providers are “openai”, “anthropic”, “google”, “grok”,
“mistral”, and “python”. For example:

``` python
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

### web_browser

Tools used for web browser navigation.

To create a separate web browser process for each call to
`web_browser()`, pass a unique value for `instance`.

See complete documentation at
<https://inspect.aisi.org.uk/tools-standard.html#sec-web-browser>.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/6ebcf87dc7c37bd203a9c99d69a7eda944bcfe05/src/inspect_ai/tool/_tools/_web_browser/_web_browser.py#L39)

``` python
def web_browser(*, interactive: bool = True, instance: str | None = None) -> list[Tool]
```

`interactive` bool  
Provide interactive tools (enable clicking, typing, and submitting
forms). Defaults to True.

`instance` str \| None  
Instance id (each unique instance id has its own web browser process)

## Agentic Tools

### skill

Make skills available to an agent.

See the `Skill` documentation for details on defining skills.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/6ebcf87dc7c37bd203a9c99d69a7eda944bcfe05/src/inspect_ai/tool/_tools/_skill/tool.py#L16)

``` python
@tool
def skill(
    skills: Sequence[str | Path | Skill],
    *,
    sandbox: str | None = None,
    user: str | None = None,
    dir: str | None = None,
) -> Tool
```

`skills` Sequence\[str \| Path \| [Skill](inspect_ai.tool.qmd#skill)\]  
Agent skill specifications. Either a directory containing a skill or a
full `Skill` specification.

`sandbox` str \| None  
Sandbox environment name to copy skills to.

`user` str \| None  
User to write skills files with.

`dir` str \| None  
Directory to install into (defaults to “./skills”).

### memory

Memory tool for managing persistent information.

The description for the memory tool is based on the documentation for
the Claude [system
prompt](https://platform.claude.com/docs/en/agents-and-tools/tool-use/memory-tool#prompting-guidance)
associated with the use of the memory tool.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/6ebcf87dc7c37bd203a9c99d69a7eda944bcfe05/src/inspect_ai/tool/_tools/_memory.py#L21)

``` python
@tool
def memory(*, initial_data: dict[str, str] | None = None) -> Tool
```

`initial_data` dict\[str, str\] \| None  
Optional dict mapping file paths to content for pre-seeding the memory
store. Keys should be valid /memories paths (e.g.,
“/memories/file.txt”). Values are resolved via resource(), supporting
inline strings, file paths, or remote resources (s3://, <https://>).
Seeding happens once on first tool execution.

### update_plan

Planning tool to track steps and progress in a longer horizon task.

The update_plan tool is based on the update_plan provided by [Codex
CLI](https://github.com/openai/codex).

The default tool description is taken from the GPT 5.1 system prompt for
Codex. Pass a custom `description` to override this.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/6ebcf87dc7c37bd203a9c99d69a7eda944bcfe05/src/inspect_ai/tool/_tools/_update_plan.py#L12)

``` python
@tool
def update_plan(description: str | None = None) -> Tool
```

`description` str \| None  
Override the default description of the update_plan tool.

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/6ebcf87dc7c37bd203a9c99d69a7eda944bcfe05/src/inspect_ai/tool/_tools/_think.py#L6)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/6ebcf87dc7c37bd203a9c99d69a7eda944bcfe05/src/inspect_ai/tool/_mcp/connection.py#L10)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/6ebcf87dc7c37bd203a9c99d69a7eda944bcfe05/src/inspect_ai/tool/_mcp/server.py#L116)

``` python
def mcp_server_stdio(
    *,
    name: str | None = None,
    command: str,
    args: list[str] | None = None,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
) -> MCPServer
```

`name` str \| None  
Human readable name for the server (defaults to `command` if not
specified)

`command` str  
The executable to run to start the server.

`args` list\[str\] \| None  
Command line arguments to pass to the executable.

`cwd` str \| Path \| None  
The working directory to use when spawning the process.

`env` dict\[str, str\] \| None  
The environment to use when spawning the process in addition to the
platform specific set of default environment variables (e.g. “HOME”,
“LOGNAME”, “PATH”, “SHELL”, “TERM”, and “USER” for Posix-based systems).

### mcp_server_http

MCP Server (SSE).

HTTP interface to MCP server. Use this for MCP servers available via a
URL endpoint.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/6ebcf87dc7c37bd203a9c99d69a7eda944bcfe05/src/inspect_ai/tool/_mcp/server.py#L67)

``` python
def mcp_server_http(
    *,
    name: str | None = None,
    url: str,
    execution: Literal["local", "remote"] = "local",
    authorization: str | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 5,
    sse_read_timeout: float = 60 * 5,
) -> MCPServer
```

`name` str \| None  
Human readable name for the server (defaults to `url` if not specified)

`url` str  
URL to remote server

`execution` Literal\['local', 'remote'\]  
Where to execute tool call (“local” for within the Inspect process,
“remote” for execution by the model provider – note this is currently
only supported by OpenAI and Anthropic).

`authorization` str \| None  
OAuth Bearer token for authentication with server.

`headers` dict\[str, str\] \| None  
Headers to send server (typically authorization is included here)

`timeout` float  
Timeout for HTTP operations

`sse_read_timeout` float  
How long (in seconds) the client will wait for a new event before
disconnecting.

### mcp_server_sandbox

MCP Server (Sandbox).

Interface to MCP server running in an Inspect sandbox.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/6ebcf87dc7c37bd203a9c99d69a7eda944bcfe05/src/inspect_ai/tool/_mcp/server.py#L153)

``` python
def mcp_server_sandbox(
    *,
    name: str | None = None,
    command: str,
    args: list[str] | None = None,
    cwd: str | Path | None = None,
    env: dict[str, str] | None = None,
    sandbox: str | None = None,
    timeout: int | None = None,
) -> MCPServer
```

`name` str \| None  
Human readable name for server (defaults to `command` with args if not
specified).

`command` str  
The executable to run to start the server.

`args` list\[str\] \| None  
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

### mcp_server_sse

MCP Server (SSE).

SSE interface to MCP server. Use this for MCP servers available via a
URL endpoint.

NOTE: The SEE interface has been
[deprecated](https://mcp-framework.com/docs/Transports/sse/) in favor of
`mcp_server_http()` for MCP servers at URL endpoints.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/6ebcf87dc7c37bd203a9c99d69a7eda944bcfe05/src/inspect_ai/tool/_mcp/server.py#L15)

``` python
def mcp_server_sse(
    *,
    name: str | None = None,
    url: str,
    execution: Literal["local", "remote"] = "local",
    authorization: str | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 5,
    sse_read_timeout: float = 60 * 5,
) -> MCPServer
```

`name` str \| None  
Human readable name for the server (defaults to `url` if not specified)

`url` str  
URL to remote server

`execution` Literal\['local', 'remote'\]  
Where to execute tool call (“local” for within the Inspect process,
“remote” for execution by the model provider – note this is currently
only supported by OpenAI and Anthropic).

`authorization` str \| None  
OAuth Bearer token for authentication with server.

`headers` dict\[str, str\] \| None  
Headers to send server (typically authorization is included here)

`timeout` float  
Timeout for HTTP operations

`sse_read_timeout` float  
How long (in seconds) the client will wait for a new event before
disconnecting.

### mcp_tools

Tools from MCP server.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/6ebcf87dc7c37bd203a9c99d69a7eda944bcfe05/src/inspect_ai/tool/_mcp/tools.py#L10)

``` python
def mcp_tools(
    server: MCPServer,
    *,
    tools: Literal["all"] | list[str] = "all",
) -> ToolSource
```

`server` [MCPServer](inspect_ai.tool.qmd#mcpserver)  
MCP server created with `mcp_server_stdio()`, `mcp_server_http()`, or
`mcp_server_sandbox()`.

`tools` Literal\['all'\] \| list\[str\]  
List of tool names (or globs) (defaults to “all”) which returns all
tools.

### MCPServer

Model Context Protocol server interface.

`MCPServer` can be passed in the `tools` argument as a source of tools
(use the `mcp_tools()` function to filter the list of tools)

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/6ebcf87dc7c37bd203a9c99d69a7eda944bcfe05/src/inspect_ai/tool/_mcp/_types.py#L10)

``` python
class MCPServer(ToolSource, AbstractAsyncContextManager["MCPServer"])
```

#### Methods

tools  
List of all tools provided by this server

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/6ebcf87dc7c37bd203a9c99d69a7eda944bcfe05/src/inspect_ai/tool/_mcp/_types.py#L17)

``` python
@abc.abstractmethod
async def tools(self) -> list[Tool]
```

### MCPServerConfig

Configuration for MCP server.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/6ebcf87dc7c37bd203a9c99d69a7eda944bcfe05/src/inspect_ai/tool/_mcp/_config.py#L7)

``` python
class MCPServerConfig(BaseModel)
```

#### Attributes

`type` Literal\['stdio', 'http', 'sse'\]  
Server type.

`name` str  
Human readable server name.

`tools` Literal\['all'\] \| list\[str\]  
Tools to make available from server (“all” for all tools).

### MCPServerConfigStdio

Configuration for MCP servers with stdio interface.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/6ebcf87dc7c37bd203a9c99d69a7eda944bcfe05/src/inspect_ai/tool/_mcp/_config.py#L22)

``` python
class MCPServerConfigStdio(MCPServerConfig)
```

#### Attributes

`type` Literal\['stdio'\]  
Server type.

`command` str  
The executable to run to start the server.

`args` list\[str\]  
Command line arguments to pass to the executable.

`cwd` str \| Path \| None  
The working directory to use when spawning the process.

`env` dict\[str, str\] \| None  
The environment to use when spawning the process in addition to the
platform specific set of default environment variables (e.g. “HOME”,
“LOGNAME”, “PATH”,“SHELL”, “TERM”, and “USER” for Posix-based systems)

### MCPServerConfigHTTP

Conifguration for MCP servers with HTTP interface.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/6ebcf87dc7c37bd203a9c99d69a7eda944bcfe05/src/inspect_ai/tool/_mcp/_config.py#L41)

``` python
class MCPServerConfigHTTP(MCPServerConfig)
```

#### Attributes

`type` Literal\['http', 'sse'\]  
Server type.

`url` str  
URL for remote server.

`headers` dict\[str, str\] \| None  
Headers for remote server (type “http” or “sse”)

## Skills

### skill

Make skills available to an agent.

See the `Skill` documentation for details on defining skills.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/6ebcf87dc7c37bd203a9c99d69a7eda944bcfe05/src/inspect_ai/tool/_tools/_skill/tool.py#L16)

``` python
@tool
def skill(
    skills: Sequence[str | Path | Skill],
    *,
    sandbox: str | None = None,
    user: str | None = None,
    dir: str | None = None,
) -> Tool
```

`skills` Sequence\[str \| Path \| [Skill](inspect_ai.tool.qmd#skill)\]  
Agent skill specifications. Either a directory containing a skill or a
full `Skill` specification.

`sandbox` str \| None  
Sandbox environment name to copy skills to.

`user` str \| None  
User to write skills files with.

`dir` str \| None  
Directory to install into (defaults to “./skills”).

### read_skills

Read skill specifications.

See the [agent skills
specification](https://agentskills.io/specification) for details on
defining skills.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/6ebcf87dc7c37bd203a9c99d69a7eda944bcfe05/src/inspect_ai/tool/_tools/_skill/read.py#L10)

``` python
def read_skills(skills: Sequence[str | Path | Skill]) -> list[Skill]
```

`skills` Sequence\[str \| Path \| [Skill](inspect_ai.tool.qmd#skill)\]  
Directories containing SKILL.md files.

### install_skills

Install skills into a sandbox.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/6ebcf87dc7c37bd203a9c99d69a7eda944bcfe05/src/inspect_ai/tool/_tools/_skill/install.py#L11)

``` python
async def install_skills(
    skills: Sequence[str | Path | Skill],
    sandbox: str | SandboxEnvironment | None = None,
    user: str | None = None,
    dir: str | None = None,
) -> list[SkillInfo]
```

`skills` Sequence\[str \| Path \| [Skill](inspect_ai.tool.qmd#skill)\]  
Agent skills to install.

`sandbox` str \| [SandboxEnvironment](inspect_ai.util.qmd#sandboxenvironment) \| None  
Sandbox environment name to copy skills to.

`user` str \| None  
User to write skills files with.

`dir` str \| None  
Directory to install into (defaults to “./skills”).

### Skill

Agent skill specification.

See <https://agentskills.io/specification> for additional details.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/6ebcf87dc7c37bd203a9c99d69a7eda944bcfe05/src/inspect_ai/tool/_tools/_skill/types.py#L8)

``` python
class Skill(BaseModel)
```

#### Attributes

`name` str  
Skill name. Max 64 characters. Lowercase letters, numbers, and hyphens
only. Must not start or end with a hyphen.

`description` str  
Describes what the skill does and when to use it. Max 1024 characters.

`instructions` str  
Skill instructions.

Information agents need to perform the task effectively including
step-by-step instructions, examples of inputs and outputs, and common
edge cases.

Note that the agent will load this entire file once it’s decided to
activate a skill so you should try to keep it under 500 lines long. You
can break additional information into scripts/, references/ and assets/
directories.

If you do use scripts/, references/, etc. you should mention them
explicitly in the `instructions` so models know to read them as
required.

`scripts` dict\[str, str \| bytes \| Path\]  
Executable code that agents can run.

Scripts should:

- Be self-contained or clearly document dependencies
- Include helpful error messages
- Handle edge cases gracefully

Supported languages depend on the agent implementation. Common options
include Python, Bash, and JavaScript.

`references` dict\[str, str \| bytes \| Path\]  
Additional documentation that agents can read when needed.

- REFERENCE.md - Detailed technical reference
- FORMS.md - Form templates or structured data formats
- Domain-specific files (finance.md, legal.md, etc.)

Keep individual reference files focused. Agents load these on demand, so
smaller files mean less use of context.

`assets` dict\[str, str \| bytes \| Path\]  
Static resources.

- Templates (document templates, configuration templates)
- Images (diagrams, examples)
- Data files (lookup tables, schemas)

`license` str \| None  
License name or reference to a bundled license file.

`compatibility` str \| None  
Indicates environment requirements (intended product, system packages,
network access, etc.). Max 500 characters.

`metadata` dict\[str, JsonValue\] \| None  
Arbitrary key-value mapping for additional metadata.

`allowed_tools` str \| None  
Space-delimited list of pre-approved tools the skill may use.
(Experimental).

#### Methods

skill_md  
Render the skill as SKILL.md content.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/6ebcf87dc7c37bd203a9c99d69a7eda944bcfe05/src/inspect_ai/tool/_tools/_skill/types.py#L73)

``` python
def skill_md(self) -> str
```

### SkillInfo

Agent skill info.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/6ebcf87dc7c37bd203a9c99d69a7eda944bcfe05/src/inspect_ai/tool/_tools/_skill/types.py#L99)

``` python
class SkillInfo(BaseModel)
```

#### Attributes

`name` str  
Skill name. Max 64 characters. Lowercase letters, numbers, and hyphens
only. Must not start or end with a hyphen.

`description` str  
Describes what the skill does and when to use it. Max 1024 characters.

`instructions` str  
Skill instructions.

`location` str  
Full path to skill description file (SKILL.md)

## Dynamic

### tool_with

Tool with modifications to various attributes.

This function modifies the passed tool in place and returns it. If you
want to create multiple variations of a single tool using `tool_with()`
you should create the underlying tool multiple times.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/6ebcf87dc7c37bd203a9c99d69a7eda944bcfe05/src/inspect_ai/tool/_tool_with.py#L14)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/6ebcf87dc7c37bd203a9c99d69a7eda944bcfe05/src/inspect_ai/tool/_tool_def.py#L36)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/6ebcf87dc7c37bd203a9c99d69a7eda944bcfe05/src/inspect_ai/tool/_tool_def.py#L39)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/6ebcf87dc7c37bd203a9c99d69a7eda944bcfe05/src/inspect_ai/tool/_tool_def.py#L146)

``` python
def as_tool(self) -> Tool
```

## Types

### Tool

Additional tool that an agent can use to solve a task.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/6ebcf87dc7c37bd203a9c99d69a7eda944bcfe05/src/inspect_ai/tool/_tool.py#L80)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/6ebcf87dc7c37bd203a9c99d69a7eda944bcfe05/src/inspect_ai/tool/_tool.py#L34)

``` python
ToolResult = (
    str
    | int
    | float
    | bool
    | ContentText
    | ContentImage
    | ContentAudio
    | ContentVideo
    | list[ContentText | ContentImage | ContentAudio | ContentVideo]
)
```

### ToolError

Exception thrown from tool call.

If you throw a `ToolError` form within a tool call, the error will be
reported to the model for further processing (rather than ending the
sample). If you want to raise a fatal error from a tool call use an
appropriate standard exception type (e.g. `RuntimeError`, `ValueError`,
etc.)

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/6ebcf87dc7c37bd203a9c99d69a7eda944bcfe05/src/inspect_ai/tool/_tool.py#L48)

``` python
class ToolError(Exception)
```

#### Methods

\_\_init\_\_  
Create a ToolError.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/6ebcf87dc7c37bd203a9c99d69a7eda944bcfe05/src/inspect_ai/tool/_tool.py#L58)

``` python
def __init__(self, message: str) -> None
```

`message` str  
Error message to report to the model.

### ToolCallError

Error raised by a tool call.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/6ebcf87dc7c37bd203a9c99d69a7eda944bcfe05/src/inspect_ai/tool/_tool_call.py#L66)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/6ebcf87dc7c37bd203a9c99d69a7eda944bcfe05/src/inspect_ai/tool/_tool_choice.py#L13)

``` python
ToolChoice = Union[Literal["auto", "any", "none"], ToolFunction]
```

### ToolFunction

Indicate that a specific tool function should be called.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/6ebcf87dc7c37bd203a9c99d69a7eda944bcfe05/src/inspect_ai/tool/_tool_choice.py#L5)

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

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/6ebcf87dc7c37bd203a9c99d69a7eda944bcfe05/src/inspect_ai/tool/_tool_info.py#L19)

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

`options` dict\[str, Any\] \| None  
Optional property bag that can be used by the model provider to
customize the implementation of the tool

### ToolParams

Description of tool parameters object in JSON Schema format.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/6ebcf87dc7c37bd203a9c99d69a7eda944bcfe05/src/inspect_ai/tool/_tool_params.py#L15)

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

`additionalProperties` Optional\[[JSONSchema](inspect_ai.util.qmd#jsonschema)\] \| bool  
Are additional object properties allowed?

### ToolParam

Description of tool parameter in JSON Schema format.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/6ebcf87dc7c37bd203a9c99d69a7eda944bcfe05/src/inspect_ai/tool/_tool_params.py#L11)

``` python
ToolParam: TypeAlias = JSONSchema
```

### ToolSource

Protocol for dynamically providing a set of tools.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/6ebcf87dc7c37bd203a9c99d69a7eda944bcfe05/src/inspect_ai/tool/_tool.py#L107)

``` python
@runtime_checkable
class ToolSource(Protocol)
```

#### Methods

tools  
Retrieve tools from tool source.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/6ebcf87dc7c37bd203a9c99d69a7eda944bcfe05/src/inspect_ai/tool/_tool.py#L111)

``` python
async def tools(self) -> list[Tool]
```

### WebSearchProviders

Provider configuration for `web_search()` tool.

The `web_search()` tool provides models the ability to enhance their
context window by performing a search. Web searches are executed using a
provider. Providers are split into two categories:

- Internal providers: `"openai"`, `"anthropic"`, `"gemini"`, `"grok"`,
  `mistral`, and `"perplexity"` - these use the model’s built-in search
  capability and do not require separate API keys. These work only for
  their respective model provider (e.g. the “openai” search provider
  works only for `openai/*` models).

- External providers: `"tavily"`, `"exa"`, and `"google"`. These are
  external services that work with any model and require separate
  accounts and API keys. Note that “google” is different from “gemini” -
  “google” refers to Google’s Programmable Search Engine service, while
  “gemini” refers to Google’s built-in search capability for Gemini
  models.

By default, all internal providers are enabled if there are no external
providers defined. If an external provider is defined then you need to
explicitly enable internal providers that you want to use.

Internal providers will be prioritized if running on the corresponding
model (e.g., “openai” provider will be used when running on `openai`
models). If an internal provider is specified but the evaluation is run
with a different model, a fallback external provider must also be
specified.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/6ebcf87dc7c37bd203a9c99d69a7eda944bcfe05/src/inspect_ai/tool/_tools/_web_search/_web_search.py#L42)

``` python
class WebSearchProviders(TypedDict, total=False)
```

#### Attributes

`openai` dict\[str, Any\] \| bool  
Use OpenAI internal provider. For available options see
<https://platform.openai.com/docs/guides/tools-web-search?api-mode=responses>.

`anthropic` dict\[str, Any\] \| bool  
Use Anthropic internal provider. For available options see
<https://docs.anthropic.com/en/docs/agents-and-tools/tool-use/web-search-tool>.

`grok` dict\[str, Any\] \| bool  
Use Grok internal provider. For available options see
<https://docs.x.ai/docs/guides/tools/search-tools#web-search-parameters>.

`gemini` dict\[str, Any\] \| bool  
Use Gemini internal provider. For available options see
<https://ai.google.dev/gemini-api/docs/google-search>.

`mistral` dict\[str, Any\] \| bool  
Use Mistral internal provider. For available options see
<https://docs.mistral.ai/agents/tools/built-in/websearch>.

`perplexity` dict\[str, Any\] \| bool  
Use Perplexity internal provider. For available options see
<https://docs.perplexity.ai/api-reference/chat-completions-post>

`tavily` dict\[str, Any\] \| bool  
Use Tavili external provider. For available options see \<Use Exa
external provider. For available options see
<https://inspect.aisi.org.uk/tools-standard.html#tavili-options>.

`google` dict\[str, Any\] \| bool  
Use Google external provider. For available options see
<https://inspect.aisi.org.uk/tools-standard.html#google-options>.

`exa` dict\[str, Any\] \| bool  
Use Exa external provider. For available options see
<https://inspect.aisi.org.uk/tools-standard.html#exa-options>.

### CodeExecutionProviders

Provider configuration for `code_execution()` tool.

The `code_execution()` tool provides models the ability to execute code
using an sandboxed environment. Several model providers including
OpenAI, Anthropic, Google, Grok, and Mistral have native support for
code execution (where code is executed on the provider’s servers).

By default, native code execution is enabled for all providers that
support it. If you are using a provider that doesn’t support code
execution then a fallback using the `python()` tool is available.
Additionally, you can optionally disable code execution for a provider
with a native implementation and use the `python()` tool instead.

Each model provider has a field that can be used to disable native code
execution. For some providers (e.g. OpenAI) a `dict` of provider
specific options may also be passed.

When falling back to the `python()` provider you should ensure that your
`Task` has a `sandbox` with support for executing Python code enabled.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/6ebcf87dc7c37bd203a9c99d69a7eda944bcfe05/src/inspect_ai/tool/_tools/_code_execution.py#L15)

``` python
class CodeExecutionProviders(TypedDict, total=False)
```

#### Attributes

`openai` dict\[str, Any\] \| bool  
Use OpenAI native code interpreter. Defaults to `True`. Pass `False` to
use a sandbox instead or pass a `dict` with custom options (see
<https://platform.openai.com/docs/guides/tools-code-interpreter>).

`anthropic` bool  
Use Anthropoic native code execution. Defaults to `True`. Pass `False`
to use a sandbox instead.

`google` bool  
Use Google native code execution. Defaults to `True`. Pass `False` to
use a sandbox instead.

`grok` bool  
Use Grok native code execution. Defaults to `True`. Pass `False` to use
a sandbox instead.

`mistral` bool  
Use Mistral native code execution. Defaults to `True`. Pass `False` to
use a sandbox instead.

`python` dict\[str, Any\] \| bool  
Use `python()` tool as a fallback for providers that don’t support code
execution. Defaults to `True`. Pass `False` to disable the fallback or
pass a `dict` with `python()` tool options (`timeout` and `sandbox`)

## Decorator

### tool

Decorator for registering tools.

[Source](https://github.com/UKGovernmentBEIS/inspect_ai/blob/6ebcf87dc7c37bd203a9c99d69a7eda944bcfe05/src/inspect_ai/tool/_tool.py#L161)

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
