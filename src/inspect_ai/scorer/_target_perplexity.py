"""Target-completion perplexity scorer.

Measures how well a model predicts a target continuation by computing
the negative log-likelihood (NLL) of the target tokens only, given a
prompt context.  Supports both pre-computed token counts and automatic
tokenization via the model provider's :meth:`~ModelAPI.tokenize` method.

This corresponds to the ``loglikelihood`` evaluation pattern in:
    - EleutherAI lm-evaluation-harness, ``LM.loglikelihood()``:
      https://github.com/EleutherAI/lm-evaluation-harness/blob/main/lm_eval/api/model.py

Usage::

    Task(
        dataset=dataset,
        solver=generate(max_tokens=1, prompt_logprobs=1),
        scorer=target_perplexity(),
    )

Each ``Sample`` should have either:
- ``metadata={"num_target_tokens": N}`` (pre-computed, no tokenization call), or
- ``metadata={"target_text": "..."}`` (auto-tokenized via the provider).
"""

from __future__ import annotations

import logging
import math

from inspect_ai._util.logger import warn_once
from inspect_ai.model._model import get_model
from inspect_ai.solver._task_state import TaskState

from ._metric import Score
from ._metrics.perplexity import perplexity_per_seq, perplexity_per_token
from ._scorer import Scorer, scorer
from ._target import Target

logger = logging.getLogger(__name__)


@scorer(metrics=[perplexity_per_token(), perplexity_per_seq()])
def target_perplexity(
    num_target_tokens: int | None = None,
    target_text_key: str = "target_text",
) -> Scorer:
    """Score samples by computing NLL of target-completion tokens.

    *N* (number of target tokens) is resolved in order:

    1. The ``num_target_tokens`` argument (uniform for all samples).
    2. ``state.metadata["num_target_tokens"]`` (per-sample).
    3. Auto-tokenize ``state.metadata[target_text_key]`` via the model
       provider's :meth:`~ModelAPI.tokenize` method.
    4. Raises an error if ``target_text`` is present but tokenization
       fails (no silent fallback to incorrect results).

    If neither ``num_target_tokens`` nor ``target_text`` is available,
    defaults to ``1`` (single-token targets like ``" A"``).

    Args:
        num_target_tokens: Fixed number of trailing prompt tokens.
            When ``None``, resolved per-sample from metadata or
            auto-tokenization.
        target_text_key: Metadata key holding the target text for
            auto-tokenization.  Defaults to ``"target_text"``.
    """

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
                explanation=(
                    "No prompt logprobs available. "
                    "Ensure prompt_logprobs is set in GenerateConfig."
                ),
            )

        # Resolve N: argument > metadata > auto-tokenize > default 1
        n = num_target_tokens
        if n is None:
            n = state.metadata.get("num_target_tokens")
        if n is None:
            target_text = state.metadata.get(target_text_key)
            if target_text:
                # Count tokens via the provider. Errors are not caught
                # because an incorrect n produces wrong scores.
                token_ids = await get_model().api.tokenize(target_text)
                n = len(token_ids)
            else:
                warn_once(
                    logger,
                    f"target_perplexity: neither 'num_target_tokens' nor "
                    f"'{target_text_key}' found in sample metadata; "
                    f"defaulting to num_target_tokens=1.",
                )
                n = 1

        if n <= 0:
            return Score(
                value=float("nan"),
                explanation=f"num_target_tokens must be > 0, got {n}.",
            )

        all_lps = choice.prompt_logprobs.content
        if len(all_lps) < n:
            return Score(
                value=float("nan"),
                explanation=(
                    f"prompt_logprobs has {len(all_lps)} entries but "
                    f"num_target_tokens={n}."
                ),
            )

        target_lps = all_lps[-n:]
        sum_log_probs = sum(lp.logprob for lp in target_lps)
        nll = -sum_log_probs / n

        return Score(
            value=nll,
            explanation=(
                f"target tokens={n}, "
                f"per-token NLL={nll:.4f}, "
                f"perplexity={math.exp(nll):.4f}"
            ),
            metadata={
                "num_tokens": n,
                "sum_log_probs": sum_log_probs,
                "perplexity": math.exp(nll),
            },
        )

    return score
