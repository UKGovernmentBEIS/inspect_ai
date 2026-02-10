"""Test script for samples_df.

Usage:
    python scripts/test_samples_df.py <log_dir>

Examples:
    python scripts/test_samples_df.py ~/tmp/logs/metr
    python scripts/test_samples_df.py s3://inspect-flow-test/metr/
    python scripts/test_samples_df.py ./logs
"""

import sys
import time

from inspect_ai.analysis import (
    SampleSummary,
    samples_df,
)
from inspect_ai.log import list_eval_logs


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    log_dir = sys.argv[1]
    print(f"Log directory: {log_dir}")
    print()

    # Step 1: List all logs
    print("=" * 60)
    print("Step 1: Listing eval logs")
    print("=" * 60)
    t0 = time.time()
    logs = list_eval_logs(log_dir)
    t1 = time.time()
    print(f"Found {len(logs)} log files in {t1 - t0:.2f}s")
    for log in logs[:10]:
        print(f"  {log.name}  ({log.task}, {log.size} bytes)")
    if len(logs) > 10:
        print(f"  ... and {len(logs) - 10} more")
    print()

    # Step 3: Read samples_df
    print("=" * 60)
    print("Step 3: Reading samples_df")
    print("=" * 60)
    t0 = time.time()
    sdf = samples_df(logs, columns=SampleSummary)
    t1 = time.time()
    print(f"samples_df: {len(sdf)} samples in {t1 - t0:.2f}s")
    print()

    # Step 4: Compute token usage from the total_tokens column
    print("=" * 60)
    print("Step 4: Token usage from total_tokens column")
    print("=" * 60)
    if "total_tokens" in sdf.columns:
        total = sdf["total_tokens"].sum()
        mean = sdf["total_tokens"].mean()
        median = sdf["total_tokens"].median()
        min_val = sdf["total_tokens"].min()
        max_val = sdf["total_tokens"].max()
        non_null = sdf["total_tokens"].notna().sum()
        print(f"Samples with token data: {non_null} / {len(sdf)}")
        print(f"Total tokens across all samples: {total:,}")
        print(f"Mean tokens per sample: {mean:,.1f}")
        print(f"Median tokens per sample: {median:,.1f}")
        print(f"Min tokens: {min_val:,}")
        print(f"Max tokens: {max_val:,}")
    else:
        print("total_tokens column not found!")
    print()

    print("=" * 60)
    print("Done!")
    print("=" * 60)


if __name__ == "__main__":
    main()
