---
name: system-info
description: Retrieve detailed Linux system information including OS distribution, kernel version, CPU model and core count, memory usage, and uptime. Use when the user asks about system specs, hardware details, RAM, processor info, kernel version, or needs a host inventory summary.
---

# System Information Skill

Gathers comprehensive system information about the Linux host.

## Suggested Workflow

1. Run `./scripts/sysinfo.sh` for structured output covering OS, CPU, memory, and uptime.
2. Use individual commands below for specific details or when the script is unavailable.

## Commands Reference

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

- The `sysinfo.sh` script outputs structured text (distribution, kernel, CPU model, cores, memory, uptime) suitable for parsing
- Use `lscpu` for the most readable CPU information
- Memory values in `/proc/meminfo` are in kilobytes
