---
name: system-info
description: Get detailed system information including OS, kernel, CPU, and memory details
---

# System Information Skill

Use this skill to gather comprehensive system information about the Linux host.

## Quick Start

Run the included script for a complete system overview:

```bash
./scripts/sysinfo.sh
```

## Manual Commands

### Operating System
- `cat /etc/os-release` - Distribution name and version
- `uname -a` - Kernel version and architecture
- `hostnamectl` - Hostname and OS info (systemd systems)

### CPU Information
- `lscpu` - CPU architecture details (cores, threads, model)
- `cat /proc/cpuinfo | head -30` - Detailed processor info
- `nproc` - Number of available processors

### Memory Information
- `free -h` - Memory and swap usage (human-readable)
- `cat /proc/meminfo | head -10` - Detailed memory statistics

### System Uptime
- `uptime` - How long the system has been running
- `cat /proc/loadavg` - Load averages

## Tips

- The `sysinfo.sh` script provides structured output suitable for parsing
- Use `lscpu` for the most readable CPU information
- Memory values in `/proc/meminfo` are in kilobytes
