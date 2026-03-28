"""Run a small HarmActionsEval evaluation using OpenAI-compatible settings from .env.

Required .env values:
    OPENAI_MODEL
Recommended .env values:
    OPENAI_BASE_URL
    OPENAI_API_KEY

Example:
    python examples/harmactionseval.py
"""

from __future__ import annotations

import os

from inspect_ai import Task, eval, task
from inspect_ai.tasks import harmactionseval


def _load_env_value(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} must be set in your .env file or environment.")
    return value


def _openai_compatible_model() -> str:
    model = _load_env_value("OPENAI_MODEL")
    return model if "/" in model else f"openai/{model}"


@task
def sample_harmactionseval(k: int = 1, limit: int = 5) -> Task:
    return harmactionseval(k=k, limit=limit)


if __name__ == "__main__":
    eval(
        sample_harmactionseval(),
        model=_openai_compatible_model(),
        model_args={"responses_api": False},
        display="plain",
        max_subprocesses=1,
    )
