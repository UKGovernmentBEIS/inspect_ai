#!/bin/bash

# Check if container ID is provided
if [ -z "$1" ]; then
    echo "Usage: $0 <container_id>"
    echo "Example: $0 my_container"
    exit 1
fi

CONTAINER_ID="$1"

docker exec "$CONTAINER_ID" sh -c '
# Try Windows first
if command -v cmd >/dev/null 2>&1; then
    echo "OS: Windows"
    cmd /c ver 2>/dev/null || powershell -Command "$PSVersionTable.PSVersion" 2>/dev/null
    exit 0
fi

# Try macOS
if command -v sw_vers >/dev/null 2>&1; then
    echo "OS: macOS"
    sw_vers
    exit 0
fi

# Linux detection
if [ -f /etc/os-release ]; then
    . /etc/os-release
    case "$ID" in
        ubuntu)
            echo "OS: Ubuntu"
            echo "Version: $VERSION"
            ;;
        debian)
            echo "OS: Debian" 
            echo "Version: $VERSION"
            ;;
        kali)
            echo "OS: Kali Linux"
            echo "Version: $VERSION"
            ;;
        *)
            echo "OS: Other Linux ($NAME)"
            echo "Version: $VERSION"
            ;;
    esac
elif [ -f /etc/kali_version ]; then
    echo "OS: Kali Linux"
    cat /etc/kali_version
elif [ -f /etc/debian_version ]; then
    echo "OS: Debian-based"
    cat /etc/debian_version
else
    echo "OS: Other/Unknown"
    uname -a 2>/dev/null || echo "Could not determine OS"
fi
' 2>/dev/null || echo "Shell execution failed - trying alternative methods"