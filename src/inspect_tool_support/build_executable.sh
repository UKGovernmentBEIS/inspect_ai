#!/bin/bash

set -e

# Get architecture suffix from environment (set by build_within_container.sh)
ARCH_SUFFIX=${ARCH_SUFFIX:-"unknown"}

# Parse command line arguments
DEV_BUILD=false
while [[ $# -gt 0 ]]; do
    case $1 in
        --dev)
            DEV_BUILD=true
            shift
            ;;
        *)
            echo "Unknown argument: $1"
            echo "Usage: $0 [--dev]"
            exit 1
            ;;
    esac
done

# Set executable name based on whether this is a dev build
VERSION=$(cat ../inspect_ai/tool/tool_support_version.txt 2>/dev/null || echo "666")
if [ "$DEV_BUILD" = true ]; then
    EXECUTABLE_NAME="inspect-tool-support-$ARCH_SUFFIX-v$VERSION-dev"
else
    EXECUTABLE_NAME="inspect-tool-support-$ARCH_SUFFIX-v$VERSION"
fi

echo "Building maximally portable executable for $ARCH_SUFFIX..."

# Copy source and setup
rm -rf /tmp/inspect_tool_support-copy # This makes it easier to run multiple times when debugging the container.
cp -r /inspect_tool_support /tmp/inspect_tool_support-copy
cd /tmp/inspect_tool_support-copy

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

echo "Making executable..."
chmod +x "/output/$EXECUTABLE_NAME"

echo "Verifying portability..."
# This should show "not a dynamic executable" or similar
ldd "/output/$EXECUTABLE_NAME" 2>/dev/null || echo "✅ Fully static - maximum portability achieved"

# Show what we built
ls -lh "/output/$EXECUTABLE_NAME"
file "/output/$EXECUTABLE_NAME"

echo "✅ Portable executable ready: $EXECUTABLE_NAME"
echo "This should run on any Linux x86_64 system from ~2016 onwards"