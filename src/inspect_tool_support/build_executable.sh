#!/bin/bash

set -e

echo "Building maximally portable executable..."

# Copy source and setup
cp -r /src /tmp/src-copy
cd /tmp/src-copy

echo "Installing package..."
pip install .

echo "Building with PyInstaller (bundling all Python dependencies)..."
pyinstaller \
    --onefile \
    --strip \
    --optimize 2 \
    --hidden-import=psutil \
    --copy-metadata=inspect_tool_support \
    --exclude-module tkinter \
    --exclude-module test \
    --exclude-module unittest \
    --exclude-module pdb \
    --name inspect-tool-support \
    src/inspect_tool_support/_cli/main.py

echo "Creating statically linked executable (eliminating system dependencies)..."
staticx --strip dist/inspect-tool-support /output/inspect-tool-support

echo "Verifying portability..."
# This should show "not a dynamic executable" or similar
ldd /output/inspect-tool-support 2>/dev/null || echo "✅ Fully static - maximum portability achieved"

# Show what we built
ls -lh /output/inspect-tool-support
file /output/inspect-tool-support

echo "✅ Portable executable ready!"
echo "This should run on any Linux x86_64 system from ~2016 onwards"