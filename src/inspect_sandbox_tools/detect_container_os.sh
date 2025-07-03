#!/bin/bash

# Check if container ID is provided
if [ -z "$1" ]; then
    echo "Usage: $0 <container_id>"
    echo "Example: $0 my_container"
    exit 1
fi

CONTAINER_ID="$1"

docker exec "$CONTAINER_ID" sh -c '
# Function to detect architecture
detect_arch() {
    if command -v uname >/dev/null 2>&1; then
        ARCH=$(uname -m)
        case "$ARCH" in
            x86_64|amd64)
                echo "Architecture: x86_64 (amd64)"
                ;;
            aarch64|arm64)
                echo "Architecture: aarch64 (arm64)"
                ;;
            armv7l|armhf)
                echo "Architecture: armv7l (armhf)"
                ;;
            i386|i686)
                echo "Architecture: i386"
                ;;
            *)
                echo "Architecture: $ARCH"
                ;;
        esac
    else
        echo "Architecture: Unknown (uname not available)"
    fi
}

# Try Windows first
if command -v cmd >/dev/null 2>&1; then
    echo "OS: Windows"
    cmd /c ver 2>/dev/null || powershell -Command "$PSVersionTable.PSVersion" 2>/dev/null
    # Windows architecture detection
    if command -v powershell >/dev/null 2>&1; then
        powershell -Command "echo \"Architecture: $env:PROCESSOR_ARCHITECTURE\"" 2>/dev/null
    else
        echo "Architecture: Unknown (PowerShell not available)"
    fi
    exit 0
fi

# Try macOS
if command -v sw_vers >/dev/null 2>&1; then
    echo "OS: macOS"
    sw_vers
    detect_arch
    exit 0
fi

# Linux detection
if [ -f /etc/os-release ]; then
    . /etc/os-release
    case "$ID" in
        ubuntu)
            echo "OS: Ubuntu"
            echo "Version: $VERSION"
            detect_arch
            ;;
        debian)
            echo "OS: Debian" 
            echo "Version: $VERSION"
            detect_arch
            ;;
        kali)
            echo "OS: Kali Linux"
            echo "Version: $VERSION"
            detect_arch
            ;;
        *)
            echo "OS: Other Linux ($NAME)"
            echo "Version: $VERSION"
            detect_arch
            ;;
    esac
elif [ -f /etc/kali_version ]; then
    echo "OS: Kali Linux"
    cat /etc/kali_version
    detect_arch
elif [ -f /etc/debian_version ]; then
    echo "OS: Debian-based"
    cat /etc/debian_version
    detect_arch
else
    echo "OS: Other/Unknown"
    detect_arch
    uname -a 2>/dev/null || echo "Could not determine OS"
fi
' 2>/dev/null || echo "Shell execution failed - trying alternative methods"