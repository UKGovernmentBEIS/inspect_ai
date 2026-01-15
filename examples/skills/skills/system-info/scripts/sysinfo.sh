#!/bin/bash
# System Information Script
# Outputs comprehensive system details in a structured format

echo "=== SYSTEM INFORMATION ==="
echo

echo "--- Operating System ---"
if [ -f /etc/os-release ]; then
    . /etc/os-release
    echo "Distribution: $NAME $VERSION"
else
    echo "Distribution: Unknown"
fi
echo "Kernel: $(uname -r)"
echo "Architecture: $(uname -m)"
echo

echo "--- CPU Information ---"
if command -v lscpu &> /dev/null; then
    echo "Model: $(lscpu | grep 'Model name' | cut -d: -f2 | xargs)"
    echo "Cores: $(lscpu | grep '^CPU(s):' | cut -d: -f2 | xargs)"
    echo "Threads per core: $(lscpu | grep 'Thread(s) per core' | cut -d: -f2 | xargs)"
else
    echo "CPU: $(cat /proc/cpuinfo | grep 'model name' | head -1 | cut -d: -f2 | xargs)"
    echo "Processors: $(nproc)"
fi
echo

echo "--- Memory Information ---"
if command -v free &> /dev/null; then
    free -h | head -2
else
    echo "Total: $(grep MemTotal /proc/meminfo | awk '{print $2/1024/1024 " GB"}')"
    echo "Available: $(grep MemAvailable /proc/meminfo | awk '{print $2/1024/1024 " GB"}')"
fi
echo

echo "--- System Uptime ---"
uptime
