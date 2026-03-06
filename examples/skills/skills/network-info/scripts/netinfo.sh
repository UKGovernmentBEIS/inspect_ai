#!/bin/bash
# Network Information Script
# Outputs network configuration details in a structured format

echo "=== NETWORK INFORMATION ==="
echo

echo "--- Network Interfaces ---"
if command -v ip &> /dev/null; then
    ip -br addr
else
    cat /proc/net/dev | tail -n +3 | awk '{print $1}' | tr -d ':'
fi
echo

echo "--- IP Addresses ---"
if command -v ip &> /dev/null; then
    ip addr show | grep -E 'inet |inet6 ' | awk '{print $2, $NF}'
else
    hostname -I 2>/dev/null || echo "Could not determine IP addresses"
fi
echo

echo "--- Routing Table ---"
if command -v ip &> /dev/null; then
    ip route
else
    cat /proc/net/route | head -5
fi
echo

echo "--- DNS Configuration ---"
if [ -f /etc/resolv.conf ]; then
    grep -E '^nameserver|^search|^domain' /etc/resolv.conf
else
    echo "No /etc/resolv.conf found"
fi
echo

echo "--- Listening Ports ---"
if command -v ss &> /dev/null; then
    ss -tuln | head -20
else
    cat /proc/net/tcp | head -10
fi
