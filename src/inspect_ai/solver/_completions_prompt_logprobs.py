"""Solver that calls ``/v1/completions`` directly for prompt logprobs.

Designed for perplexity benchmarks that need
``prompt_logprobs`` but cannot use the chat completions API.  The chat
completions endpoint applies the model's chat template, injecting role
markers and special tokens that shift the probability distribution and
contaminate logprob-based metrics.  This solver sends raw prompt text
to ``/v1/completions`` with ``prompt_logprobs`` enabled and populates
``state.output`` so the :func:`~inspect_ai.scorer.target_perplexity`
scorer can read them.

Usage::

    Task(
        dataset=dataset,
        solver=completions_prompt_logprobs(),
        scorer=target_perplexity(),
    )
    log = eval(task, model="vllm/my-model")
"""

from __future__ import annotations

import logging
from typing import Any

from openai import AsyncOpenAI, NotFoundError

from inspect_ai.model import (
    ChatCompletionChoice,
    ChatMessageAssistant,
    Logprob,
    Logprobs,
    ModelOutput,
    ModelUsage,
    TopLogprob,
    get_model,
)
from inspect_ai.model._model_output import as_stop_reason
from inspect_ai.model._openai import parse_vllm_prompt_logprobs_raw

from ._solver import Generate, Solver, solver
from ._task_state import TaskState

logger = logging.getLogger(__name__)


async def _resolve_base_url(override: str | None) -> str:
    """Get the vLLM base URL from override or the active model.

    Returns a URL ending in ``/v1`` suitable for the OpenAI SDK
    ``base_url`` parameter.

    For lazy-init providers (e.g. vLLM with ``lazy_init=True``), the
    server may not have started yet.  This function triggers startup
    via ``_ensure_server_started()`` before reading ``base_url``.
    """
    if override:
        url = override.rstrip("/")
        if not url.endswith("/v1"):
            url = url + "/v1"
        return url
    model = get_model()
    api = getattr(model, "api", None)
    if api is None:
        raise RuntimeError(
            "completions_prompt_logprobs: active model has no 'api' attribute. "
            "Pass base_url explicitly or use a vLLM model."
        )
    # The vLLM provider starts its server lazily on the first
    # generate() call (see VLLMAPI.generate which also calls
    # _ensure_server_started as its first step).  Since this solver
    # bypasses generate() and creates its own client, we need to
    # trigger the same startup so that base_url is available.
    ensure_started = getattr(api, "_ensure_server_started", None)
    if ensure_started is not None:
        await ensure_started()
    base_url = getattr(api, "base_url", None)
    if not base_url:
        base_url = getattr(api, "_init_base_url", None)
    if not base_url:
        raise RuntimeError(
            "completions_prompt_logprobs: could not determine vLLM base_url. "
            "Pass base_url explicitly."
        )
    return str(base_url).rstrip("/")


def _resolve_model_id(override: str | None) -> str:
    """Get the model ID from override or the active model."""
    if override:
        return override
    model = get_model()
    api = getattr(model, "api", None)
    return str(getattr(api, "model_name", str(model)))


def _resolve_api_key(base_url_override: str | None) -> str | None:
    """Get the API key from the active model provider, if available."""
    if base_url_override is not None:
        return None
    try:
        return getattr(getattr(get_model(), "api", None), "api_key", None)
    except (ValueError, RuntimeError):
        return None


def _parse_completion_logprobs(sdk_logprobs: Any) -> Logprobs | None:
    """Parse ``/v1/completions`` logprobs into inspect_ai Logprobs.

    The completions endpoint returns logprobs as parallel arrays::

        {
            "tokens": [" Paris", "."],
            "token_logprobs": [-0.595, -0.837],
            "top_logprobs": [{" Paris": -0.595}, {".": -0.837}]
        }

    This differs from chat completions which uses a list of objects.
    """
    if sdk_logprobs is None:
        return None

    tokens = getattr(sdk_logprobs, "tokens", None)
    token_logprobs = getattr(sdk_logprobs, "token_logprobs", None)
    if not tokens or not token_logprobs:
        return None

    sdk_top = getattr(sdk_logprobs, "top_logprobs", None)

    result: list[Logprob] = []
    for i, (token, logprob) in enumerate(zip(tokens, token_logprobs)):
        if logprob is None:
            continue
        top_lps: list[TopLogprob] | None = None
        if sdk_top and i < len(sdk_top) and sdk_top[i]:
            top_lps = [TopLogprob(token=t, logprob=lp) for t, lp in sdk_top[i].items()]
        result.append(Logprob(token=token, logprob=logprob, top_logprobs=top_lps))
    return Logprobs(content=result) if result else None


@solver
def completions_prompt_logprobs(
    base_url: str | None = None,
    model_id: str | None = None,
    max_tokens: int = 1,
    temperature: float = 0.0,
    prompt_logprobs: int = 1,
    logprobs: int | None = None,
    timeout: float = 120.0,
) -> Solver:
    """Call ``/v1/completions`` directly for prompt logprob evaluation.

    Bypasses inspect_ai's chat completions path so that perplexity
    scores are not affected by the model's chat template.

    The server URL and model name are auto-detected from the active
    model, so you can typically just write::

        solver=completions_prompt_logprobs()

    Args:
        base_url: Override for the server URL.  Auto-detected from
            the active model if not provided.
        model_id: Override for the model name.  Auto-detected from
            the active model if not provided.
        max_tokens: Tokens to generate (default 1; set low since
            prompt_logprobs is the primary output).
        temperature: Sampling temperature (default 0.0).
        prompt_logprobs: Number of prompt logprobs to request (vLLM
            extension). Set to ``None`` to disable.
        logprobs: Number of completion token logprobs to return.
            ``None`` disables completion logprobs.
        timeout: HTTP request timeout in seconds.
    """
    _client: AsyncOpenAI | None = None
    _url: str | None = None
    _mid: str | None = None

    async def _get_client() -> tuple[AsyncOpenAI, str]:
        nonlocal _client, _url, _mid
        if _client is None:
            _url = await _resolve_base_url(base_url)
            _mid = _resolve_model_id(model_id)
            api_key = _resolve_api_key(base_url)
            _client = AsyncOpenAI(
                base_url=_url,
                api_key=api_key or "no-key",
                timeout=timeout,
            )
        assert _mid is not None
        return _client, _mid

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        if not isinstance(state._input, str):
            raise TypeError(
                "completions_prompt_logprobs requires Sample.input to be a "
                "plain string, not a list of ChatMessage. The /v1/completions "
                "endpoint sends raw text — multi-message inputs are not supported."
            )

        client, mid = await _get_client()

        # Build extra_body for vLLM extensions
        extra_body: dict[str, Any] = {}
        if prompt_logprobs is not None:
            extra_body["prompt_logprobs"] = prompt_logprobs

        try:
            response = await client.completions.create(
                model=mid,
                prompt=state.input_text,
                max_tokens=max_tokens,
                temperature=temperature,
                logprobs=logprobs,
                extra_body=extra_body or None,
            )
        except NotFoundError:
            raise RuntimeError(
                f"Server at {_url} does not support /v1/completions. "
                f"Ensure you are using a vLLM-compatible server."
            ) from None

        # Parse response
        if not response.choices:
            state.output = ModelOutput(model=mid, choices=[])
            return state

        choice = response.choices[0]

        # prompt_logprobs: vLLM extension, lives inside the choice for
        # /v1/completions (unlike chat completions where it's top-level).
        raw_plps = (
            choice.model_extra.get("prompt_logprobs") if choice.model_extra else None
        )
        parsed_prompt_lps = (
            parse_vllm_prompt_logprobs_raw(raw_plps) if raw_plps else None
        )

        # Completion token logprobs (standard completions format)
        parsed_completion_lps = _parse_completion_logprobs(choice.logprobs)

        state.output = ModelOutput(
            model=mid,
            choices=[
                ChatCompletionChoice(
                    message=ChatMessageAssistant(
                        content=choice.text,
                    ),
                    stop_reason=as_stop_reason(choice.finish_reason),
                    logprobs=parsed_completion_lps,
                    prompt_logprobs=parsed_prompt_lps,
                )
            ],
            usage=(
                ModelUsage(
                    input_tokens=response.usage.prompt_tokens,
                    output_tokens=response.usage.completion_tokens,
                    total_tokens=response.usage.total_tokens,
                )
                if response.usage
                else None
            ),
        )

        return state

    return solve
