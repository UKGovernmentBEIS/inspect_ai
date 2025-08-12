#!/bin/bash

echo "🧪 Quick portability test..."

EXECUTABLE_PATH="$(pwd)/container_build/inspect-tool-support"

# Essential distributions representing different libc implementations
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
