#!/usr/bin/env python3
import argparse
import os
import sys


def start():
    parser = argparse.ArgumentParser(description="Start the clock")
    parser.parse_args(sys.argv[2:])
    print("starting the clock")


def stop():
    print("stopping the clock")


def note():
    print("making a note")


_commands: dict = {"start": start, "stop": stop, "note": note}

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
