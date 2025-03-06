"""
Command-line interface for multi-tool image.

This script allows the user to execute a specified tool with given parameters.

CLI Parameters:
---------------
request : str
  A JSON string representing the JSON RPC 2.0 request. This should be a valid JSON string that can be parsed into a dictionary.

Usage:
------
python multi_tool_v1.py <request>

Example:
--------
python multi_tool_v1.py '{"jsonrpc": "2.0", "method": "editor", "id": 666, "params": {"command": "view", "path": "/tmp"}}'
"""

import asyncio

from multi_tool._cli_helper import main as helper_main


def run():
    asyncio.run(helper_main())


if __name__ == "__main__":
    run()
