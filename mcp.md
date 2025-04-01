## AutoGen

```python
# Create server params for the remote MCP service
server_params = SseServerParams(
  url="https://api.example.com/mcp",
  headers={"Authorization": "Bearer your-api-key", "Content-Type": "application/json"},
  timeout=30,  # Connection timeout in seconds
)

# Get the translation tool from the server
adapter = await SseMcpToolAdapter.from_server_params(server_params, "translate")
```

Can also use stdio based servers:

```python
# Setup server params for local filesystem access
desktop = str(Path.home() / "Desktop")
server_params = StdioServerParams(
    command="npx.cmd", args=["-y", "@modelcontextprotocol/server-filesystem", desktop]
)

# Get all available tools from the server
tools = await mcp_server_tools(server_params)
```

## LangGraph

You manually invoke all the mcp bits, their integration just adapts the tools

```python
# Create server parameters for stdio connection
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from langchain_mcp_adapters.tools import load_mcp_tools

server_params = StdioServerParameters(
    command="python",
    # Make sure to update to the full absolute path to your math_server.py file
    args=["/path/to/math_server.py"],
)

async with stdio_client(server_params) as (read, write):
    async with ClientSession(read, write) as session:
        # Initialize the connection
        await session.initialize()

        # Get tools
        tools = await load_mcp_tools(session)
```

## Agents SDK

```python
async with MCPServerStdio(
    params={
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", samples_dir],
    }
) as server:
    tools = await server.list_tools()
```

`MCPServerStdio` and `MCPServerSse` both supported.

## MCP

```python
async with stdio_client(server_params) as (read, write):
    async with ClientSession(
        read, write, sampling_callback=handle_sampling_message
    ) as session:
        # Initialize the connection
        await session.initialize()

        # List available prompts
        prompts = await session.list_prompts()

        # Get a prompt
        prompt = await session.get_prompt(
            "example-prompt", arguments={"arg1": "value"}
        )

        # List available resources
        resources = await session.list_resources()

        # List available tools
        tools = await session.list_tools()

        # Read a resource
        content, mime_type = await session.read_resource("file://some/path")

        # Call a tool
        result = await session.call_tool("tool-name", arguments={"arg1": "value"})
```

## Inspect


Treat this just like we treat models. They can explicitly managed using the context manager OR they are memoized with their parameters at the eval level, and they are released when the eval ends.

```python
class McpServer:
   def __aenter__()
   def __aexit__()

def mcp_server_sandbox() -> McpServer:
def mcp_server_local() -> McpServer:
def mcp_server_remote() -> McpServer:

def mcp_tools(server: McpServer, tools=["weather"]) -> list[Tool]
```

```python

def task_resource("name", cleanup)
def cleanup()

@task
def mytask():
  github = mcp_server_sse("github")

  return Task(
    solver=[usetools(mcp_tools(github))]
  )

```

```python

@solver
def my_solver():


    github = mcp_server_sse("github")

    async def solve(state, generate):
        

    return solve, github.cleanup
    
  
   
  

```


```python
with mcp_server_stdio() as server:
    agent = react(
      tools=server.list_tools()
    )
    state = run(agent, "do the thing")
```

```python
lifespan = Literal["task", "sample", "auto"]
# as soon as you do __aenter__ you disable the lifespan
```
