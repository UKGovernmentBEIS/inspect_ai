# Intervention Mode Demo

## Introduction

This is a prototype of an Inspect agent with human intervention. It utilizes Inspect's [Interactivity features](https://inspect.ai-safety-institute.org.uk/interactivity.html). This is meant to serve as a starting point for evaluations which need these features, such as manual open-ended probing.

This gives an overview of this setup and how to customize it.

## Inspect Code

### The Task

At the bottom of `intervention.py`, we have our Inspect task:

```python
@task
def intervention():
    tools = [bash(), python()]
    return Task(
        dataset=MemoryDataset([Sample(input="Unused in interactive mode")]),
        plan=[
            system_message(SYSTEM_PROMPT),
            agent_loop(tools),
        ],
        sandbox="docker",
    )
```

As you can see, this is just a regular Inspect evaluation. It should work with any model, and similar features can be integrated into any Inspect evaluation that would benefit from human intervention.

A few things to note here:

* To add more tools, just put them in the `tools` list.
* You may want to customize the system prompt, which can be found above the task definition.
* It uses an agent loop using the [lower level `model.generate()` API.](https://inspect.ai-safety-institute.org.uk/agents-api.html)

### The Agent Loop

The agent loop is [just a plain Inspect solver.](https://inspect.ai-safety-institute.org.uk/solvers.html).

First, we ask the user to enter a prompt for the model, print it out, and append it as a user message. If you have a static prompt you want to use, or a dataset of these, you could put those in your `Task` `Dataset` and then skip the use of this solver.

```python
@solver
def get_user_prompt() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        with input_screen() as console:
            user_prompt = Prompt.ask("Please enter your initial prompt for the model\n")
            console.print(
                Panel.fit(user_prompt, title="User Action", subtitle="Initial prompt")
            )
        state.messages.append(ChatMessageUser(content=user_prompt))

        return state

    return solve
```

Next, we have our agent loop. It runs a generation and appends the output to the messages list in `TaskState`. We also print the response of the model along with any tool calls present.

If there are tool calls present, it will ask the user for explicit permission to run the tool calls. If this is granted, they will be run. The tool call output will then be appended to messages and printed to the screen.

If there are no tool calls, the user will get a choice to terminate the conversation, force another generation, or send a custom user message to the model.

```python
@solver
def agent_loop(tools: list[Tool]) -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        model = get_model()
        while True:
            output = await model.generate(state.messages, tools)
            state.output = output
            state.messages.append(output.message)

            if output.message.tool_calls:
                authorization = print_tool_response_and_get_authorization(output)
                if not authorization:
                    logger.info("User denied tool calls and ended the evaluation.")
                    break

                tool_output = await call_tools(output.message, tools)
                state.messages.extend(tool_output)

                print_tool_output(tool_output)
            else:
                next_action = print_no_tool_response_and_ask_for_next_action(output)
                with input_screen() as console:
                    match next_action.strip().lower():
                        case "exit":
                            console.print(
                                Panel.fit(
                                    "User terminated the conversation.",
                                    title="User Action",
                                    subtitle="Exit",
                                )
                            )
                            break
                        case "":
                            console.print(
                                Panel.fit(
                                    "User requested another generation.",
                                    title="User Action",
                                    subtitle="Forced generation",
                                )
                            )
                            continue
                        case _:
                            console.print(
                                Panel.fit(
                                    next_action,
                                    title="User Action",
                                    subtitle="User sent message",
                                )
                            )
                            state.messages.append(ChatMessageUser(content=next_action))

        return state

    return solve
```

There are a few features and customizations that you might want to add:

1. In the case of rejecting a tool call, you might want to add a feature for sending a user message to the model or modifying the tool calls instead of terminating the evaluation.
2. You may want to customize the actions when no tool calls are generated, such as forcing another generation to overwrite the previous one without tool calls.

### Pretty-printing

As mentioned before, this demo relies on [Inspect's interactivity features](https://inspect.ai-safety-institute.org.uk/interactivity.html). These are built upon the [Rich Python library](https://rich.readthedocs.io/en/stable/introduction.html), which has many features, such as custom layouts, rendering for custom types, and more.

As an example, here is the function which renders tool calls. It demonstrates bash/Python code highlighting, text bolding, and nested panels. I highly recommend that you read the Rich documentation in case you want to extend this.

The rest of the code we haven't covered is just for layout and user input, but it's all self explanatory.

```python
def format_human_readable_tool_calls(
    tool_calls: list[ToolCall],
) -> list[RenderableType]:
    output_renderables: list[RenderableType] = []
    for i, tool_call in enumerate(tool_calls):
        panel_contents = []
        for i, (argument, value) in enumerate(tool_call.arguments.items()):
            argument_contents = []
            match (tool_call.function, argument):
                case ("python", "code"):
                    argument_contents.append(
                        Syntax(
                            value,
                            "python",
                            theme="monokai",
                            line_numbers=True,
                        )
                    )
                case ("bash", "cmd"):
                    argument_contents.append(Syntax(value, "bash", theme="monokai"))
                case _:
                    argument_contents.append(value)
            panel_contents.append(
                Panel.fit(
                    Group(*argument_contents, fit=True),
                    title=f"Argument #{i}: [bold]{argument}[/bold]",
                )
            )
        if tool_call.parse_error is not None:
            output_renderables.append(f"Parse error: {tool_call.parse_error}")
        output_renderables.append(
            Panel.fit(
                Group(*panel_contents, fit=True),
                title=f"Tool Call #{i}: [bold]{tool_call.function}[/bold]",
            )
        )
    return output_renderables
```

## Sandboxing

This evaluation is sandboxed in a Docker container. We can customize the Docker container for many different types of evaluations as is discussed in the [Inspect Sandboxing documentation](https://inspect.ai-safety-institute.org.uk/agents.html#sec-sandbox-environments).

### The Dockerfile

The Dockerfile is pretty simple for this demo. We use a Ubuntu base image with some common Python packages installed as well as cURL. Feel free to install other packages you want.

```dockerfile
FROM ubuntu:24.04

# Update the package lists
RUN apt-get update -y && apt-get upgrade -y

# Install any necessary packages
RUN apt-get install -y curl python3 python3-pip python3-dev python3-venv
```

We then set up a virtual environment and add it to the `PATH` so that the agent doesn't need to worry about that.
```dockerfile
# Virtual environment setup
ENV VIRTUAL_ENV=/opt/venv
RUN python3 -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
```

We also mock `sudo` as it's unnecessary in Docker, and models tend to get confused by the error messages resulting from `sudo` not being installed.

```dockerfile
# Mock sudo to avoid permission issues
RUN echo -e '#!/bin/sh\nexec "$@"' > /usr/bin/sudo && chmod +x /usr/bin/sudo
```

### Docker Compose

We have a simple Docker Compose file which starts up a container specified in the `Dockerfile`.

```docker
version: '3'
services:
  default:
    build: .
    command: tail -f /dev/null
    cpus: 1.0
    mem_limit: 0.5gb
    network_mode: bridge
```

You can customize this for advanced behaviors, such as GPU passthrough or multiple containers. Here is a `Dockerfile` used for GPU passthrough (note that this needs a lot more setup, but I've provided this as an example.)

```docker
version: '3'
services:
  default:
    build: .
    command: tail -f /dev/null
    cpus: 7.0
    mem_limit: 28.0gb
    network_mode: bridge
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
```
