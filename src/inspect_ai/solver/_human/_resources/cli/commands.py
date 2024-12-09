#!/usr/bin/env python3
import argparse
import os
import sys


def start():
    parser = argparse.ArgumentParser(description="Start the clock")
    args = parser.parse_args(sys.argv[2:])
    print("starting the clock")


def stop():
    print("stopping the clock")


def note():
    print("making a note")


if len(sys.argv) > 0:
    command = os.path.basename(sys.argv[1])
    match command:
        case "start":
            start()
        case "stop":
            stop()
        case "note":
            note()
        case _:
            sys.stderr.write(f"command not recognized: {command}")
            sys.exit(1)
else:
    sys.stderr.write("no command specified (usage command.py <cmd>)")
    sys.exit(1)
