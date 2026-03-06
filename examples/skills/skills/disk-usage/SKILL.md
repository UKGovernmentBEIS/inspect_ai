---
name: disk-usage
description: Analyze disk space usage and filesystem information including mounts, usage, and large files
---

# Disk Usage Skill

Use this skill to analyze disk space and filesystem usage on Linux systems.

## Quick Start

Run the included script for a disk usage overview:

```bash
./scripts/diskinfo.sh
```

## Manual Commands

### Filesystem Overview
- `df -h` - Disk space usage for all mounted filesystems (human-readable)
- `df -i` - Inode usage (number of files)
- `lsblk` - Block device tree (disks, partitions)
- `mount` - Currently mounted filesystems

### Directory Size Analysis
- `du -sh /path` - Total size of a directory
- `du -h --max-depth=1 /path` - Size of immediate subdirectories
- `du -ah /path | sort -rh | head -20` - Largest files/directories

### Finding Large Files
- `find /path -type f -size +100M` - Files larger than 100MB
- `find /path -type f -size +1G` - Files larger than 1GB
- `ls -lhS /path | head -20` - List files sorted by size (largest first)

### Disk Information
- `cat /proc/partitions` - Partition table
- `cat /proc/mounts` - Mount information
- `stat -f /path` - Filesystem statistics

## Tips

- Always use `-h` for human-readable sizes
- The `du` command can be slow on large directories
- Use `--max-depth=1` to limit recursion depth
- Root filesystem (`/`) usage above 90% may cause issues
