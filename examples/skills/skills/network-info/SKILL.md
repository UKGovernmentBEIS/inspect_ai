---
name: network-info
description: Gather network configuration and connectivity information including interfaces, routes, and DNS
---

# Network Information Skill

Use this skill to explore network configuration and connectivity on Linux systems.

## Quick Start

Run the included script for a network overview:

```bash
./scripts/netinfo.sh
```

## Manual Commands

### Network Interfaces
- `ip addr` or `ip a` - Show all network interfaces and IP addresses
- `ip link` - Show interface status (up/down)
- `cat /sys/class/net/*/address` - MAC addresses

### Routing
- `ip route` - Show routing table
- `ip route get 8.8.8.8` - Show route to a specific destination

### DNS Configuration
- `cat /etc/resolv.conf` - DNS servers
- `cat /etc/hosts` - Local host mappings
- `systemd-resolve --status` - DNS status (systemd systems)

### Active Connections
- `ss -tuln` - Show listening TCP/UDP ports
- `ss -tupn` - Show established connections with process info
- `cat /proc/net/tcp` - Raw TCP connection data

### Network Statistics
- `ip -s link` - Interface statistics (bytes, packets, errors)
- `cat /proc/net/dev` - Network device statistics

## Tips

- Use `ip` commands (modern) over `ifconfig`/`netstat` (deprecated)
- The `-n` flag prevents DNS lookups for faster output
- Check `ss -tuln` to see what services are listening
