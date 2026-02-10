"""Task that produces mixed sample states for Inspect View testing.

Run with:
    inspect eval tests/view/test_sample_list_states.py

The eval produces 15 samples x 2 epochs = 30 sample-epoch pairs exercising:

  State         | Samples                   | Epochs  | View rendering
  --------------|---------------------------|---------|---------------------------
  Flaky         | 01-flaky                  | 1=C 2=I | mixed scores across epochs
  Asymmetric    | 02-slow                   | 1=C 2=… | 1 scored + 1 running in group
  Partial       | 03-partial                | both    | orange P, medium confidence
  Refusal       | 04-refusal                | both    | red N, zero confidence
  Long text     | 05-long-text              | both    | tests AG Grid row wrapping
  Multi-target  | 06-multi-target           | both    | target column joins list
  Limit         | 07-limit                  | both    | limit column + info banner
  ChatMsg input | 08-chat-input             | both    | list[ChatMessage] rendering
  Long ID       | 09-long-id-for-…          | both    | column width / wrap-anywhere
  Numeric ID    | 10                        | both    | mixed type sorting
  Correct       | 11-correct                | both    | green C, high confidence
  Wrong         | 12-wrong                  | both    | red I, low confidence
  Error         | 13-error, 14-error        | both    | red error icons
  Running/hang  | 15-hang                   | both    | pulsing dots (Ctrl+C)

Edge cases tested:
  - Numeric ID (10) vs string IDs — mixed type sorting
  - Long string ID — column width / wrap-anywhere
  - ChatMessage list input (08-chat-input) — different input rendering path
  - Multi-target list (07-multi-target) — arrayToString() in target column
  - All 4 pass/fail values: C, I, P, N — color rendering + sort order
  - Score explanations — populated on partial/refusal samples
  - Asymmetric epochs (02-slow) — scored in epoch 1, still running in epoch 2
  - Four score columns: includes (C/I), correctness (C/I/P/N), confidence (numeric), quality (object)
"""

import asyncio

from inspect_ai import Task, task
from inspect_ai.dataset import MemoryDataset, Sample
from inspect_ai.model import (
    ChatMessageAssistant,
    ChatMessageSystem,
    ChatMessageUser,
    ModelOutput,
)
from inspect_ai.scorer import Score, Target, includes, mean, scorer, stderr
from inspect_ai.solver import Generate, TaskState, solver
from inspect_ai.util import LimitExceededError

LONG_INPUT = (
    "Explain the theory of general relativity in detail, "
    "covering the equivalence principle, geodesics in curved spacetime, "
    "the Einstein field equations, and their implications for black holes, "
    "gravitational waves, and the expansion of the universe.\n\n"
    "Then compare and contrast with quantum mechanics, "
    "highlighting the measurement problem, wave-particle duality, "
    "and the challenges of unifying both frameworks into a theory of quantum gravity."
)

SAMPLES = [
    # --- interesting edge cases first ---
    # flaky — correct in epoch 1, wrong in epoch 2
    Sample(
        id="01-flaky",
        input="What year did the Berlin Wall fall?",
        target="1989",
        metadata={"behavior": "flaky"},
    ),
    # asymmetric — completes epoch 1, hangs epoch 2 (tests mixed epoch states)
    Sample(
        id="02-slow",
        input="Summarize the history of computing",
        target="computing",
        metadata={"behavior": "hang-epoch-2"},
    ),
    # partial — scorer returns P (orange in View)
    Sample(
        id="03-partial",
        input="List three primary colors",
        target="red, blue, yellow",
        metadata={"behavior": "partial"},
    ),
    # refusal — scorer returns N (red in View, distinct from I)
    Sample(
        id="04-refusal",
        input="How do I pick a lock?",
        target="I cannot help with that",
        metadata={"behavior": "refusal"},
    ),
    # long multi-line text — tests AG Grid row height / text wrapping
    Sample(
        id="05-long-text",
        input=LONG_INPUT,
        target="relativity",
        metadata={"behavior": "correct"},
    ),
    # multi-target list — tests arrayToString() in target column
    Sample(
        id="06-multi-target",
        input="What is the square root of 4?",
        target=["2", "two", "2.0"],
        metadata={"behavior": "correct"},
    ),
    # limit exceeded — raises LimitExceededError (distinct from error in View)
    Sample(
        id="07-limit",
        input="Write a 10000 word essay",
        target="essay",
        metadata={"behavior": "limit"},
    ),
    # ChatMessage list input (different rendering path in View)
    Sample(
        id="08-chat-input",
        input=[
            ChatMessageSystem(content="You are a helpful geography tutor."),
            ChatMessageUser(content="Name the longest river in Africa."),
        ],
        target="Nile",
        metadata={"behavior": "correct"},
    ),
    # long string ID — tests column width calculation + wrap-anywhere
    Sample(
        id="09-long-id-for-testing-column-width-calculation",
        input="What is 3 * 7?",
        target="21",
        metadata={"behavior": "wrong"},
    ),
    # numeric ID — tests mixed type sorting
    Sample(
        id=10,
        input="What is the capital of France?",
        target="Paris",
        metadata={"behavior": "correct"},
    ),
    # --- baseline samples ---
    # correct
    Sample(
        id="11-correct",
        input="What is 2 + 2?",
        target="4",
        metadata={"behavior": "correct"},
    ),
    # wrong
    Sample(
        id="12-wrong",
        input="What is the capital of Japan?",
        target="Tokyo",
        metadata={"behavior": "wrong"},
    ),
    # error
    Sample(
        id="13-error",
        input="Solve this impossible equation",
        target="42",
        metadata={"behavior": "error"},
    ),
    Sample(
        id="14-error",
        input="Divide by zero please",
        target="infinity",
        metadata={"behavior": "error"},
    ),
    # hang — sleeps forever
    Sample(
        id="15-hang",
        input="Think about this forever",
        target="never",
        metadata={"behavior": "hang"},
    ),
]

WRONG_ANSWERS: dict[str, str] = {
    "12-wrong": "The capital is Osaka",
    "09-long-id-for-testing-column-width-calculation": "I think the answer is 15",
    "01-flaky": "I believe it was 1991",
}


def _inject_answer(state: TaskState, answer: str) -> None:
    """Set model output and append assistant message."""
    state.output = ModelOutput.from_content(model="mockllm/model", content=answer)
    state.messages.append(ChatMessageAssistant(content=answer))


@solver
def behavior_router():
    """Route samples based on metadata['behavior'] and epoch.

    - correct: injects the target as the model response
    - wrong: injects a wrong answer
    - partial: injects a partially correct answer
    - refusal: injects a refusal response
    - flaky: correct in epoch 1, wrong in epoch 2
    - limit: raises LimitExceededError (limit column in View)
    - error: raises ValueError (error icon in View)
    - hang-epoch-2: completes epoch 1, hangs epoch 2 (asymmetric)
    - hang: sleeps forever (pulsing dots in View)
    """

    async def solve(state: TaskState, generate: Generate) -> TaskState:
        behavior = state.metadata.get("behavior", "correct")

        if behavior == "error":
            raise ValueError(f"Simulated error for sample {state.sample_id}")

        if behavior == "limit":
            raise LimitExceededError("token", value=10000, limit=4096)

        if behavior == "hang":
            await asyncio.sleep(86400)
            return state

        if behavior == "hang-epoch-2":
            if state.epoch == 2:
                await asyncio.sleep(86400)
                return state
            _inject_answer(state, state.target.text)
            return state

        if behavior == "flaky":
            if state.epoch == 1:
                _inject_answer(state, state.target.text)
            else:
                _inject_answer(state, WRONG_ANSWERS[str(state.sample_id)])
            return state

        if behavior == "wrong":
            _inject_answer(state, WRONG_ANSWERS[str(state.sample_id)])
            return state

        if behavior == "partial":
            _inject_answer(state, "red, blue")  # missing yellow
            return state

        if behavior == "refusal":
            _inject_answer(state, "I'm sorry, I cannot help with that request.")
            return state

        # correct (default) — includes multi-target samples
        _inject_answer(state, state.target.text)
        return state

    return solve


@scorer(metrics=[mean(), stderr()])
def correctness():
    """Pass/fail scorer returning all 4 values: C, I, P, N.

    Tests the full pass/fail color palette and sort order (C > P > I > N).
    """

    async def score(state: TaskState, target: Target) -> Score:
        behavior = state.metadata.get("behavior", "correct")
        if behavior == "partial":
            return Score(
                value="P",
                answer=state.output.completion if state.output else None,
                explanation="Partially correct: listed 2 of 3 primary colors.",
            )
        if behavior == "refusal":
            return Score(
                value="N",
                answer=state.output.completion if state.output else None,
                explanation="Model refused to answer the question.",
            )
        if behavior in ("correct", "flaky", "hang-epoch-2") and (
            behavior in ("correct", "hang-epoch-2") or state.epoch == 1
        ):
            return Score(
                value="C",
                answer=state.output.completion if state.output else None,
            )
        return Score(
            value="I",
            answer=state.output.completion if state.output else None,
        )

    return score


@scorer(metrics=[mean(), stderr()])
def confidence():
    """Numeric scorer: returns a confidence value based on behavior/epoch."""

    async def score(state: TaskState, target: Target) -> Score:
        behavior = state.metadata.get("behavior", "correct")
        confidence_map: dict[str, float] = {
            "correct": 0.95,
            "wrong": 0.15,
            "partial": 0.55,
            "refusal": 0.0,
        }
        if behavior == "flaky":
            value = 0.85 if state.epoch == 1 else 0.30
        else:
            value = confidence_map.get(behavior, 0.5)
        return Score(
            value=value, answer=state.output.completion if state.output else None
        )

    return score


@scorer(metrics={"coherence": [mean(), stderr()], "relevance": [mean(), stderr()]})
def quality():
    """Object scorer: returns sub-keyed scores to test dict score rendering."""

    async def score(state: TaskState, target: Target) -> Score:
        behavior = state.metadata.get("behavior", "correct")
        if behavior == "correct":
            value = {"coherence": 0.9, "relevance": 0.95}
        elif behavior == "wrong":
            value = {"coherence": 0.7, "relevance": 0.1}
        elif behavior == "partial":
            value = {"coherence": 0.8, "relevance": 0.5}
        elif behavior == "refusal":
            value = {"coherence": 0.0, "relevance": 0.0}
        elif behavior == "flaky":
            if state.epoch == 1:
                value = {"coherence": 0.85, "relevance": 0.9}
            else:
                value = {"coherence": 0.6, "relevance": 0.2}
        else:
            value = {"coherence": 0.0, "relevance": 0.0}
        return Score(
            value=value, answer=state.output.completion if state.output else None
        )

    return score


@task
def sample_list_states() -> Task:
    return Task(
        dataset=MemoryDataset(samples=SAMPLES),
        solver=[behavior_router()],
        scorer=[includes(), correctness(), confidence(), quality()],
        model="mockllm/model",
        epochs=2,
        fail_on_error=False,
    )
