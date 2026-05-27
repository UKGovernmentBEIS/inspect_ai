---
name: disk-usage
description: Analyze disk space usage, filesystem mounts, and storage allocation on Linux systems. Identifies large files and directories, checks partition usage, and reports inode consumption. Use when the user asks about disk full errors, free space, storage usage, du/df output, finding large files, or checking which directories consume the most space.
---

# Disk Usage Skill

Analyzes disk space and filesystem usage on Linux systems.

## Suggested Workflow

1. Run `./scripts/diskinfo.sh` for a structured overview of mounts, block devices, and top directories.
2. Check `df -h` output for any filesystem above 80% usage.
3. Drill into high-usage mounts with `du -h --max-depth=1 /mount` to find large subdirectories.
4. Locate specific large files with `find /path -type f -size +100M`.

## Commands Reference

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
- The `du` command can be slow on large directories; use `--max-depth=1` to limit recursion
- Root filesystem (`/`) usage above 90% may cause issues
