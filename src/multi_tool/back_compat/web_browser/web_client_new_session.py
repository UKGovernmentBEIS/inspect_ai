"""
This script provides a backward compatible CLI for creating a new web browser session.

It is intended for backwards compatibility only, adapting the old, deprecated CLI to the new version supported by `multi_tool_v1.py`.

Usage:
  web_client_new_session [--headful]

Arguments:
  --headful : Run in headful mode for testing.
"""

import argparse
import json
import subprocess
import sys

from tool_types import NewSessionResult


def main() -> None:
    parser = argparse.ArgumentParser(prog="web_client_new_session")
    parser.add_argument(
        "--headful", action="store_true", help="Run in headful mode for testing"
    )
    result = subprocess.run(
        [
            "python",
            "multi_tool_v1.py",
            "web_new_session",
            json.dumps(vars(parser.parse_args())),
        ],
        cwd="/opt/inspect",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    print(NewSessionResult(**json.loads(result.stdout)).session_name)

    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
