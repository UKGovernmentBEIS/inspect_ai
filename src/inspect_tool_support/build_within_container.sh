#!/bin/bash

set -e

IMAGE_NAME="pyinstaller-build"
DOCKERFILE="Dockerfile.pyinstaller"

# Build the Docker image
echo "Building Docker image..."
docker build -t "$IMAGE_NAME" -f "$DOCKERFILE" .

# Create container_build directory if it doesn't exist
mkdir -p container_build

# Note: Using --rm flag, so no need to manage container lifecycle

# Run the container with mounts and execute build script
echo "Starting container and building executable..."
docker run --rm \
    -v "$(pwd):/src:ro" \
    -v "$(pwd)/container_build:/output:rw" \
    -w /src \
    "$IMAGE_NAME" \
    /src/build_executable.sh

echo "Build completed. Executable available in container_build/"