# tests/test_idealized_model_usage.py
from __future__ import annotations

import pprint
from datetime import datetime

import pytest

from inspect_ai import Task, eval
from inspect_ai.dataset import Sample
from inspect_ai.log import ModelEvent
from inspect_ai.model._chat_message import ChatMessage, ChatMessageUser
from inspect_ai.model._model import (
    get_model,
    idealized_model_usage,
)
from inspect_ai.model._model_output import ModelOutput, ModelUsage
from inspect_ai.solver import generate


# ────────────────────────────────────────────────────────────────────────────
# helpers
# ────────────────────────────────────────────────────────────────────────────
def simulate_out(*, write: int, read: int, output: int | None) -> ModelOutput:
    """Fabricate a ModelOutput."""
    mo = ModelOutput.from_content("mockllm/model", "A (stub)")

    if output is not None:
        mo.usage = ModelUsage(
            input_tokens_cache_write=write,
            input_tokens_cache_read=read,
            output_tokens=output,
        )
    else:  # usage missing
        mo.usage = None
    return mo


def sig(msgs: list[ChatMessage]) -> str:
    """Tiny dump for debugging output inside failing assert reports"""
    return " | ".join(m.content for m in msgs)


def dump_state(step: str, msgs: list[ChatMessage], usage) -> None:
    """Pretty-print conversation and counters for debugging."""
    print(f"\n===== {step} =====")
    for i, m in enumerate(msgs, 1):
        role = getattr(m, "role", m.__class__.__name__).upper()
        # collapse ContentText / ContentReasoning if present
        if isinstance(m.content, list):
            text = "".join(
                getattr(c, "text", getattr(c, "reasoning", str(c))) for c in m.content
            )
        else:
            text = m.content
        print(f"{i:02d} {role:<10}: {text}")
    print("idealised-usage:", pprint.pformat(usage.model_dump(), compact=True))
    print("=" * 60)


# ────────────────────────────────────────────────────────────────────────────
# 1. Instance-level perfect-cache accounting
# ────────────────────────────────────────────────────────────────────────────
test_matrix_instance = [
    (
        "simple prefix growth",
        [
            simulate_out(write=4, read=0, output=3),  # U1
            simulate_out(write=8, read=4, output=5),  # U1 A1 U2
            simulate_out(write=11, read=12, output=2),  # U1 A1 U2 A2 U3
        ],
        [
            (["U1"], 4, 4, 3),
            (["U1", "A1", "U2"], 16, 12, 8),
            (["U1", "A1", "U2", "U3"], 39, 23, 10),
        ],
    ),
    (
        "repeat identical prompt (full hit)",
        [
            simulate_out(write=4, read=0, output=1),
            simulate_out(write=0, read=4, output=1),
        ],
        [
            (["U1"], 4, 4, 1),
            (["U1"], 8, 4, 2),
        ],
    ),
    (
        "shorter prompt - prefix miss",
        [
            simulate_out(write=10, read=0, output=2),  # U1 U2 U3
            simulate_out(write=4, read=0, output=2),  # U1
        ],
        [
            (["1", "2", "3"], 10, 10, 2),
            (["1"], 14, 14, 4),
        ],
    ),
]


@pytest.mark.anyio
@pytest.mark.parametrize("desc,custom_outputs,steps", test_matrix_instance)
async def test_idealized_model_usage_instance(desc, custom_outputs, steps):
    """Validate *per-instance* IdealizedModelUsage numbers for various scenarios."""
    async with get_model("mockllm/model", custom_outputs=custom_outputs) as model:
        msgs: list[ChatMessage] = []
        for prompt, exp_I, exp_U, exp_O in steps:
            # rebuild conversation up to 'prompt'
            msgs = [ChatMessageUser(content=p) for p in prompt]
            await model.generate(msgs)

            ideal = model.idealized_model_usage
            assert (
                ideal.input_tokens,
                ideal.input_tokens_cache_write,
                ideal.output_tokens,
            ) == (
                exp_I,
                exp_U,
                exp_O,
            ), f"{desc} / prompt=[{sig(msgs)}]"


@pytest.mark.anyio
async def test_idealised_usage_four_turns_with_cache(capsys) -> None:
    """
    Test of a 4 turn conversation with caching

    Conversation we simulate             provider reports
    ───────────────────────────────────────────────────────────────
    call-1  U1                → write 4  read 0   out 3
    call-2  U1 A1 U2          → write 8  read 4   out 5
    call-3  U1 A1 U2 A2 U3    → write 11 read 12  out 2

    call-4  U1 A1 U4          → write 10  read 4   out 5. Note U1 A1 were previously sent, but _with U2_ which we've now dropped - the best prefix we can find in the cache is just U1

    Ideal cache charges     4 + 8 + 11 = 23 prompt tokens
    Completions               3 + 5 + 2  = 10 tokens
    """
    custom_outputs = [
        simulate_out(write=4, read=0, output=3),  # U1
        simulate_out(write=8, read=4, output=5),  # U1 A1 U2
        simulate_out(write=11, read=12, output=2),  # U1 A1 U2 A2 U3
        simulate_out(write=10, read=4, output=5),  # U1 A1 U4
    ]

    async with get_model("mockllm/model", custom_outputs=custom_outputs) as model:
        # ── call-1 ─────────────────────────────────────────────────────────
        msgs: list[ChatMessage] = [ChatMessageUser(content="U1: 4 unique tokens")]
        out1 = await model.generate(msgs)
        msgs.append(out1.choices[0].message)  # A1
        dump_state("after call-1", msgs, model.idealized_model_usage)

        # ── call-2 ─────────────────────────────────────────────────────────
        msgs.append(ChatMessageUser(content="U2: 5 unique tokens"))
        out2 = await model.generate(msgs)
        msgs.append(out2.choices[0].message)  # A2
        dump_state("after call-2", msgs, model.idealized_model_usage)

        # ── call-3 ─────────────────────────────────────────────────────────
        msgs.append(ChatMessageUser(content="U3: 6 unique tokens"))
        await model.generate(msgs)
        dump_state("after call-3", msgs, model.idealized_model_usage)

        ideal = model.idealized_model_usage
        assert ideal.input_tokens == 39  # 4 + 8+4 + 11+12
        assert ideal.input_tokens_cache_write == 23  # total unique tokens
        assert ideal.output_tokens == 10  # 3 + 5 + 2

        new_msgs = msgs[:2].copy()
        new_msgs.append(ChatMessageUser(content="U4: 7 unique tokens"))
        await model.generate(new_msgs)
        dump_state("after call-4", new_msgs, model.idealized_model_usage)

        ideal = model.idealized_model_usage
        assert ideal.input_tokens == 53  # 4 + 8+4 + 11+12 + 10+4
        assert ideal.input_tokens_cache_write == 33  # total unique tokens
        assert ideal.output_tokens == 15  # 3 + 5 + 2 + 5


# ────────────────────────────────────────────────────────────────────────────
# 2. ContextVar aggregation
# ────────────────────────────────────────────────────────────────────────────
@pytest.mark.anyio
async def test_ideal_usage_contextvar() -> None:
    """
    Validate relevant ContextVars are configured as expected.

    Ensures that record_idealized_model_usage() populates the task-local
    ContextVar exactly once per provider call.
    """
    # 2 calls, different models => two independent entries
    outputs_A = [simulate_out(write=5, read=0, output=1)]
    outputs_B = [simulate_out(write=3, read=0, output=2)]

    async with (
        get_model("mockllm/A", custom_outputs=outputs_A) as model_A,
        get_model("mockllm/B", custom_outputs=outputs_B) as model_B,
    ):
        await model_A.generate([ChatMessageUser(content="foo")])
        await model_B.generate([ChatMessageUser(content="bar")])

        store = idealized_model_usage()

        assert set(store.keys()) == {str(model_A), str(model_B)}

        ua = store[str(model_A)]
        ub = store[str(model_B)]

        assert (
            ua.input_tokens == 5
            and ua.input_tokens_cache_write == 5
            and ua.output_tokens == 1
        )
        assert (
            ub.input_tokens == 3
            and ub.input_tokens_cache_write == 3
            and ub.output_tokens == 2
        )


def sample_cache_hit(sample) -> bool:
    return any(isinstance(e, ModelEvent) and e.cache == "read" for e in sample.events)


def test_eval_populates_idealized_model_usage():
    """
    Ensure perfect cache usage is updated even when the local cache is used.

    First eval populates the inspect cache (MISS), second eval is served
    from it (HIT) but must still update perfect-cache accounting.
    """
    timestamp = str(datetime.now())

    custom_outputs = [simulate_out(write=4, read=0, output=1)]

    log1 = eval(
        Task(
            dataset=[Sample(input=f"What is the timestamp: {timestamp}")],
            solver=[generate(cache=True)],
        ),
        model="mockllm/model",
        model_args={"custom_outputs": custom_outputs},
    )[0]

    assert log1.samples and not sample_cache_hit(log1.samples[0])
    assert log1.stats.model_usage
    assert log1.stats.idealized_model_usage

    # ---- run #2  (cache hit) --------------------------------------------
    log2 = eval(
        Task(
            dataset=[Sample(input=f"What is the timestamp: {timestamp}")],
            solver=[generate(cache=True)],
        ),
        model="mockllm/model",
        model_args={"custom_outputs": custom_outputs},
    )[0]
    assert log2.samples and sample_cache_hit(log2.samples[0])
    assert (
        not log2.stats.model_usage
    )  # No expected usage, should have loaded from inspect cache
    assert log2.stats.idealized_model_usage

    # Simulated cache usage _should_ match, even though local inspect cache was used for second request
    assert (
        log1.stats.idealized_model_usage["mockllm/model"]
        == log2.stats.idealized_model_usage["mockllm/model"]
    )
