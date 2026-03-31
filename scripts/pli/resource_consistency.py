"""Compute resource consistency (C_res) from an Inspect eval log.

This script extracts resource totals (time/tokens/cost fields), then compares
their variation across groups using:
    C_res = exp(-(1/|R|) * sum_r CV_r)
where CV_r is the sample coefficient of variation for resource r.

Grouping modes:
- by run (default): compare totals per epoch/run
- by sample: compare totals for each task-run sample

Usage examples:
    python scripts/pli/resource_consistency.py --latest
    python scripts/pli/resource_consistency.py --latest --resources total_time,total_tokens
"""

from __future__ import annotations

import argparse
import math
import sys
from collections import defaultdict
from pathlib import Path

_HELPERS = Path(__file__).resolve().parent.parent / "helper_scripts"
if str(_HELPERS) not in sys.path:
    sys.path.insert(0, str(_HELPERS))

from reliability_common import coeff_variation, resolve_log_path, sample_resources
from inspect_ai.log import read_eval_log


def grouped_resource_totals_from_log(
    log_path: Path, aggregation: str
) -> dict[str | int, dict[str, float]]:
    """Collect resource totals grouped by run or task-run sample."""
    log = read_eval_log(str(log_path))
    if not log.samples:
        return {}

    grouped: dict[str | int, dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for sample in log.samples:
        if aggregation == "run":
            group_key: str | int = sample.epoch if sample.epoch is not None else sample.uuid
        else:
            group_key = sample.uuid
        resources = sample_resources(sample)
        for name, value in resources.items():
            grouped[group_key][name] += value
    return {key: dict(values) for key, values in grouped.items()}


def resource_consistency_from_log(
    log_path: Path,
    resource_names: list[str] | None,
    epsilon: float,
    aggregation: str,
) -> tuple[float, list[str]]:
    """Compute C_res over grouped totals for selected resources."""
    grouped_totals = grouped_resource_totals_from_log(log_path=log_path, aggregation=aggregation)
    if not grouped_totals:
        raise ValueError(f"Log has no samples: {log_path}")

    available_resources: set[str] = set()
    for totals in grouped_totals.values():
        available_resources.update(totals.keys())

    if not available_resources:
        raise ValueError(
            "No resource fields found in log samples. "
            "Expected sample total/working time or model_usage token/cost fields."
        )

    if resource_names is None:
        resources = sorted(available_resources)
    else:
        requested = [name.strip() for name in resource_names if name.strip()]
        resources = [name for name in requested if name in available_resources]
        missing = sorted(set(requested) - set(resources))
        if missing:
            print(f"warning: requested resources not present in log: {', '.join(missing)}")

    if not resources:
        raise ValueError("No usable resources selected for resource consistency.")

    cvs: list[float] = []
    for resource_name in resources:
        values = [
            totals[resource_name]
            for totals in grouped_totals.values()
            if resource_name in totals
        ]
        if not values:
            continue
        cvs.append(coeff_variation(values, epsilon=epsilon))

    if not cvs:
        raise ValueError(
            "Unable to compute resource consistency with selected resources and grouping."
        )

    avg_cv = sum(cvs) / len(cvs)
    return float(math.exp(-avg_cv)), resources


def resource_means_from_groups(
    grouped_totals: dict[str | int, dict[str, float]], resource_names: list[str]
) -> dict[str, float]:
    """Compute mean value for selected resources across grouped totals."""
    values_by_resource: dict[str, list[float]] = defaultdict(list)
    for resources in grouped_totals.values():
        for name in resource_names:
            value = resources.get(name)
            if value is not None:
                values_by_resource[name].append(value)

    means: dict[str, float] = {}
    for name in resource_names:
        values = values_by_resource.get(name, [])
        if values:
            means[name] = float(sum(values) / len(values))
    return means


def resource_stddevs_from_groups(
    grouped_totals: dict[str | int, dict[str, float]], resource_names: list[str]
) -> dict[str, float]:
    """Compute sample standard deviation for selected resources across grouped totals."""
    values_by_resource: dict[str, list[float]] = defaultdict(list)
    for resources in grouped_totals.values():
        for name in resource_names:
            value = resources.get(name)
            if value is not None:
                values_by_resource[name].append(value)

    stddevs: dict[str, float] = {}
    for name in resource_names:
        values = values_by_resource.get(name, [])
        if len(values) >= 2:
            mean = sum(values) / len(values)
            variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
            stddevs[name] = float(math.sqrt(max(0.0, variance)))
        elif len(values) == 1:
            stddevs[name] = 0.0
    return stddevs


def resource_counts_from_groups(
    grouped_totals: dict[str | int, dict[str, float]], resource_names: list[str]
) -> dict[str, int]:
    """Count observed values for selected resources across grouped totals."""
    counts: dict[str, int] = defaultdict(int)
    for resources in grouped_totals.values():
        for name in resource_names:
            if name in resources:
                counts[name] += 1

    return {name: counts[name] for name in resource_names if counts[name] > 0}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compute resource consistency from an Inspect eval log."
    )
    parser.add_argument("--log", type=str, default=None, help="Path to .eval log file.")
    parser.add_argument("--log-dir", type=str, default="logs")
    parser.add_argument("--latest", action="store_true")
    parser.add_argument(
        "--resource-epsilon",
        type=float,
        default=1e-8,
        help="Stability constant used in CV denominator for near-zero means.",
    )
    parser.add_argument(
        "--resources",
        type=str,
        default=None,
        help=(
            "Comma-separated resource fields to include in C_res "
            "(default: all found in log)."
        ),
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--by-run",
        action="store_true",
        help="Compare resource totals grouped by run (epoch, default).",
    )
    mode.add_argument(
        "--by-sample",
        action="store_true",
        help="Compare resource totals with no grouping (all tasks across runs).",
    )
    args = parser.parse_args()

    log_path = resolve_log_path(log=args.log, log_dir=args.log_dir, latest=args.latest)
    aggregation = "sample" if args.by_sample else "run"
    resource_names = args.resources.split(",") if args.resources else None
    resource_score, used_resources = resource_consistency_from_log(
        log_path=log_path,
        resource_names=resource_names,
        epsilon=args.resource_epsilon,
        aggregation=aggregation,
    )
    grouped_totals = grouped_resource_totals_from_log(
        log_path=log_path, aggregation=aggregation
    )
    print(f"log={log_path}")
    print(f"aggregation={aggregation}")
    print(f"resource_consistency={resource_score:.6f}")
    print(f"resources={','.join(used_resources)}")

    included_resources = used_resources
    included_means = resource_means_from_groups(
        grouped_totals=grouped_totals, resource_names=included_resources
    )
    included_stddevs = resource_stddevs_from_groups(
        grouped_totals=grouped_totals, resource_names=included_resources
    )
    included_counts = resource_counts_from_groups(
        grouped_totals=grouped_totals, resource_names=included_resources
    )
    for resource_name in included_resources:
        if resource_name in included_means:
            print(f"{resource_name}_mean={included_means[resource_name]:.6f}")
        else:
            print(f"{resource_name}_mean=n/a")
        if resource_name in included_stddevs:
            print(f"{resource_name}_stddev={included_stddevs[resource_name]:.6f}")
        else:
            print(f"{resource_name}_stddev=n/a")
        if resource_name in included_counts:
            print(f"{resource_name}_count={included_counts[resource_name]}")
        else:
            print(f"{resource_name}_count=0")


if __name__ == "__main__":
    main()
