#!/bin/bash

set -e

# Parse command line arguments
TARGET_ARCH=""
BUILD_ALL=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --arch)
            TARGET_ARCH="$2"
            shift 2
            ;;
        --all)
            BUILD_ALL=true
            shift
            ;;
        --help)
            echo "Usage: $0 [--arch amd64|arm64] [--all]"
            echo "  --arch: Build for specific architecture"
            echo "  --all:  Build for both amd64 and arm64"
            echo "  (no args): Build for host architecture"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            echo "Use --help for usage information"
            exit 1
            ;;
    esac
done

if [ "$BUILD_ALL" = true ]; then
    echo "Building for all architectures..."
    $0 --arch amd64
    $0 --arch arm64
    exit 0
fi

# Determine target architecture
if [ -n "$TARGET_ARCH" ]; then
    case $TARGET_ARCH in
        amd64|arm64)
            ARCH_SUFFIX="$TARGET_ARCH"
            PLATFORM="linux/$TARGET_ARCH"
            ;;
        *)
            echo "Unsupported target architecture: $TARGET_ARCH"
            echo "Supported: amd64, arm64"
            exit 1
            ;;
    esac
else
    # Detect host architecture
    ARCH=$(uname -m)
    case $ARCH in
        x86_64)
            ARCH_SUFFIX="amd64"
            PLATFORM="linux/amd64"
            ;;
        aarch64|arm64)
            ARCH_SUFFIX="arm64"
            PLATFORM="linux/arm64"
            ;;
        *)
            echo "Unsupported architecture: $ARCH"
            exit 1
            ;;
    esac
fi

IMAGE_NAME="pyinstaller-build-$ARCH_SUFFIX"
DOCKERFILE="Dockerfile.pyinstaller"

echo "Building for architecture: $ARCH_SUFFIX (platform: $PLATFORM)"

# Build the Docker image
echo "Building Docker image..."
docker build --platform "$PLATFORM" -t "$IMAGE_NAME" -f "$DOCKERFILE" .

# Create container_build directory if it doesn't exist
mkdir -p container_build

# Note: Using --rm flag, so no need to manage container lifecycle

# Run the container with mounts and execute build script
echo "Starting container and building executable..."
docker run --rm --platform "$PLATFORM" \
    -v "$(pwd):/src:ro" \
    -v "$(pwd)/container_build:/output:rw" \
    -w /src \
    -e "ARCH_SUFFIX=$ARCH_SUFFIX" \
    "$IMAGE_NAME" \
    /src/build_executable.sh

echo "Build completed. Executable available in container_build/inspect-tool-support-$ARCH_SUFFIX"