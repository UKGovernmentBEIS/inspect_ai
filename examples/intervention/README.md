# Intervention Mode Demo

## Introduction

This is a prototype of an Inspect agent with human intervention. It utilises Inspect's [Interactivity features](https://inspect.ai-safety-institute.org.uk/interactivity.html). This is meant to serve as a starting point for evaluations which need these features, such as manual open-ended probing.

This gives an overview of this task and how to customise it. Note that this task is intended to be run within Inspect's approval mode (so you can confirm tool calls) and trace mode (so you can see the conversation with the model). For example:

``` bash
inspect eval intervention.py --approval human --trace
```

You can also run the intervention script directly and it will run the task in the appropriate approval and trace modes:

``` bash
python3 intervention.py
```

## Inspect Code

### Task Definition

At the top of `intervention.py`, we have our Inspect task:

``` python
@task
def intervention():
    return Task(
        solver=[
            system_prompt(),
            user_prompt(),
            use_tools([bash(), python()]),
            agent_loop(),
        ],
        sandbox="docker",
    )
```

As you can see, this is just a regular Inspect evaluation. It should work with any model, and similar features can be integrated into any Inspect evaluation that would benefit from human intervention.

A few things to note here:

-   To add more tools, just pass them to the `agent_loop()`.
-   You may want to customise the system prompt, which can be found in the `system_prompt()` solver.
-   It uses an agent loop using the [lower level `model.generate()` API.](https://inspect.ai-safety-institute.org.uk/agents-api.html)

### User Prompt

First, we ask the user to enter a prompt for the model:

``` python
@solver
def user_prompt() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        with input_screen("User Prompt") as console:
            state.user_prompt.content = Prompt.ask(
                "Please enter your initial prompt for the model:\n\n", console=console
            )

        return state

    return solve
```

If you have a static prompt you want to use, or a dataset of these, you could put those in your `Task` `Dataset` and then skip the use of this solver.

### Agent Loop

The agent loop is [just a plain Inspect solver.](https://inspect.ai-safety-institute.org.uk/solvers.html). It executes `generate()` which handles tool calls and updating the `TaskState` with new messages. Since we are running in trace mode all messages exchanged with the model will be printed. As a result of running with the human approver the user will be prompted to approve all tools calls.

``` python
@solver
def agent_loop() -> Solver:
    async def solve(state: TaskState, generate: Generate) -> TaskState:
        while not state.completed:
            # generate w/ tool calls, approvals, etc.
            state = await generate(state)

            # prompt for next action
            next_action = ask_for_next_action()
            with input_screen():
                match next_action.strip().lower():
                    case "exit":
                        break
                    case "":
                        state.messages.append(
                            ChatMessageUser(
                                content="Please continue working on this task."
                            )
                        )
                        continue
                    case _:
                        state.messages.append(ChatMessageUser(content=next_action))

        return state

    return solve
```

Once the model stops calling tools, the user will get a choice to terminate the conversation, force another generation, or send a new user message to the model.

## Sandboxing

This evaluation is sandboxed in a Docker container. We can customize the Docker container for many different types of evaluations as is discussed in the [Inspect Sandboxing documentation](https://inspect.ai-safety-institute.org.uk/agents.html#sec-sandbox-environments).

### The Dockerfile

The Dockerfile is pretty simple for this demo. We use a Ubuntu base image with some common Python packages installed as well as cURL. Feel free to install other packages you want.

``` dockerfile
FROM ubuntu:24.04

# Update the package lists
RUN apt-get update -y && apt-get upgrade -y

# Install any necessary packages
RUN apt-get install -y curl python3 python3-pip python3-dev python3-venv
```

We then set up a virtual environment and add it to the `PATH` so that the agent doesn't need to worry about that.

``` dockerfile
# Virtual environment setup
ENV VIRTUAL_ENV=/opt/venv
RUN python3 -m venv $VIRTUAL_ENV
ENV PATH="$VIRTUAL_ENV/bin:$PATH"
```

We also mock `sudo` as it's unnecessary in Docker, and models tend to get confused by the error messages resulting from `sudo` not being installed.

``` dockerfile
# Mock sudo to avoid permission issues
RUN echo -e '#!/bin/sh\nexec "$@"' > /usr/bin/sudo && chmod +x /usr/bin/sudo
```

### Docker Compose

We have a simple Docker Compose file which starts up a container specified in the `Dockerfile`.

``` docker
version: '3'
services:
  default:
    build: .
    command: tail -f /dev/null
    cpus: 1.0
    mem_limit: 0.5gb
    network_mode: bridge
```

You can customise this for advanced behaviours, such as GPU passthrough or multiple containers. Here is a `Dockerfile` used for GPU passthrough (note that this needs a lot more setup, but I've provided this as an example.)

``` docker
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