
Here's a simple tool that adds two numbers. The `@tool` decorator is used to register it with the system:

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

{{< include _tools-annotations-required.md >}}

Note that you while you are required to provide default descriptions for tools and their parameters within doc comments, you can also make these dynamically customisable by users of your tool (see the section on [Tool Descriptions](tools-custom.qmd#sec-tool-descriptions) for details on how to do this).

## Using Tools

We can use the `addition()` tool in an evaluation by passing it to the `use_tools()` Solver:

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

Note that this tool doesn't make network requests or do heavy computation, so is fine to run as inline Python code. If your tool does do more elaborate things, you'll want to make sure it plays well with Inspect's concurrency scheme. For network requests, this amounts to using `async` HTTP calls with `httpx`. For heavier computation, tools should use subprocesses as described in the next section.

::: {.callout-note appearance="simple"}
Note that when using tools with models, the models do not call the Python function directly. Rather, the model generates a structured request which includes function parameters, and then Inspect calls the function and returns the result to the model.
:::
