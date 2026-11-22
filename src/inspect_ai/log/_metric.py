"""Score metrics recomputation functionality."""

from typing import NamedTuple

from inspect_ai._eval.task.results import ScorerInfo, eval_results
from inspect_ai._util.registry import RegistryNameNotFound
from inspect_ai.scorer._metric import Metric, SampleScore
from inspect_ai.scorer._reducer import ScoreReducer, create_reducers

from ._log import EvalLog

REDUCER_MISSING = (
    "Epoch reducer '{name}' (the log's epochs_reducer) could not be built: "
    "{error}. Install the package that defines the missing object, or import "
    "the module that defines it, first; the log's task file is not imported "
    "for reducers."
)


class LogMetrics(NamedTuple):
    """Reducers and metrics rebuilt from a log header."""

    reducers: list[ScoreReducer] | None
    metrics: list[Metric | dict[str, list[Metric]]] | dict[str, list[Metric]] | None
    scorers: list[ScorerInfo]


def resolve_log_metrics(
    log: EvalLog,
    *,
    trust_log: bool = False,
    reducer_advice: str | None = None,
    trust_log_advice: bool = True,
) -> LogMetrics:
    """Rebuild the log's reducers and metrics.

    Reads only the header. Without `trust_log` nothing the log names is
    imported, and metric options may construct only metrics and reducers.

    Args:
        log: The evaluation log.
        trust_log: Import the log's task file for unregistered metrics and
            rebuild metric options without restriction. This runs the task
            file's code, so pass it only for logs you trust.
        reducer_advice: Text appended to the error for a missing reducer,
            recorded or nested in metric options.
        trust_log_advice: End untrusted metric errors with advice to pass
            `trust_log=True`. `False` for callers that have no such option.

    Raises:
        RegistryNameNotFound: A metric, an epoch reducer or an object they
            depend on is not registered (a `LookupError`).
        DisallowedRegistryArg: Untrusted metric options name a model or a
            non-metric registry object.
    """
    # Import here to avoid circular imports
    from inspect_ai._eval.score import (
        TRUST_LOG_OPT_IN,
        LogTaskFileImport,
        metrics_from_log_header,
        resolve_scorers_info,
    )

    reducers: list[ScoreReducer] | None = None
    if log.eval.config.epochs_reducer is not None:
        reducers = []
        for name in log.eval.config.epochs_reducer:
            try:
                reducers.extend(create_reducers(name))
            except RegistryNameNotFound as ex:
                # the missing name may be the reducer's or a dependency's
                message = REDUCER_MISSING.format(name=name, error=ex)
                if reducer_advice:
                    message = f"{message} {reducer_advice}"
                raise RegistryNameNotFound(message) from ex

    task_import = LogTaskFileImport(
        log,
        trust_log=trust_log,
        opt_in=TRUST_LOG_OPT_IN if trust_log_advice else None,
        dependency_advice=reducer_advice,
    )
    metrics = metrics_from_log_header(log, task_import=task_import)
    scorers = resolve_scorers_info(log, task_import=task_import)
    return LogMetrics(reducers=reducers, metrics=metrics, scorers=scorers)


def compute_log_metrics(log: EvalLog, resolved: LogMetrics) -> None:
    """Compute the log's results and reductions from its samples' scores.

    Args:
        log: The evaluation log (updated in place).
        resolved: Reducers and metrics from `resolve_log_metrics()`.

    Raises:
        ValueError: If log is missing required data for recomputation
    """
    if log.samples is None:
        raise ValueError("Log contains no samples")

    # Extract scores from all samples
    scores = []
    for sample in log.samples:
        if sample.scores:
            sample_scores = {}
            for score_name, score in sample.scores.items():
                sample_scores[score_name] = SampleScore(
                    score=score, sample_id=sample.id, sample_metadata=sample.metadata
                )
            scores.append(sample_scores)

    # Recompute
    results, reductions = eval_results(
        samples=len(log.samples),
        scores=scores,
        reducers=resolved.reducers,
        scorers=resolved.scorers,
        metrics=resolved.metrics,
        early_stopping=log.results.early_stopping if log.results else None,
        metadata=log.results.metadata if log.results else None,
        # eval-set completeness contract (see EvalResults.logged_samples):
        # recomputing metrics must not make a drained log read complete
        logged_samples=log.results.logged_samples if log.results else None,
        # the count isn't persisted but the per-sample error state is, so
        # recompute it rather than letting eval_results() fall back to
        # len(scores) (which is scorer-order dependent)
        completed_samples=sum(1 for s in log.samples if s.error is None),
        headline_metric=log.eval.headline_metric,
    )

    # Update the log's results and reductions
    log.results = results
    log.reductions = reductions


def recompute_metrics(log: EvalLog, *, trust_log: bool = False) -> None:
    """Recompute aggregate metrics after score edits.

    Metrics and reducers are rebuilt from the registry. A metric defined in
    the log's task file must be imported first, or `trust_log=True` passed.

    Args:
        log: The evaluation log to recompute metrics for
        trust_log: Import the log's task file for metrics that are not
            registered, and rebuild metric options that hold models or other
            registry objects. This runs the task file's code, so pass it
            only for logs you trust.

    Raises:
        ValueError: If log is missing required data for recomputation
        LookupError: A metric, an epoch reducer or an object they depend on
            is not registered.
        DisallowedRegistryArg: Without `trust_log`, metric options name a
            model or a non-metric registry object (a `ValueError`).
    """
    if log.samples is None:
        raise ValueError("Log contains no samples")
    compute_log_metrics(log, resolve_log_metrics(log, trust_log=trust_log))
