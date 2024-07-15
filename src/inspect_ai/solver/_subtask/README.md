# Inspect Low-Level Solver APIs

## Overview

This document describes some new features aimed at improving the development and observability of complex agent evals. Taken together, these capabilities constitute a "low-level" Sovler API that affords full control over execution and model interactions. This is intended to compliment the "high-level" Solver API which assumes a more linear model interaction history and relies on the default `generate()` function and tool use loop.

Our goal is to identify the lower level capabilities common to agent frameworks and provide an inspect-native implementation of them. The hope is that this will enable both "bare metal" agent development (just using Inspect w/ no extra libraries) as well as free higher level agent frameworks from many lower level concerns (e.g. state-tracking, observability, managing sub-agents, etc.). Ideally, core agents could be implemented using Inspect primitives only, and then be re-used in both bare-metal evals as well as evals that use additional abstractions from an agent framework.

You can find the initial implementation of these features on the [feature/subtasks](https://github.com/AI-Safety-Institute/inspect_ai/tree/feature/subtasks) branch.

## Tool Use

Previously, tool use in Inspect required the use of the higher level `generate()` function passed to solvers. We've now refactored things so that its easy to code the equivalent of the `generate()` function even when using lower-level direct interactions w/ LLMs. For example:

``` python
model = get_model()
output = await model.generate(messages, tools)
messages.append(output.message)
messages.extend(call_tools(output.message, tools))
```

This does everything that default `generate()` does (save for the outer loop). You could implement the outer loop as follows:

``` python
model = get_model()
while True:
    output = await model.generate(messages, tools)
    messages.append(output.message)
    if output.message.tool_calls:
        messages.extend(call_tools(output.message, tools))
    else:
        break
```

One additional change made to facilitate implementing the equivalent of `generate()` is that when calling `get_model()` with no parameters to get the "active" model, the `model` instance you get back will use the evaluation's default `GenerateConfig` (e.g. `temperature`, `top_p`, etc.). Note that previously you needed to call the higher level `generate()` passed to Solvers to have this configuration applied.

## Store

The `Store` is intended as a replacement for reading/writing to `state.metadata`. It includes better facilities for default values and has a clean mechanism for use within tools. The `Store` is also designed to play well with [Transcripts](#transcripts) and [Subtasks](#subtasks) (both described below). The core of the `Store` interface is:

``` python
from inspect_ai.solver import Store

class Store:
    def get(self, key: str, default: VT) -> VT
    def set(self, key: str, value: Any) -> None
    def delete(self, key: str) -> None
```

Basic views on the store's collection (e.g. `items()`, `keys()`, `values()`) are also provided. Note that the `get()` method will automatically add the `default` to the store if it doesn't exist.

The `Store` can be accessed via `TaskState` as follows:

``` python
history = state.store.get("history", [])
```

It is also possible the access the `Store` *for the current sample* using the `store()` function. This is the mechanism for tools to read and write the `Store`. For example:

``` python
from inspect_ai.solver import store
from inspect_ai.tool import tool

@tool
def web_browser_back():
   def execute() -> str:
       history = store().get("web_browser:history", [])
       return history.pop()
```

While there is no formal namespacing mechanism for the `Store`, this can be informally achieved using key prefixes as demonstrated above.

See [store.py](https://github.com/AI-Safety-Institute/inspect_ai/blob/feature/subtasks/src/inspect_ai/solver/_subtask/store.py) for the full implementation of `Store`.

## Transcripts

The current Inspect logs only record the final state of the message history, which for complex evals that re-write the message history tells you very little about "what happened" during the execution of the sample. Transcripts are intended to provide a rich per-sample view of everything that occurred. Transcripts consist of a list of events, here are the core events that are recorded:

| Event | Description |
|------------------------------------|------------------------------------|
| `StateEvent` | Records changes (in [JSON Patch](https://jsonpatch.com/) format) to `TaskState` that occur within a `Solver`. |
| `ModelEvent` | Records LLM calls (including input message, tools, config, and model output). |
| `LoggerEvent` | Records calls to the Python logger (e.g. `logger.warning("warn)`). |
| `StepEvent` | Deliniates "steps" in an eval. By default a step is created for each `Solver` but you can also add your own steps. |

The plan is to replace the default "Messages" view in the Inspect log viewer with a "Transcript" view that provides much better visibility into what actually occurred during execution. These are the core events, there are additionally `InfoEvent`, `StepEvent`, `StoreEvent`, and `SubtaskEvent` which are described below.

### Custom Info

You can insert custom entries into the transcript via the Transcipt `info()` method (which creates an `InfoEvent`). Access the transcript for the current sample using the `transcript()` function, for example:

``` python
from inspect_ai.solver import transcript

transcript().info("here is some custom info")
```

You can pass arbitrary JSON serialisable objects to `info()` (we will likely want to create a mechanism for rich display of this data within the log viewer):

### Grouping with Steps

You can create arbitrary groupings of transcript activity using the Transcript `step()` context manager. For example:

``` python
with transcript().step("reasoning"):
    ...
    state.store.set("next-action", next_action)
```

There are two reasons that you might want to create steps:

1.  Any changes to the store which occur during a step will be collected into a `StoreEvent` that records the changes (in [JSON Patch](https://jsonpatch.com/) format) that occurred.
2.  The Inspect log viewer will create a visual delination for the step, which will make it easier to see the flow of activity within the transcript.

See [transcript.py](https://github.com/AI-Safety-Institute/inspect_ai/blob/feature/subtasks/src/inspect_ai/solver/_subtask/transcript.py) for the full implementation of `Transcript`.

## Subtasks

Subtasks provide a mechanism for creating isolated, re-usable units of execution. You might implement a complex tool using a subtask or might use them in a multi-agent evaluation. The main characteristics of sub-tasks are:

1.  They run in their own async coroutine.

2.  They have their own isolated `Transcript`

3.  They have their own isolated `Store` (no access to the sample `Store`).

To create a subtask, declare an async function with the `@subtask` decorator. The function can take any arguments and return a value of any type. For example:

``` python
from inspect_ai.solver import Store, subtask

@subtask
def web_search(keywords: str) -> str:
    # get links for these keywords
    links = await search_links(keywords)

    # add links to the store so they end up in the transcript
    store().set("links", links)

    # summarise the links
    return await fetch_and_summarise(links)
```

Note that we add `links` to the `store` not because we strictly need to for our implementation, but because we want the links to be recorded as part of the transcript.

Call the subtask as you would any async function:

``` python
summary = await web_search(keywords="solar power")
```

A few things will occur automatically when you run a subtask:

-   New isolated `Store` and `Transcript` objects will be created for the subtask (accessible via the `store()` and `transcript()` functions). Changes to the `Store` that occur during execution will be recorded in a `StoreEvent`.

-   A `SubtaskEvent` will be added to the current transcript. The event will include the name of the subtask, its input and results, and a transcript of all events that occur within the subtask.

You can also include one or more steps within a subtask.

### Tool Subtasks

If a tool is entirely independent of other tools (i.e. it is not coordinating with other tools via changes to the `store`) you can make the tool itself a subtask. This would be beneficial if the tool had interactions (e.g. model calls, store changes, etc.) you want to record in a distinct transcript.

To enclose a tool in a subtask, just add the `@subtask` decorator to the tool's execute function. For example, let's adapt the `web_search()` function above into a tool that also defines a subtask (note we also add a `model` parameter to customise what model is used for summarisation):

``` python
@tool(prompt="Use the web search tool to find information online")
def web_search(model: str | Model | None = None):

    # resolve model used for summarisation
    model = get_model(model)

    @subtask(name="web_search")
    def execute(keywords: str) -> str:
        # get links for these keywords
        links = await search_links(keywords)

        # add links to the store so they end up in the transcript
        store().set("links", links)

        # summarise the links
        return await fetch_and_summarise(links, model)

    return execute
```

Note that we've added the `name="web_search"` argument to `@subtask`—this is because we've declared our function using the generic name `execute()` and want to provide an alternative that is more readily understandable.

See [subtask.py](https://github.com/AI-Safety-Institute/inspect_ai/blob/feature/subtasks/src/inspect_ai/solver/_subtask/subtask.py) for the full implementation of the `@subtask` decorator.