# Custom Tools


## Overview

Inspect natively supports registering Python functions as tools and
providing these tools to models that support them. Inspect also supports
secure sandboxes for running arbitrary code produced by models, flexible
error handling, as well as dynamic tool definitions.

We’ll cover all of these features below, but we’ll start with a very
simple example to cover the basic mechanics of tool use.

## Defining Tools

Here’s a simple tool that adds two numbers. The `@tool` decorator is
used to register it with the system:

``` python
from inspect_ai.tool import tool

@tool
def add():
    async def execute(x: int, y: int):
        """
        Add two numbers.

        Args:
            x: First number to add.
            y: Second number to add.

        Returns:
            The sum of the two numbers.
        """
        return x + y

    return execute
```

### Annotations

Note that we provide type annotations for both arguments:

``` python
async def execute(x: int, y: int)
```

Further, we provide descriptions for each parameter in the documentation
comment:

``` python
Args:
    x: First number to add.
    y: Second number to add.
```

Type annotations and descriptions are *required* for tool declarations
so that the model can be informed which types to pass back to the tool
function and what the purpose of each parameter is.

Note that you while you are required to provide default descriptions for
tools and their parameters within doc comments, you can also make these
dynamically customisable by users of your tool (see the section on [Tool
Descriptions](tools-custom.qmd#sec-tool-descriptions) for details on how
to do this).

## Using Tools

We can use the `addition()` tool in an evaluation by passing it to the
`use_tools()` Solver:

``` python
from inspect_ai import Task, task
from inspect_ai.dataset ipmort Sample
from inspect_ai.solver import generate, use_tools
from inspect_ai.scorer import match

@task
def addition_problem():
    return Task(
        dataset=[Sample(input="What is 1 + 1?", target=["2"])],
        solver=[
            use_tools(add()), 
            generate()
        ],
        scorer=match(numeric=True),
    )
```

Note that this tool doesn’t make network requests or do heavy
computation, so is fine to run as inline Python code. If your tool does
do more elaborate things, you’ll want to make sure it plays well with
Inspect’s concurrency scheme. For network requests, this amounts to
using `async` HTTP calls with `httpx`. For heavier computation, tools
should use subprocesses as described in the next section.

> [!NOTE]
>
> Note that when using tools with models, the models do not call the
> Python function directly. Rather, the model generates a structured
> request which includes function parameters, and then Inspect calls the
> function and returns the result to the model.

## Tool Errors

Various errors can occur during tool execution, especially when
interacting with the file system or network or when using [Sandbox
Environments](sandboxing.qmd) to execute code in a container sandbox. As
a tool writer you need to decide how you’d like to handle error
conditions. A number of approaches are possible:

1.  Notify the model that an error occurred to see whether it can
    recover.

2.  Catch and handle the error internally (trying another code path,
    etc.).

3.  Allow the error to propagate, resulting in the current `Sample`
    failing with an error state.

There are no universally correct approaches as tool usage and semantics
can vary widely—some rough guidelines are provided below.

### Default Handling

If you do not explicitly handle errors, then Inspect provides some
default error handling behaviour. Specifically, if any of the following
errors are raised they will be handled and reported to the model:

- `TimeoutError` — Occurs when a call to `subprocess()` or
  `sandbox().exec()` times out.

- `PermissionError` — Occurs when there are inadequate permissions to
  read or write a file.

- `UnicodeDecodeError` — Occurs when the output from executing a process
  or reading a file is binary rather than text.

- `OutputLimitExceededError` - Occurs when one or both of the output
  streams from `sandbox().exec()` exceed 10 MiB or when attempting to
  read a file over 100 MiB in size.

- `ToolError` — Special error thrown by tools to indicate they’d like to
  report an error to the model.

These are all errors that are *expected* (in fact the
`SandboxEnvironment` interface documents them as such) and possibly
recoverable by the model (try a different command, read a different
file, etc.). Unexpected errors (e.g. a network error communicating with
a remote service or container runtime) on the other hand are not
automatically handled and result in the `Sample` failing with an error.

Many tools can simply rely on the default handling to provide reasonable
behaviour around both expected and unexpected errors.

> [!NOTE]
>
> When we say that the errors are reported directly to the model, this
> refers to the behaviour when using the default `generate()`. If on the
> other hand, you are have created custom scaffolding for an agent, you
> can intercept tool errors and apply additional filtering and logic.

### Explicit Handling

In some cases a tool can implement a recovery strategy for error
conditions. For example, an HTTP request might fail due to transient
network issues, and retrying the request (perhaps after a delay) may
resolve the problem. Explicit error handling strategies are generally
applied when there are *expected* errors that are not already handled by
Inspect’s [Default Handling](#default-handling).

Another type of explicit handling is re-raising an error to bypass
Inspect’s default handling. For example, here we catch at re-raise
`TimeoutError` so that it fails the `Sample`:

``` python
try:
  result = await sandbox().exec(
    cmd=["decode", file], 
    timeout=timeout
  )
except TimeoutError:
  raise RuntimeError("Decode operation timed out.")
  
```

## Sandboxing

Tools may have a need to interact with a sandboxed environment (e.g. to
provide models with the ability to execute arbitrary bash or python
commands). The active sandbox environment can be obtained via the
`sandbox()` function. For example:

``` python
from inspect_ai.tool import ToolError, tool
from inspect_ai.util import sandbox

@tool
def list_files():
    async def execute(dir: str):
        """List the files in a directory.

        Args:
            dir: Directory

        Returns:
            File listing of the directory
        """
        result = await sandbox().exec(["ls", dir])
        if result.success:
            return result.stdout
        else:
            raise ToolError(result.stderr)

    return execute
```

The following instance methods are available to tools that need to
interact with a `SandboxEnvironment`:

``` python
class SandboxEnvironment:
   
    async def exec(
        self,
        cmd: list[str],
        input: str | bytes | None = None,
        cwd: str | None = None,
        env: dict[str, str] = {},
        user: str | None = None,
        timeout: int | None = None,
        timeout_retry: bool = True
    ) -> ExecResult[str]:
        """
        Raises:
          TimeoutError: If the specified `timeout` expires.
          UnicodeDecodeError: If an error occurs while
            decoding the command output.
          PermissionError: If the user does not have
            permission to execute the command.
          OutputLimitExceededError: If an output stream
            exceeds the 10 MiB limit.
        """
        ...

    async def write_file(
        self, file: str, contents: str | bytes
    ) -> None:
        """
        Raises:
          PermissionError: If the user does not have
            permission to write to the specified path.
          IsADirectoryError: If the file exists already and 
            is a directory.
        """
        ...

    async def read_file(
        self, file: str, text: bool = True
    ) -> Union[str | bytes]:
        """
        Raises:
          FileNotFoundError: If the file does not exist.
          UnicodeDecodeError: If an encoding error occurs 
            while reading the file.
            (only applicable when `text = True`)
          PermissionError: If the user does not have
            permission to read from the specified path.
          IsADirectoryError: If the file is a directory.
          OutputLimitExceededError: If the file size
            exceeds the 100 MiB limit.
        """
        ...

    async def connection(self, *, user: str | None = None) -> SandboxConnection:
        """
        Raises:
           NotImplementedError: For sandboxes that don't provide connections
           ConnectionError: If sandbox is not currently running.
        """
```

The `read_file()` method should preserve newline constructs (e.g. crlf
should be preserved not converted to lf). This is equivalent to
specifying `newline=""` in a call to the Python `open()` function. Note
that `write_file()` automatically creates parent directories as required
if they don’t exist.

The `connection()` method is optional, and provides commands that can be
used to login to the sandbox container from a terminal or IDE.

Note that to deal with potential unreliability of container services,
the `exec()` method includes a `timeout_retry` parameter that defaults
to `True`. For sandbox implementations this parameter is *advisory*
(they should only use it if potential unreliability exists in their
runtime). No more than 2 retries should be attempted and both with
timeouts less than 60 seconds. If you are executing commands that are
not idempotent (i.e. the side effects of a failed first attempt may
affect the results of subsequent attempts) then you can specify
`timeout_retry=False` to override this behavior.

For each method there is a documented set of errors that are raised:
these are *expected* errors and can either be caught by tools or allowed
to propagate in which case they will be reported to the model for
potential recovery. In addition, *unexpected* errors may occur (e.g. a
networking error connecting to a remote container): these errors are not
reported to the model and fail the `Sample` with an error state.

See the documentation on [Sandbox Environments](sandboxing.qmd) for
additional details.

## Stateful Tools

Some tools need to retain state across invocations (for example, the
`bash_session()` and `web_browser()` tools both interact with a stateful
remote process). You can create stateful tools by using the `store_as()`
function to access discrete storage for your tool and/or specific
instances of your tool.

For example, imagine we were creating a `web_surfer()` tool that builds
on the `web_browser()` tool to complete sequences of browser actions in
service of researching a topic. We might want to ask multiple questions
of the web surfer and have it retain its message history and browser
state.

Here’s the complete source code for this tool.

``` python
from textwrap import dedent

from pydantic import Field
from shortuuid import uuid

from inspect_ai.model import (
  ChatMessage, ChatMessageSystem, ChatMessageUser, get_model
)
from inspect_ai.tool import Tool, tool, web_browser
from inspect_ai.util import StoreModel, store_as

class WebSurferState(StoreModel):
    messages: list[ChatMessage] = Field(default_factory=list)

@tool
def web_surfer(instance: str | None = None) -> Tool:
    """Web surfer tool for researching topics.

    The web_surfer tool builds on the web_browser tool to complete
    sequences of web_browser actions in service of researching a topic.
    Input can either be requests to do research or questions about 
    previous research.
    """
    async def execute(input: str, clear_history: bool = False) -> str:
        """Use the web to research a topic.

        You may ask the web surfer any question. These questions can 
        either prompt new web searches or be clarifying or follow up 
        questions about previous web searches.

        Args:
           input: Message to the web surfer. This can be a prompt to
              do research or a question about previous research.
           clear_history: Clear memory of previous searches.

        Returns:
           Answer to research prompt or question.
        """
        # keep track of message history in the store
        surfer_state = store_as(WebSurferState, instance=instance)

        # clear history if requested.
        if clear_history:
            surfer_state.messages.clear()

        # provide system prompt if we are at the beginning
        if len(surfer_state.messages) == 0:
            surfer_state.messages.append(
                ChatMessageSystem(
                    content=dedent("""
                You are a helpful assistant that can use a browser
                to answer questions. You don't need to answer the 
                questions with a single web browser request, rather,
                you can perform searches, follow links, backtrack, 
                and otherwise use the browser to its fullest 
                capability to help answer the question.

                In some cases questions will be about your previous
                web searches, in those cases you don't always need
                to use the web browser tool but can answer by 
                consulting previous conversation messages.
                """)
                )
            )

        # append the latest question
        surfer_state.messages.append(ChatMessageUser(content=input))

        # run tool loop with web browser
        messages, output = await get_model().generate_loop(
            surfer_state.messages, tools=web_browser(instance=instance)
        )

        # update state
        surfer_state.messages.extend(messages)

        # return response
        return output.completion

    return execute
```

Note that we make available an `instance` parameter that enables
creation of multiple instances of the `web_surfer()` tool. We then pass
this `instance` to the `store_as()` function (to store our own tool’s
message history) and the `web_browser()` function (so that we also
provision a unique browser for the web surfer session).

For example, this creates a distinct instance of the `web_surfer()` with
its own state and browser:

``` python
from shortuuid import uuid

react(..., tools=[web_surfer(instance=uuid())])
```

## Tool Choice

By default models will use a tool if they think it’s appropriate for the
given task. You can override this behaviour using the `tool_choice`
parameter of the `use_tools()` Solver. For example:

``` python
# let the model decide whether to use the tool
use_tools(addition(), tool_choice="auto")

# force the use of a tool
use_tools(addition(), tool_choice=ToolFunction(name="addition"))

# prevent use of tools
use_tools(addition(), tool_choice="none")
```

The last form (`tool_choice="none"`) would typically be used to turn off
tool usage after an initial generation where the tool used. For example:

``` python
solver = [
  use_tools(addition(), tool_choice=ToolFunction(name="addition")),
  generate(),
  follow_up_prompt(),
  use_tools(tool_choice="none"),
  generate()
]
```

## Tool Descriptions

Well crafted tools should include descriptions that provide models with
the context required to use them correctly and productively. If you will
be developing custom tools it’s worth taking some time to learn how to
provide good tool definitions. Here are some resources you may find
helpful:

- [Best Practices for Tool
  Definitions](https://docs.anthropic.com/claude/docs/tool-use#best-practices-for-tool-definitions)
- [Function Calling with
  LLMs](https://www.promptingguide.ai/applications/function_calling)

In some cases you may want to change the default descriptions created by
a tool author—for example you might want to provide better
disambiguation between multiple similar tools that are used together.
You also might have need to do this during development of tools (to
explore what descriptions are most useful to models).

The `tool_with()` function enables you to take any tool and adapt its
name and/or descriptions. For example:

``` python
from inspect_ai.tool import tool_with

my_add = tool_with(
  tool=addition(), 
  name="my_add",
  description="a tool to add numbers", 
  parameters={
    "x": "the x argument",
    "y": "the y argument"
  })
```

You need not provide all of the parameters shown above, for example here
are some examples where we modify just the main tool description or only
a single parameter:

``` python
my_add1 = tool_with(addition(), description="a tool to add numbers")
my_add2 = tool_with(addition(), parameters={"x": "the x argument"})
```

Note that `tool_with()` function modifies the passed tool in-place, so
if you want to create multiple variations of a single tool using
`tool_with()` you should create the underlying tool multiple times, once
for each call to `tool_with()` (this is demonsrated in the example
above).

## Dynamic Tools

As described above, normally tools are defined using `@tool` decorators
and documentation comments. It’s also possible to create a tool
dynamically from any function by creating a `ToolDef`. For example:

``` python
from inspect_ai.solver import use_tools
from inspect_ai.tool import ToolDef

async def addition(x: int, y: int):
    return x + y

add = ToolDef(
    tool=addition,
    name="add",
    description="A tool to add numbers", 
    parameters={
        "x": "the x argument",
        "y": "the y argument"
    })
)

use_tools([add])
```

This is effectively what happens under the hood when you use the `@tool`
decorator. There is one critical requirement for functions that are
bound to tools using `ToolDef`: type annotations must be provided in the
function signature (e.g. `x: int, y: int`).

For Inspect APIs, `ToolDef` can generally be used anywhere that `Tool`
can be used (`use_tools()`, setting `state.tools`, etc.). If you are
using a 3rd party API that does not take `Tool` in its interface, use
the `ToolDef.as_tool()` method to adapt it. For example:

``` python
from inspect_agents import my_agent
agent = my_agent(tools=[add.as_tool()])
```

If on the other hand you want to get the `ToolDef` for an existing tool
(e.g. to discover its name, description, and parameters) you can just
pass the `Tool` to the `ToolDef` constructor (including whatever
overrides for `name`, etc. you want):

``` python
from inspect_ai.tool import ToolDef, bash
bash_def = ToolDef(bash())
```
