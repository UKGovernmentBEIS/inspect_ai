#!/bin/bash

set -e

# Get architecture suffix from environment (set by build_within_container.sh)
ARCH_SUFFIX=${ARCH_SUFFIX:-"unknown"}
EXECUTABLE_NAME="inspect-tool-support-$ARCH_SUFFIX"

echo "Building maximally portable executable for $ARCH_SUFFIX..."

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
    --name "$EXECUTABLE_NAME" \
    src/inspect_tool_support/_cli/main.py

echo "Creating statically linked executable (eliminating system dependencies)..."
staticx --strip "dist/$EXECUTABLE_NAME" "/output/$EXECUTABLE_NAME"

echo "Verifying portability..."
# This should show "not a dynamic executable" or similar
ldd "/output/$EXECUTABLE_NAME" 2>/dev/null || echo "✅ Fully static - maximum portability achieved"

# Show what we built
ls -lh "/output/$EXECUTABLE_NAME"
file "/output/$EXECUTABLE_NAME"

echo "✅ Portable executable ready!"
echo "This should run on any Linux x86_64 system from ~2016 onwards"