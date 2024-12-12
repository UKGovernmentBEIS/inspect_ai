#!/usr/bin/env python3
import argparse
import os
import sys

sys.path.append("/tmp/inspect-sandbox-services/human_agent")
from human_agent import call_human_agent


def status():
    status = call_human_agent("status")
    print(status)


def start():
    parser = argparse.ArgumentParser()
    parser.parse_args(sys.argv[2:])
    call_human_agent("start")


def stop():
    call_human_agent("stop")


def submit():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "answer",
        nargs="?",
        help="Answer to submit for scoring (optional, not required for all tasks)",
    )
    args = parser.parse_args(sys.argv[2:])
    call_human_agent("submit", **vars(args))


_commands: dict = {"status": status, "start": start, "stop": stop, "submit": submit}

if len(sys.argv) > 0:
    command = os.path.basename(sys.argv[1])
    handler = _commands.get(command, None)
    if handler:
        handler()
    else:
        sys.stderr.write(f"command not recognized: {command}")
        sys.exit(1)
else:
    sys.stderr.write("no command specified (usage command.py <cmd>)")
    sys.exit(1)
