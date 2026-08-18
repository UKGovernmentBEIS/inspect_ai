"""Full-text perplexity scorer.

Scores every prompt token by computing the per-sample negative
log-likelihood (NLL) from ``prompt_logprobs``.  This is used for pure
perplexity benchmarks (WikiText, C4, code validation sets) where the
entire text is the input and all tokens are scored.

This corresponds to the evaluation approach described in:
    - HuggingFace Transformers, "Perplexity of fixed-length models":
      https://huggingface.co/docs/transformers/en/perplexity

For target-completion perplexity (scoring only trailing target tokens),
see :func:`~inspect_ai.scorer.target_perplexity`.
"""

import math

from inspect_ai.solver._task_state import TaskState

from ._metric import Score
from ._metrics.perplexity import perplexity_per_seq, perplexity_per_token
from ._scorer import Scorer, scorer
from ._target import Target


@scorer(metrics=[perplexity_per_token(), perplexity_per_seq()])
def perplexity() -> Scorer:
    """Score samples by computing per-token negative log-likelihood from prompt logprobs.

    Requires ``prompt_logprobs`` to be set in ``GenerateConfig`` so that the
    model provider returns log probabilities for each prompt token.

    The score value is the per-sample negative log-likelihood (NLL).
    Per-sample perplexity is ``exp(value)``.  The companion
    :func:`perplexity_per_token` metric computes corpus-level perplexity
    weighted by token count.
    """

    # NaN signals "unscorable sample" — the metrics skip these
    # gracefully instead of crashing the eval run.  This matches
    # how classification scorers use NOANSWER for the same purpose.
    async def score(state: TaskState, target: Target) -> Score:
        if not state.output.choices:
            return Score(
                value=float("nan"),
                explanation="No model output choices available.",
            )

        choice = state.output.choices[0]
        if not choice.prompt_logprobs or choice.prompt_logprobs.content is None:
            return Score(
                value=float("nan"),
                explanation="No prompt logprobs available. Ensure prompt_logprobs is set in GenerateConfig.",
            )

        log_probs = [lp.logprob for lp in choice.prompt_logprobs.content]
        num_tokens = len(log_probs)
        if num_tokens == 0:
            return Score(
                value=float("nan"),
                explanation="prompt_logprobs.content is empty.",
            )
        sum_log_probs = sum(log_probs)
        nll = -sum_log_probs / num_tokens

        return Score(
            value=nll,
            explanation=f"Per-token NLL: {nll:.4f}, perplexity: {math.exp(nll):.4f}",
            metadata={
                "num_tokens": num_tokens,
                "sum_log_probs": sum_log_probs,
                "perplexity": math.exp(nll),
            },
        )

    return score
