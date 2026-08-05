from typing import Protocol, runtime_checkable

from ._verdict import JudgeVerdict


@runtime_checkable
class Judge(Protocol):
    """Callable that compares two responses to the same prompt.

    Implementations may use a model (`llm_judge`), a human, or any other
    strategy. The protocol intentionally sees only the prompt and the two
    candidate responses — contestant identities are kept inside
    `pairwise_scorer` to avoid biasing the judge.
    """

    async def __call__(
        self,
        prompt: str,
        response_a: str,
        response_b: str,
    ) -> JudgeVerdict: ...
