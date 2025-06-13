# Tool Basics


## Overview

Many models now have the ability to interact with client-side Python
functions in order to expand their capabilities. This enables you to
equip models with your own set of custom tools so they can perform a
wider variety of tasks.

Inspect natively supports registering Python functions as tools and
providing these tools to models that support them. Inspect also includes
several standard tools for code execution, text editing, computer use,
web search, and web browsing.

> [!NOTE]
>
> ### Tools and Agents
>
> One application of tools is to run them within an agent scaffold that
> pursues an objective over multiple interactions with a model. The
> scaffold uses the model to help make decisions about which tools to
> use and when, and orchestrates calls to the model to use the tools.
> This is covered in more depth in the [Agents](agents.qmd) section.

## Standard Tools

Inspect has several standard tools built-in, including:

- [Web Search](tools-standard.qmd#sec-web-search), which uses a search
  provider (either built in to the model or external) to execute and
  summarize web searches.

- [Bash and Python](tools-standard.qmd#sec-bash-and-python) for
  executing arbitrary shell and Python code.

- [Bash Session](tools-standard.qmd#sec-bash-session) for creating a
  stateful bash shell that retains its state across calls from the
  model.

- [Text Editor](tools-standard.qmd#sec-text-editor) which enables
  viewing, creating and editing text files.

- [Web Browser](tools-standard.qmd#sec-web-browser), which provides the
  model with a headless Chromium web browser that supports navigation,
  history, and mouse/keyboard interactions.

- [Computer](tools-standard.qmd#sec-computer), which provides the model
  with a desktop computer (viewed through screenshots) that supports
  mouse and keyboard interaction.

- [Think](tools-standard.qmd#sec-think), which provides models the
  ability to include an additional thinking step as part of getting to
  its final answer.

If you are only interested in using the standard tools, check out their
respective documentation links above. To learn more about creating your
own tools read on below.

## MCP Tools

The [Model Context
Protocol](https://modelcontextprotocol.io/introduction) is a standard
way to provide capabilities to LLMs. There are hundreds of [MCP
Servers](https://github.com/modelcontextprotocol/servers) that provide
tools for a myriad of purposes including web search and browsing,
filesystem interaction, database access, git, and more.

Tools exposed by MCP servers can be easily integrated into Inspect.
Learn more in the article on [MCP Tools](tools-mcp.qmd).

## Custom Tools

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

See the [Custom Tools](tools-custom.qmd) article for details on more
advanced custom tool features including sandboxing, error handling, and
dynamic tool definitions.

## Learning More

- [Standard Tools](tools-standard.qmd) describes Inspect’s built-in
  tools for code execution, text editing computer use, web search, and
  web browsing.

- [MCP Tools](tools-mcp.qmd) covers how to intgrate tools from the
  growing list of [Model Context
  Protocol](https://modelcontextprotocol.io/introduction) providers.

- [Custom Tools](tools-custom.qmd) provides details on more advanced
  custom tool features including sandboxing, error handling, and dynamic
  tool definitions.
