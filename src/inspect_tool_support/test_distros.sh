#!/bin/bash

echo "🧪 Quick portability test..."

# Detect host architecture
ARCH=$(uname -m)
case $ARCH in
    x86_64)
        ARCH_SUFFIX="amd64"
        ;;
    aarch64|arm64)
        ARCH_SUFFIX="arm64"
        ;;
    *)
        echo "Unsupported architecture: $ARCH"
        exit 1
        ;;
esac

EXECUTABLE_PATH="$(pwd)/container_build/inspect-tool-support-$ARCH_SUFFIX"

if [ ! -f "$EXECUTABLE_PATH" ]; then
    echo "❌ Executable not found: $EXECUTABLE_PATH"
    echo "Run ./build_within_container.sh first"
    exit 1
fi

echo "Testing executable for $ARCH ($ARCH_SUFFIX): $EXECUTABLE_PATH"

# Essential distributions representing different libc implementations
# Note: These will pull images matching the host architecture automatically
distributions=(
    "alpine:latest"           # musl libc
    "ubuntu:18.04"           # older glibc
    "ubuntu:22.04"           # recent glibc  
    "debian:11"              # debian stable
    "debian:10"              # debian oldstable
    "kalilinux/kali-rolling" # kali linux
    "centos:7"               # enterprise linux
    "rockylinux:9"           # modern enterprise
)

for distro in "${distributions[@]}"; do
    echo -n "Testing $distro: "
    if docker run --rm -v "$EXECUTABLE_PATH:/test/app:ro" "$distro" /test/app --help >/dev/null 2>&1; then
        echo "✅"
    else
        echo "❌"
    fi
done

echo ""
echo "Note: Tests run against $ARCH_SUFFIX executable on $ARCH_SUFFIX containers"
echo "For cross-architecture testing, build on the target architecture"
