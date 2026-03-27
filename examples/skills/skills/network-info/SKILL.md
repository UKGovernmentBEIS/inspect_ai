---
name: network-info
description: Gather network configuration and connectivity details on Linux including interfaces, IP addresses, routing tables, DNS settings, and listening ports. Use when the user asks about IP configuration, network interfaces, connection issues, DNS resolution, open ports, routing, or network troubleshooting.
---

# Network Information Skill

Explores network configuration and connectivity on Linux systems.

## Suggested Workflow

1. Run `./scripts/netinfo.sh` for a structured overview of interfaces, IPs, routes, DNS, and listening ports.
2. Check `ip addr` for interface status and assigned addresses.
3. Verify routing with `ip route` and DNS with `cat /etc/resolv.conf`.
4. Inspect listening services with `ss -tuln` to identify open ports.

## Commands Reference

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
