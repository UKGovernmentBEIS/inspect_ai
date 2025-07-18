#!/bin/bash

cp -r /src /tmp/src-copy
cd /tmp/src-copy
pip install .
pyinstaller --onefile --hidden-import=psutil --copy-metadata=inspect_tool_support src/inspect_tool_support/_cli/main.py
staticx dist/main dist/inspect-tool-support-static
cp dist/inspect-tool-support-static /output/inspect-tool-support