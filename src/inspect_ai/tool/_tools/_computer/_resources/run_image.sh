#!/usr/bin/env bash

SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )

docker run -d --rm \
  -v "$SCRIPT_DIR"/computer_tool_support:/home/computeruse/computer_tool_support/ \
  -p 5900:5900 \
  -p 6080:6080 \
  -it epatey/inspect-computer-tool:local