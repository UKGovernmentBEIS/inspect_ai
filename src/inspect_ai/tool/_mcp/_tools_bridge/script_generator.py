"""Generate MCP server script for sandbox."""

import json

from inspect_ai.tool._tool_info import ToolInfo

from .service import SERVICE_NAME

SERVICES_DIR = "/var/tmp/sandbox-services"


def generate_mcp_server_script(
    server_name: str,
    tools_info: dict[str, ToolInfo],
    service_instance: str,
) -> str:
    """Generate MCP server script for sandbox.

    Creates a self-contained Python script that:
    - Implements MCP JSON-RPC protocol over stdio
    - Communicates with host via sandbox service (filesystem IPC)
    - Has no external dependencies (only stdlib)

    Args:
        server_name: Name of the MCP server
        tools_info: Dictionary mappin g tool names to ToolInfo metadata
        service_instance: Unique instance ID for the sandbox service

    Returns:
        Python script content as string
    """
    tools_schema = []
    for name, info in tools_info.items():
        tools_schema.append(
            {
                "name": name,
                "description": info.description,
                "inputSchema": info.parameters.model_dump(exclude_none=True),
            }
        )

    tools_json = json.dumps(tools_schema, indent=2)
    tools_json_repr = repr(tools_json)

    template = """\
#!/usr/bin/env python3
\"\"\"MCP server for {server_name}.\"\"\"

import json
import sys
from pathlib import Path
from time import sleep
from uuid import uuid4

# Service client for host communication
SERVICES_DIR = "{services_dir}"
SERVICE_NAME = "{service_name}"
INSTANCE = "{service_instance}"

def call_host_tool(tool_name: str, arguments: dict) -> str:
    \"\"\"Call tool on host via service bridge.\"\"\"
    service_dir = Path(SERVICES_DIR) / SERVICE_NAME / INSTANCE
    requests_dir = service_dir / "requests"
    responses_dir = service_dir / "responses"

    request_id = str(uuid4())
    request = {{"id": request_id, "method": "call_tool", "params": {{"tool_name": tool_name, "arguments": arguments}}}}

    request_path = requests_dir / f"{{request_id}}.json"
    with open(request_path, "w") as f:
        json.dump(request, f)

    response_path = responses_dir / f"{{request_id}}.json"
    while True:
        if not response_path.exists():
            sleep(0.1)
            continue
        # File exists but may still be written - handle partial reads
        try:
            with open(response_path) as f:
                response = json.load(f)
            break
        except json.JSONDecodeError:
            # File exists but content not fully written yet
            sleep(0.1)
            continue
    response_path.unlink()

    if response.get("error"):
        raise Exception(response["error"])
    return response["result"]

TOOLS_JSON = {tools_json_repr}
TOOLS = json.loads(TOOLS_JSON)

def handle_request(request: dict) -> dict | None:
    method = request.get("method")
    req_id = request.get("id")

    if method == "initialize":
        return {{
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {{
                "protocolVersion": "2024-11-05",
                "capabilities": {{"tools": {{}}}},
                "serverInfo": {{"name": "{server_name}", "version": "1.0.0"}}
            }}
        }}

    elif method == "tools/list":
        return {{"jsonrpc": "2.0", "id": req_id, "result": {{"tools": TOOLS}}}}

    elif method == "tools/call":
        params = request.get("params", {{}})
        tool_name = params.get("name")
        arguments = params.get("arguments", {{}})
        try:
            result = call_host_tool(tool_name, arguments)
            return {{
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {{"content": [{{"type": "text", "text": result}}]}}
            }}
        except Exception as e:
            return {{
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {{"content": [{{"type": "text", "text": f"Error: {{e}}"}}], "isError": True}}
            }}

    elif method == "notifications/initialized":
        return None

    return {{"jsonrpc": "2.0", "id": req_id, "error": {{"code": -32601, "message": f"Unknown method: {{method}}"}}}}

def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            response = handle_request(request)
            if response:
                print(json.dumps(response), flush=True)
        except json.JSONDecodeError:
            print(json.dumps({{"jsonrpc": "2.0", "id": None, "error": {{"code": -32700, "message": "Parse error"}}}}), flush=True)

if __name__ == "__main__":
    main()
"""
    script = template.format(
        server_name=server_name,
        services_dir=SERVICES_DIR,
        service_name=SERVICE_NAME,
        service_instance=service_instance,
        tools_json_repr=tools_json_repr,
    )

    return script
