"""Write recovered .eval files."""

from datetime import datetime, timezone
from logging import getLogger

from inspect_ai._util.error import EvalError
from inspect_ai.log._file import write_eval_log_async
from inspect_ai.log._log import (
    EvalLog,
    EvalSample,
    EvalStats,
    sort_samples,
)
from inspect_ai.log._metric import recompute_metrics
from inspect_ai.model._model_output import ModelUsage

from ._read import CrashedEvalLog

logger = getLogger(__name__)


async def write_recovered_eval_log(
    crashed: CrashedEvalLog,
    flushed_samples: list[EvalSample],
    buffer_samples: list[EvalSample],
    output: str | None = None,
) -> EvalLog:
    """Assemble and write a recovered .eval file.

    Args:
        crashed: Start data from the crashed .eval file.
        flushed_samples: Samples already flushed to the .eval file.
        buffer_samples: Reconstructed samples from the buffer DB.
        output: Output file path. Defaults to <name>-recovered.eval.

    Returns:
        The written EvalLog.
    """
    output = output or default_output_path(crashed.location)

    # Combine and sort all samples
    all_samples = flushed_samples + buffer_samples
    sort_samples(all_samples)

    # Compute stats from samples
    stats = _compute_stats(all_samples, crashed)

    # Build the EvalLog
    log = EvalLog(
        version=crashed.version,
        status="error",
        eval=crashed.eval,
        plan=crashed.plan,
        results=None,
        stats=stats,
        error=EvalError(
            message="Eval recovered from crash",
            traceback="Eval process crashed; log recovered from sample buffer database.\n",
            traceback_ansi="Eval process crashed; log recovered from sample buffer database.\n",
        ),
        samples=all_samples,
    )

    # Compute results from sample scores
    try:
        recompute_metrics(log)
    except Exception as ex:
        logger.warning(f"Unable to recompute metrics for recovered log: {ex}")

    # Write the recovered file
    await write_eval_log_async(log, output, format="eval")

    return log


def default_output_path(location: str) -> str:
    """Compute default output path for a recovered .eval file."""
    if location.endswith(".eval"):
        return location[:-5] + "-recovered.eval"
    return location + "-recovered"


def _compute_stats(samples: list[EvalSample], crashed: CrashedEvalLog) -> EvalStats:
    """Compute EvalStats from recovered samples."""
    # Find earliest started_at
    started_at = crashed.eval.created
    for sample in samples:
        if sample.started_at and (not started_at or sample.started_at < started_at):
            started_at = sample.started_at

    # Aggregate model_usage across all samples
    model_usage: dict[str, ModelUsage] = {}
    role_usage: dict[str, ModelUsage] = {}
    for sample in samples:
        for model, usage in sample.model_usage.items():
            if model not in model_usage:
                model_usage[model] = ModelUsage()
            model_usage[model] = _add_usage(model_usage[model], usage)
        for role, usage in sample.role_usage.items():
            if role not in role_usage:
                role_usage[role] = ModelUsage()
            role_usage[role] = _add_usage(role_usage[role], usage)

    return EvalStats(
        started_at=started_at or "",
        completed_at=datetime.now(timezone.utc).isoformat(),
        model_usage=model_usage,
        role_usage=role_usage,
    )


def _add_usage(a: ModelUsage, b: ModelUsage) -> ModelUsage:
    """Sum two ModelUsage instances."""
    return ModelUsage(
        input_tokens=a.input_tokens + b.input_tokens,
        output_tokens=a.output_tokens + b.output_tokens,
        total_tokens=a.total_tokens + b.total_tokens,
        input_tokens_cache_write=_add_optional(
            a.input_tokens_cache_write, b.input_tokens_cache_write
        ),
        input_tokens_cache_read=_add_optional(
            a.input_tokens_cache_read, b.input_tokens_cache_read
        ),
    )


def _add_optional(a: int | None, b: int | None) -> int | None:
    """Add two optional ints, returning None only if both are None."""
    if a is None and b is None:
        return None
    return (a or 0) + (b or 0)
