from __future__ import annotations

import math
import re
from string import Formatter

from inspect_ai.model import (
    ContentReasoning,
    ContentText,
    GenerateConfig,
    Model,
    ModelOutput,
    get_model,
)
from inspect_ai.solver import Generate, Solver, TaskState, multiple_choice, solver
from inspect_ai.util import resource

DEFAULT_SCORED_CONFIDENCE_PROMPT = """\
Estimate the probability that the answer is correct.

Question:
{question}

Reasoning (from the model that produced the answer):
{reasoning}

Answer:
{answer}

Return ONLY a single number between 0 and 1.
"""


@solver
def confidence_generate(
    method: str = "logprobs",
    confidence_key: str = "confidence",
    confidence_model: str | Model | None = None,
    confidence_prompt: str | None = None,
    choice_template: str | None = None,
    multiple_correct: bool = False,
    max_tokens: int | None = None,
    top_logprobs: int = 5,
    scored_max_tokens: int = 512,
    scored_timeout: int = 30,
    scored_attempt_timeout: int = 20,
    scored_max_retries: int = 1,
    on_confidence_error: str = "fallback",
    fallback_confidence: float = 0.5,
    clamp_confidence: bool = True,
) -> Solver:
    """Generate once, compute confidence, and store it in ``sample.metadata``.

    Methods:
      - ``logprobs``: geometric mean token probability from generated token logprobs
      - ``top_logprobs``: mean per-token normalized probability using top alternatives
      - ``scored_confidence``: extra model call that returns a scalar in [0, 1]

    Args:
        method: One of ``logprobs``, ``top_logprobs``, ``scored_confidence``.
        confidence_key: Metadata key written on ``TaskState.metadata``.
        confidence_model: Model for ``scored_confidence`` only; defaults to active eval model.
        confidence_prompt: Optional template path or string; must include ``{question}`` and
            ``{answer}`` for ``scored_confidence``. You may include ``{reasoning}`` (reasoning
            from the answer-generating call, if any). The ``{question}`` value is the text of
            the last user message (after running the task generator), so for multiple-choice
            tasks it includes the formatted options when ``multiple_choice`` has run.
        choice_template: For samples with ``choices`` (e.g. GPQA), template passed to
            ``multiple_choice`` so formatting matches the baseline task. Same contract as
            that solver's ``template`` argument.
        multiple_correct: Forwarded to ``multiple_choice`` when choices exist.
        max_tokens: Forwarded to ``generate`` / ``multiple_choice`` for the main answer call.
        top_logprobs: ``k`` passed to the model when ``method`` is ``top_logprobs``.
        scored_max_tokens: Output budget for the scored follow-up call (reasoning models
            need a larger value or the visible completion can be empty).
        scored_timeout: Whole-request timeout (seconds) for scored confidence calls.
        scored_attempt_timeout: Per-attempt timeout (seconds) for scored confidence calls.
        scored_max_retries: Retry budget for scored confidence calls.
        on_confidence_error: Behavior when confidence extraction fails:
            ``fallback`` stores ``fallback_confidence``; ``raise`` aborts sample.
        fallback_confidence: Confidence used when ``on_confidence_error='fallback'``.
        clamp_confidence: If True, clamp stored confidence to ``[0, 1]``.
    """
    mode = method.strip().lower()
    if mode not in {"logprobs", "top_logprobs", "scored_confidence"}:
        raise ValueError(
            f"Unknown method {method!r}. Use one of: "
            "'logprobs', 'top_logprobs', 'scored_confidence'."
        )
    if on_confidence_error not in {"fallback", "raise"}:
        raise ValueError(
            f"Unknown on_confidence_error {on_confidence_error!r}. "
            "Use 'fallback' or 'raise'."
        )

    prompt_template = resource(confidence_prompt or DEFAULT_SCORED_CONFIDENCE_PROMPT)

    use_mc_logprobs = mode in {"logprobs", "top_logprobs"}
    mc_top = top_logprobs if mode == "top_logprobs" else None
    mc_solver = multiple_choice(
        template=choice_template,
        multiple_correct=multiple_correct,
        max_tokens=max_tokens,
        logprobs=use_mc_logprobs,
        top_logprobs=mc_top,
    )

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        if state.choices:
            state = await mc_solver(state, generate)
        elif mode == "logprobs":
            if max_tokens is not None:
                state = await generate(state, logprobs=True, max_tokens=max_tokens)
            else:
                state = await generate(state, logprobs=True)
        elif mode == "top_logprobs":
            if max_tokens is not None:
                state = await generate(
                    state,
                    logprobs=True,
                    top_logprobs=top_logprobs,
                    max_tokens=max_tokens,
                )
            else:
                state = await generate(
                    state,
                    logprobs=True,
                    top_logprobs=top_logprobs,
                )
        else:
            if max_tokens is not None:
                state = await generate(state, max_tokens=max_tokens)
            else:
                state = await generate(state)

        if mode == "logprobs":
            confidence = _confidence_from_logprobs(state.output)
        elif mode == "top_logprobs":
            confidence = _confidence_from_top_logprobs(state.output)
        else:
            try:
                confidence = await _confidence_from_scored_call(
                    state=state,
                    model=confidence_model,
                    template=prompt_template,
                    max_tokens=scored_max_tokens,
                    timeout=scored_timeout,
                    attempt_timeout=scored_attempt_timeout,
                    max_retries=scored_max_retries,
                )
                state.metadata["confidence_source"] = "scored_confidence"
            except Exception as ex:
                if on_confidence_error == "raise":
                    raise
                confidence = fallback_confidence
                state.metadata["confidence_source"] = "fallback"
                state.metadata["confidence_error"] = str(ex)

        if clamp_confidence:
            confidence = min(1.0, max(0.0, confidence))
        state.metadata[confidence_key] = confidence
        return state

    return solve


def _first_choice(output: ModelOutput):
    if not output.choices:
        raise ValueError("Model output has no choices.")
    return output.choices[0]


def _confidence_from_logprobs(output: ModelOutput) -> float:
    choice = _first_choice(output)
    if choice.logprobs is None or not choice.logprobs.content:
        raise ValueError(
            "No logprobs were returned by the model. "
            "If you use a reasoning-enabled model, logprobs may be unsupported. "
            "Try method='scored_confidence' instead."
        )
    mean_logprob = sum(lp.logprob for lp in choice.logprobs.content) / len(
        choice.logprobs.content
    )
    return math.exp(mean_logprob)


def _confidence_from_top_logprobs(output: ModelOutput) -> float:
    choice = _first_choice(output)
    if choice.logprobs is None or not choice.logprobs.content:
        raise ValueError(
            "No logprobs were returned by the model. "
            "Try method='scored_confidence' instead."
        )

    probs: list[float] = []
    for lp in choice.logprobs.content:
        if not lp.top_logprobs:
            continue
        candidates = [tlp.logprob for tlp in lp.top_logprobs]
        if not any(abs(val - lp.logprob) < 1e-9 for val in candidates):
            candidates.append(lp.logprob)
        max_lp = max(candidates)
        denom = sum(math.exp(val - max_lp) for val in candidates)
        p_selected = math.exp(lp.logprob - max_lp) / denom
        probs.append(p_selected)

    if not probs:
        raise ValueError(
            "No top_logprobs were available in model output. "
            "Try method='logprobs' or method='scored_confidence'."
        )
    return sum(probs) / len(probs)


async def _confidence_from_scored_call(
    state: TaskState,
    model: str | Model | None,
    template: str,
    *,
    max_tokens: int,
    timeout: int,
    attempt_timeout: int,
    max_retries: int,
) -> float:
    resolved = model if isinstance(model, Model) else get_model(model)
    answer_text = _task_answer_text(state)
    reasoning_text = _reasoning_from_output(state.output)
    # Last user message after `multiple_choice` includes formatted MC options.
    question_text = state.user_prompt.text
    prompt = _format_confidence_template(
        template, question_text, answer_text, reasoning_text
    )

    budgets = [max_tokens, max(max_tokens * 2, 1024)]
    last_raw = ""
    for budget in budgets:
        output = await resolved.generate(
            prompt,
            tools=[],
            tool_choice=None,
            config=GenerateConfig(
                temperature=0,
                max_tokens=budget,
                timeout=timeout,
                attempt_timeout=attempt_timeout,
                max_retries=max_retries,
                verbosity="low",
                reasoning_effort="minimal",
                reasoning_summary="none",
            ),
        )
        last_raw = _assistant_visible_text(output)
        confidence = _parse_confidence_text(last_raw)
        if confidence is not None:
            return confidence

    raise ValueError(
        "Could not parse scored confidence from model response after retries. "
        f"Last extracted text was {last_raw!r}. "
        "Try increasing -S scored_max_tokens= (e.g. 1024), use a non-reasoning "
        "model for -S confidence_model=, or simplify the prompt so the model returns "
        "only one number in [0, 1]."
    )


def _format_confidence_template(
    template: str, question: str, answer: str, reasoning: str
) -> str:
    """Apply ``template`` with optional ``{reasoning}`` for older custom prompts."""
    names: set[str] = set()
    for _, field_name, _, _ in Formatter().parse(template):
        if field_name:
            root = field_name.split(".", 1)[0].split("[", 1)[0]
            names.add(root)
    kwargs: dict[str, str] = {"question": question, "answer": answer}
    if "reasoning" in names:
        kwargs["reasoning"] = reasoning
    return template.format(**kwargs)


def _reasoning_from_output(output: ModelOutput) -> str:
    """Extract assistant reasoning blocks from the first completion choice, if present."""
    if not output.choices:
        return ""
    msg = output.choices[0].message
    if isinstance(msg.content, str):
        return ""
    parts: list[str] = []
    for block in msg.content_list:
        if isinstance(block, ContentReasoning):
            if block.summary and block.summary.strip():
                parts.append(block.summary.strip())
            elif not block.redacted and block.reasoning.strip():
                parts.append(block.reasoning.strip())
    return "\n".join(parts).strip()


def _task_answer_text(state: TaskState) -> str:
    """Final model answer for the task (completion or assistant message text)."""
    completion = (state.output.completion or "").strip()
    if completion:
        return completion
    if state.output.choices:
        return state.output.message.text.strip()
    return ""


def _assistant_visible_text(output: ModelOutput) -> str:
    """Best-effort extract user-visible text (handles reasoning-only first chunks)."""
    text = (output.completion or "").strip()
    if text:
        return text
    if not output.choices:
        return ""
    msg = output.choices[0].message
    if isinstance(msg.content, str):
        return msg.content.strip()
    parts: list[str] = []
    for block in msg.content_list:
        if isinstance(block, ContentText) and block.text.strip():
            parts.append(block.text.strip())
        elif isinstance(block, ContentReasoning):
            if block.summary and block.summary.strip():
                parts.append(block.summary.strip())
            elif not block.redacted and block.reasoning.strip():
                parts.append(block.reasoning.strip())
    return "\n".join(parts).strip()


def _parse_confidence_text(text: str) -> float | None:
    match = re.search(r"[-+]?\d*\.?\d+", text)
    if not match:
        return None
    value = float(match.group(0))
    if 1.0 < value <= 100.0:
        value = value / 100.0
    return value
