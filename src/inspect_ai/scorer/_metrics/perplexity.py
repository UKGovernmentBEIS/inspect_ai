"""Perplexity metrics for aggregating NLL scores across samples.

Perplexity is defined as the exponentiated average negative log-likelihood:

    PPL(X) = exp( -1/N * sum_i log p(x_i | x_{<i}) )

Two aggregation strategies are provided:

- ``perplexity_per_token``: Standard corpus-level perplexity weighted by
  token count.  Longer samples contribute proportionally more.  This matches
  the HuggingFace Transformers documentation and the EleutherAI
  lm-evaluation-harness (``weighted_perplexity``).

- ``perplexity_per_seq``: Equal weight per sample regardless of length.
  Computes ``exp(mean(per-sample NLL))`` -- the geometric mean of
  per-sample perplexities.  This matches the EleutherAI
  lm-evaluation-harness (``perplexity``).

Both metrics expect each score's metadata to contain ``"num_tokens"``
and ``"sum_log_probs"`` (set by the perplexity and target_perplexity
scorers).

References:
    - HuggingFace Transformers, "Perplexity of fixed-length models":
      https://huggingface.co/docs/transformers/en/perplexity
    - EleutherAI lm-evaluation-harness, ``weighted_perplexity`` and
      ``perplexity`` aggregation functions:
      https://github.com/EleutherAI/lm-evaluation-harness/blob/main/lm_eval/api/metrics.py
"""

import logging
import math

from .._metric import Metric, SampleScore, metric

logger = logging.getLogger(__name__)


def _get_perplexity_metadata(
    sample: SampleScore,
) -> tuple[int, float]:
    """Extract num_tokens and sum_log_probs from score metadata.

    Returns (0, 0.0) and logs a warning if keys are missing.
    """
    md = sample.score.metadata or {}
    num_tokens = md.get("num_tokens")
    sum_log_probs = md.get("sum_log_probs")
    if num_tokens is None or sum_log_probs is None:
        logger.warning(
            "Perplexity metric: sample %s missing metadata keys "
            "(num_tokens=%r, sum_log_probs=%r). "
            "Ensure the scorer is perplexity() or target_perplexity().",
            sample.sample_id,
            num_tokens,
            sum_log_probs,
        )
        return (0, 0.0)
    return (int(num_tokens), float(sum_log_probs))


@metric
def perplexity_per_token() -> Metric:
    """Corpus-level perplexity weighted by token count.

    Longer samples contribute proportionally more.  Computed as
    ``exp(-total_sum_log_probs / total_num_tokens)``.

    This is the standard definition of corpus perplexity used in the
    HuggingFace Transformers documentation and the EleutherAI
    lm-evaluation-harness (``weighted_perplexity``).
    """

    def metric_fn(scores: list[SampleScore]) -> float:
        total_log_probs = 0.0
        total_tokens = 0
        for sample in scores:
            n, s = _get_perplexity_metadata(sample)
            total_log_probs += s
            total_tokens += n
        if total_tokens == 0:
            return float("nan")
        return math.exp(-total_log_probs / total_tokens)

    return metric_fn


@metric
def perplexity_per_seq() -> Metric:
    """Corpus-level perplexity with equal weight per sample.

    Each sample's per-token NLL is averaged, then exponentiated.
    Computed as ``exp(mean_over_samples(nll_i / num_tokens_i))``.

    Unlike ``perplexity_per_token``, this gives equal weight to each
    sample regardless of length, preventing long samples from
    dominating the metric.  This matches the EleutherAI
    lm-evaluation-harness (``perplexity``).
    """

    def metric_fn(scores: list[SampleScore]) -> float:
        nll_per_seq: list[float] = []
        for sample in scores:
            n, s = _get_perplexity_metadata(sample)
            if n > 0:
                nll_per_seq.append(-s / n)
        if not nll_per_seq:
            return float("nan")
        return math.exp(sum(nll_per_seq) / len(nll_per_seq))

    return metric_fn
