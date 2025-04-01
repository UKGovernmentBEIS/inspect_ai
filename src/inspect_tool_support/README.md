# Design

![diagram](https://raw.githubusercontent.com/UKGovernmentBEIS/inspect_ai/refs/heads/feature/stateful-bash/src/inspect_tool_support/shared_tool_container_design.svg)

Inspect calls into the sandboxed image are done statelessly via `docker exec inspect-tool-support`.

Some tools can be implemented without the need for any in-process state. For those tools, the tool code will be executed within the `inspect-tool-support` process.

For tools that require the maintenance of state over the lifetime of and sandbox, this image marshals tool calls into a long running process via JSON RPC to an http server process. That server then dispatches tool calls to tool specific `@method` handlers.

### Stateful Tool Design Pattern

Each stateful tool should have its own subdirectory that contains the following files:

- `json_rpc_methods.py`

  This module contains all of the JSON RPC `@method` functions — one for each tool (e.g. the web browser tool is actually a set of distinct tools). It is responsible for unpacking the JSON RPC request and forwarding the call to a transport-agnostic, strongly typed, stateful controller.

- `tool_types.py`

  This module includes the `pydantic` models representing the types for tool call parameters and results.

- `controller.py`

  This is transport-agnostic, strongly typed code that manages the tool specific in-process state and performs requested commands.
