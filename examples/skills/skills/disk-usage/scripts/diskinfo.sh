#!/bin/bash
# Disk Information Script
# Outputs disk usage and filesystem details in a structured format

echo "=== DISK INFORMATION ==="
echo

echo "--- Filesystem Usage ---"
df -h 2>/dev/null | head -15
echo

echo "--- Block Devices ---"
if command -v lsblk &> /dev/null; then
    lsblk -o NAME,SIZE,TYPE,MOUNTPOINT 2>/dev/null
else
    cat /proc/partitions
fi
echo

echo "--- Largest Directories in / ---"
du -h --max-depth=1 / 2>/dev/null | sort -rh | head -10
echo

echo "--- Mount Points ---"
mount | grep -E '^/dev' | head -10
