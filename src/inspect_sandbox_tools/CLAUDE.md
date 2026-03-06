This package provides tool support for inspect_ai without requiring custom Docker images or Dockerfiles. It uses an executable injection approach to deploy tool functionality directly into running containers.

### Stateful Tool Design Pattern

![diagram](https://raw.githubusercontent.com/UKGovernmentBEIS/inspect_ai/refs/heads/main/src/inspect_sandbox_tools/design/shared_tool_container_design.svg)

Some tools can be implemented without the need for any in-process state. For those tools, the tool code will be executed within the `inspect-sandbox-tools` process.

For tools that require the maintenance of state over the lifetime of a sandbox, this system marshals tool calls into a long running process via JSON RPC to a server process. That server then dispatches tool calls to tool specific `@method` handlers.

Each tool should have its own subdirectory that contains the following files:

-   `json_rpc_methods.py`

    This module contains all of the JSON RPC `@method` functions — one for each tool (e.g. the web browser tool is actually a set of distinct tools). It is responsible for unpacking the JSON RPC request and forwarding the call to a transport-agnostic, strongly typed, stateful controller.

-   `tool_types.py`

    This module includes the `pydantic` models representing the types for tool call parameters and results.

-   `controller.py`

    This is transport-agnostic, strongly typed code that manages the tool specific in-process state and performs requested commands.

## Architecture Overview

The `inspect_sandbox_tools` package is part of a split architecture that separates tool support into two independent systems:

- **Legacy system** (`inspect_tool_support`): Temporarily handles web browser functionality. Uses JSON-RPC communication but deploys code via Docker images built from Dockerfiles until the engineering to get Playwright included in the PyInstaller bundled executable works robustly.
- **This system** (`inspect_sandbox_tools`): Handles all other tools (bash_session, text_editor, MCP). Uses JSON-RPC communication with runtime executable injection for deployment.

### Build Process

Portable Linux executables are built via PyInstaller + StaticX for cross-distribution portability. Build scripts live in `src/inspect_ai/tool/_sandbox_tools_utils/` and output to `src/inspect_ai/binaries/` (amd64/arm64). See [RELEASING.md](design/RELEASING.md) for build, validation, and release commands.

### Container Injection Mechanism

When a tool needs to run in a container, the system automatically injects the appropriate executable:

1. Tool requests a sandbox via `container_tools_sandbox()`
2. System checks if `/opt/inspect-sandbox-tools` exists in the container
3. If missing, the injection process:
   - Detects container architecture (amd64/arm64)
   - Selects the appropriate pre-built executable from binaries
   - Writes executable to `/opt/inspect-sandbox-tools` in container
   - Sets execute permissions

The system includes fallback mechanisms to download executables from S3 or build them locally if needed.

### RPC Communication

Tools communicate through a two-layer RPC architecture:

**Layer 1 - Host to Container (stateless):**
1. Tool creates JSON-RPC request on host
2. `SandboxJSONRPCTransport` executes: `sandbox.exec(["/opt/inspect-sandbox-tools", "exec"], input=json_rpc_request)` 
3. JSON-RPC payload passed via stdin to the injected executable
4. Response returns via stdout

**Layer 2 - Container Internal (stateful operations):**
1. When stateful execution is needed, the injected executable acts as a client
2. It starts a server process if not already running
3. Sends JSON-RPC requests to the server via HTTP over Unix socket (`~/.cache/container-tools.sock`)
4. Server maintains state across requests and returns responses
5. The stateless executable forwards the response back through Layer 1

## Releasing

See [RELEASING.md](design/RELEASING.md) for the end-to-end process for building, publishing, and distributing new sandbox tools versions.

## Testing

When running `pytest` with inspect to test interactions with this package, you may wish to test your _local_ version of the `inspect_tool_support` code instead of the latest published package. Passing the flag `--local-inspect-tools` to pytest when running tests from `test_inspect_container_tools.py` will build and install the package from source, for example:

```sh
pytest tests/tools/test_inspect_container_tools.py --runslow --local-inspect-tools
```
