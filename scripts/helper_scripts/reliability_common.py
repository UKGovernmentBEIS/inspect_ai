from __future__ import annotations

import math
import warnings
from bisect import bisect_left
from pathlib import Path
from typing import Any, Literal, TypeAlias

from inspect_ai.log import read_eval_log
from inspect_ai.scorer import Value, ValueToFloat, value_to_float

Pairs: TypeAlias = list[tuple[float, int]]
"""``(confidence, outcome)`` with ``outcome`` in ``{0, 1}``."""


def latest_eval_log(log_dir: Path) -> Path:
    candidates = sorted(log_dir.glob("*.eval"), key=lambda p: p.stat().st_mtime)
    if not candidates:
        raise FileNotFoundError(f"No .eval logs found in {log_dir}")
    return candidates[-1]


def resolve_log_path(log: str | None, log_dir: str, latest: bool) -> Path:
    if latest:
        return latest_eval_log(Path(log_dir))
    if log:
        return Path(log)
    raise ValueError("Provide --log <path> or use --latest.")


def resolve_optional_log(
    path: str | None, log_dir: str, use_latest: bool, label: str
) -> Path:
    if use_latest:
        return latest_eval_log(Path(log_dir))
    if path:
        return Path(path)
    raise ValueError(f"Provide --{label}-log or --{label}-latest.")


def infer_scorer_name(log_path: Path, scorer_name: str | None) -> str:
    log = read_eval_log(str(log_path))
    if scorer_name is not None:
        return scorer_name
    if log.results and log.results.scores:
        return log.results.scores[0].name
    for sample in log.samples or []:
        if sample.scores:
            return next(iter(sample.scores.keys()))
    raise ValueError(
        f"Could not infer scorer name; pass --scorer explicitly for log {log_path}."
    )


def accuracy_from_log(log_path: Path, scorer_name: str | None) -> tuple[float, str]:
    """Mean score value for ``scorer_name`` across samples that have that score."""
    name = infer_scorer_name(log_path, scorer_name)
    log = read_eval_log(str(log_path))
    if not log.samples:
        raise ValueError(f"Log has no samples: {log_path}")

    to_float = value_to_float()
    values: list[float] = []
    for sample in log.samples:
        if sample.scores and name in sample.scores:
            values.append(to_float(sample.scores[name].value))

    if not values:
        raise ValueError(f"No sample scores found for scorer '{name}' in {log_path}.")
    return float(sum(values) / len(values)), name


def clamped_accuracy_ratio(acc_baseline: float, acc_perturbed: float) -> float:
    """min(Acc_perturbed / Acc_0, 1) for robustness metrics."""
    if acc_baseline <= 0.0:
        raise ValueError(
            "Baseline accuracy Acc_0 is zero; ratio is undefined. "
            "Use a task where the model scores above zero under baseline conditions."
        )
    return min(acc_perturbed / acc_baseline, 1.0)


def sample_resources(sample: object) -> dict[str, float]:
    """Extract scalar resource usage values from one sample."""
    resources: dict[str, float] = {}

    total_time = getattr(sample, "total_time", None)
    if isinstance(total_time, (int, float)):
        resources["total_time"] = float(total_time)

    working_time = getattr(sample, "working_time", None)
    if isinstance(working_time, (int, float)):
        resources["working_time"] = float(working_time)

    model_usage = getattr(sample, "model_usage", None) or {}
    token_fields = (
        "input_tokens",
        "output_tokens",
        "total_tokens",
        "reasoning_tokens",
        "input_tokens_cache_write",
        "input_tokens_cache_read",
        "total_cost",
    )
    for field in token_fields:
        total = 0.0
        found = False
        for usage in model_usage.values():
            value = getattr(usage, field, None)
            if isinstance(value, (int, float)):
                total += float(value)
                found = True
        if found:
            resources[field] = total

    return resources


def read_nested_metadata_key(
    mapping: dict[str, Any] | None, dotted_key: str
) -> Any | None:
    """Return ``mapping["a"]["b"]`` for ``dotted_key=="a.b"``, or ``None`` if any part is missing."""
    if not mapping:
        return None
    current: Any = mapping
    for part in dotted_key.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def parse_confidence_scalar(raw: Any) -> float | None:
    """Parse a stored metadata value as a scalar confidence, or ``None`` if unusable."""
    if raw is None:
        return None
    if isinstance(raw, bool):
        return 1.0 if raw else 0.0
    if isinstance(raw, int | float):
        if isinstance(raw, float) and math.isnan(raw):
            return None
        return float(raw)
    if isinstance(raw, str):
        try:
            return float(raw)
        except ValueError:
            return None
    return None


def clamp_unit_interval(confidence: float, *, context: str) -> float:
    """Clamp ``confidence`` to ``[0, 1]``, warning once if adjustment was needed."""
    if 0.0 <= confidence <= 1.0:
        return confidence
    clamped = min(1.0, max(0.0, confidence))
    warnings.warn(
        f"{context}: confidence {confidence} outside [0, 1]; clamped to {clamped}.",
        stacklevel=3,
    )
    return clamped


def outcome_binary_from_value(value: Value, to_float: ValueToFloat) -> int:
    """Map scorer value to ``{0, 1}`` using the usual ``value_to_float`` mapping (threshold 0.5)."""
    return 1 if float(to_float(value)) >= 0.5 else 0


def discrimination_pairs_from_log(
    log_path: Path,
    scorer_name: str | None,
    confidence_key: str,
    *,
    confidence_source: Literal["score", "sample"] = "score",
    skip_missing_confidence: bool = False,
    clamp_confidence_01: bool = True,
) -> tuple[Pairs, str, int]:
    """Collect ``(confidence, outcome)`` pairs from an eval log.

    Args:
        log_path: Path to ``.eval`` log.
        scorer_name: Scorer to use for outcomes; inferred if omitted.
        confidence_key: Dotted key path (e.g. ``confidence`` or ``calibration.p``) in metadata.
        confidence_source: Read confidence from that scorer's ``metadata`` or from ``sample.metadata``.
        skip_missing_confidence: If True, drop samples with no usable confidence; if False, raise.
        clamp_confidence_01: Clamp confidences into ``[0, 1]`` with a warning when out of range.

    Returns:
        (pairs, resolved_scorer_name, n_skipped_missing_confidence)

    Raises:
        ValueError: No samples, no scores for scorer, or missing confidence when
            ``skip_missing_confidence`` is False.
    """
    name = infer_scorer_name(log_path, scorer_name)
    log = read_eval_log(str(log_path))
    if not log.samples:
        raise ValueError(f"Log has no samples: {log_path}")

    to_float = value_to_float()
    pairs: Pairs = []
    n_skip = 0

    for sample in log.samples:
        if not sample.scores or name not in sample.scores:
            continue
        score = sample.scores[name]
        meta = score.metadata if confidence_source == "score" else sample.metadata
        raw_conf = read_nested_metadata_key(meta, confidence_key)
        conf = parse_confidence_scalar(raw_conf)
        if conf is None:
            if skip_missing_confidence:
                n_skip += 1
                continue
            raise ValueError(
                f"Missing or invalid confidence at key {confidence_key!r} "
                f"(source={confidence_source!r}) for scorer {name!r} in {log_path}."
            )
        if clamp_confidence_01:
            conf = clamp_unit_interval(
                conf, context=f"sample id={getattr(sample, 'id', '?')}"
            )
        y = outcome_binary_from_value(score.value, to_float)
        pairs.append((conf, y))

    if not pairs:
        raise ValueError(
            f"No usable (confidence, outcome) pairs for scorer '{name}' in {log_path} "
            f"(skipped_missing_confidence={n_skip})."
        )
    return pairs, name, n_skip


def discrimination_p_auroc(pairs: Pairs) -> float:
    """Pairwise discrimination (P_AUROC): AUC for confidence vs binary outcome.

    For n_succ successes and n_fail failures, counts the fraction of ordered pairs
    (success i, failure j) such that confidence c_i > c_j (strict). Equivalent to
    the Mann–Whitney / rank AUC when ties are handled as ``not greater than``.

    Args:
        pairs: ``(confidence, outcome)`` with ``outcome`` in ``{0, 1}``.

    Returns:
        Fraction in ``[0, 1]``.

    Raises:
        ValueError: If there is no success or no failure (degenerate case).
    """
    succ_c = [c for c, y in pairs if y == 1]
    fail_c = [c for c, y in pairs if y == 0]
    n_s, n_f = len(succ_c), len(fail_c)
    if n_s == 0 or n_f == 0:
        raise ValueError(
            "P_AUROC is undefined when all outcomes are the same "
            f"(n_succ={n_s}, n_fail={n_f})."
        )
    fail_sorted = sorted(fail_c)
    wins = sum(bisect_left(fail_sorted, s) for s in succ_c)
    return wins / (n_s * n_f)


def discrimination_from_log(
    log_path: Path,
    scorer_name: str | None,
    confidence_key: str,
    *,
    confidence_source: Literal["score", "sample"] = "score",
    skip_missing_confidence: bool = False,
    clamp_confidence_01: bool = True,
) -> tuple[float, str, int]:
    """Compute ``P_AUROC`` from a log; returns ``(p_auroc, scorer_name, n_skipped_missing_confidence)``."""
    pairs, name, n_skip = discrimination_pairs_from_log(
        log_path,
        scorer_name,
        confidence_key,
        confidence_source=confidence_source,
        skip_missing_confidence=skip_missing_confidence,
        clamp_confidence_01=clamp_confidence_01,
    )
    return discrimination_p_auroc(pairs), name, n_skip


def brier_predictability(pairs: Pairs) -> float:
    r"""Brier predictability P_brier = 1 - (1/T) * sum_i (c_i - y_i)^2.

    Args:
        pairs: ``(confidence, outcome)`` with ``outcome`` in ``{0, 1}`` and confidence
            in ``[0, 1]`` (after optional clamping when reading the log).

    Returns:
        One minus mean squared error between confidence and binary outcome (``1 - MSE``);
        higher is better (equals ``1`` when every ``c_i`` matches ``y_i``).

    Raises:
        ValueError: If ``pairs`` is empty.
    """
    if not pairs:
        raise ValueError("Cannot compute Brier predictability for empty pairs.")
    t = len(pairs)
    mse = sum((c - float(y)) ** 2 for c, y in pairs) / t
    return 1.0 - mse


def brier_mse(pairs: Pairs) -> float:
    """Mean squared error (1/T) * sum_i (c_i - y_i)^2 (standard Brier score)."""
    if not pairs:
        raise ValueError("Cannot compute Brier MSE for empty pairs.")
    t = len(pairs)
    return sum((c - float(y)) ** 2 for c, y in pairs) / t


def brier_predictability_from_log(
    log_path: Path,
    scorer_name: str | None,
    confidence_key: str,
    *,
    confidence_source: Literal["score", "sample"] = "score",
    skip_missing_confidence: bool = False,
    clamp_confidence_01: bool = True,
) -> tuple[float, float, str, int]:
    """Compute Brier predictability and MSE from a log.

    Returns:
        ``(p_brier, brier_mse, scorer_name, n_skipped_missing_confidence)``.
    """
    pairs, name, n_skip = discrimination_pairs_from_log(
        log_path,
        scorer_name,
        confidence_key,
        confidence_source=confidence_source,
        skip_missing_confidence=skip_missing_confidence,
        clamp_confidence_01=clamp_confidence_01,
    )
    mse = brier_mse(pairs)
    return 1.0 - mse, mse, name, n_skip


def coeff_variation(values: list[float], epsilon: float) -> float:
    """Sample coefficient of variation (sigma / mu)."""
    if not values:
        raise ValueError("Cannot compute coefficient of variation for empty values.")
    if len(values) == 1:
        return 0.0

    mean = sum(values) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / (len(values) - 1)
    std = math.sqrt(max(0.0, variance))
    if abs(mean) <= epsilon:
        return 0.0 if std <= epsilon else std / epsilon
    return std / abs(mean)
