import math
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError
from typing_extensions import TypedDict

from inspect_ai.log._file import read_eval_log
from inspect_ai.model import compute_model_cost
from inspect_ai.model._model_data.model_data import ModelCost, ModelCostTier
from inspect_ai.model._model_output import ModelUsage


def test_completion_deserialization() -> None:
    log_file = (
        Path(__file__).parent.parent
        / "log"
        / "test_list_logs"
        / "2024-11-05T13-31-45-05-00_input-task_8zXjbRzCWrL9GXiXo2vus9.json"
    )
    log = read_eval_log(log_file)
    assert log.samples
    assert len(log.samples[0].output.completion) > 0


def test_model_usage_addition() -> None:
    usage1 = ModelUsage(
        input_tokens=1,
        output_tokens=2,
        total_tokens=3,
        input_tokens_cache_write=4,
        input_tokens_cache_read=5,
        reasoning_tokens=6,
    )
    usage2 = ModelUsage(
        input_tokens=10,
        output_tokens=20,
        total_tokens=30,
        input_tokens_cache_write=40,
        input_tokens_cache_read=50,
        reasoning_tokens=60,
    )

    result = usage1 + usage2

    assert result.input_tokens == 11
    assert result.output_tokens == 22
    assert result.total_tokens == 33
    assert result.input_tokens_cache_write == 44
    assert result.input_tokens_cache_read == 55
    assert result.reasoning_tokens == 66


def test_model_usage_addition_with_none_fields() -> None:
    usage1 = ModelUsage(
        input_tokens_cache_write=None,
        input_tokens_cache_read=2,
        reasoning_tokens=None,
    )
    usage2 = ModelUsage(
        input_tokens_cache_write=1,
        input_tokens_cache_read=None,
        reasoning_tokens=None,
    )

    result = usage1 + usage2

    assert result.input_tokens_cache_write == 1
    assert result.input_tokens_cache_read == 2
    assert result.reasoning_tokens is None


def test_compute_model_cost_basic() -> None:
    cost_data = ModelCost(
        input=1000.0, output=2000.0, input_cache_write=0.0, input_cache_read=0.0
    )
    usage = ModelUsage(input_tokens=3, output_tokens=4, total_tokens=7)

    # (3 * 1000 + 4 * 2000) / 1_000_000 = 0.011
    assert compute_model_cost(cost_data, usage) == 0.011


def test_compute_model_cost_with_cache_tokens() -> None:
    cost_data = ModelCost(
        input=1000.0, output=2000.0, input_cache_write=1500.0, input_cache_read=100.0
    )
    usage = ModelUsage(
        input_tokens=10,
        output_tokens=5,
        total_tokens=15,
        input_tokens_cache_write=20,
        input_tokens_cache_read=30,
    )

    # input:       10 * 1000 / 1M = 0.01
    # output:       5 * 2000 / 1M = 0.01
    # cache_write: 20 * 1500 / 1M = 0.03
    # cache_read:  30 *  100 / 1M = 0.003
    # total: 0.053
    assert math.isclose(compute_model_cost(cost_data, usage), 0.053)


def test_compute_model_cost_with_all_token_types() -> None:
    cost_data = ModelCost(
        input=1000.0, output=2000.0, input_cache_write=1500.0, input_cache_read=100.0
    )
    usage = ModelUsage(
        input_tokens=10,
        output_tokens=20,
        total_tokens=30,
        reasoning_tokens=8,
        input_tokens_cache_write=20,
        input_tokens_cache_read=30,
    )

    # input:       10 * 1000 / 1M = 0.01
    # output:      20 * 2000 / 1M = 0.04  (includes reasoning tokens)
    # cache_write: 20 * 1500 / 1M = 0.03
    # cache_read:  30 *  100 / 1M = 0.003
    # total: 0.083
    assert math.isclose(compute_model_cost(cost_data, usage), 0.083)


def test_compute_model_cost_no_double_billing_cached_tokens() -> None:
    """Verify cached tokens are not double-billed.

    With normalized usage (input_tokens excludes cache), the cost should be:
    - Non-cached input tokens charged at full input rate
    - Cached tokens charged at cache read rate only
    """
    cost_data = ModelCost(
        input=3.0,  # $3/M for input
        output=15.0,  # $15/M for output
        input_cache_write=0.0,
        input_cache_read=1.5,  # $1.50/M for cached (50% discount)
    )
    # Simulating OpenAI-style response after normalization:
    # API reports prompt_tokens=1000 (inclusive), cached=600
    # After normalization: input_tokens=400 (non-cached), cache_read=600
    usage = ModelUsage(
        input_tokens=400,
        output_tokens=100,
        total_tokens=1100,
        input_tokens_cache_read=600,
    )

    cost = compute_model_cost(cost_data, usage)

    # input:      400 * 3.0 / 1M = 0.0012
    # output:     100 * 15.0 / 1M = 0.0015
    # cache_read: 600 * 1.5 / 1M = 0.0009
    # total: 0.0036
    expected = (400 * 3.0 + 100 * 15.0 + 600 * 1.5) / 1_000_000
    assert math.isclose(cost, expected)


def test_compute_model_cost_1h_cache_write_billed_above_5m_rate() -> None:
    """1-hour cache writes bill at 2x base input, vs 1.25x for 5-minute writes."""
    base_input = 3.0
    cost_data = ModelCost(
        input=base_input,
        output=15.0,
        input_cache_write=base_input * 1.25,  # the 5-minute rate
        input_cache_read=0.3,
    )
    usage = ModelUsage(
        input_tokens=0,
        output_tokens=0,
        total_tokens=1_000_000,
        input_tokens_cache_write=1_000_000,
    )

    # exactly 1M cache-write tokens, so each cost is the effective $/M rate
    assert math.isclose(compute_model_cost(cost_data, usage, "5m"), base_input * 1.25)
    assert math.isclose(compute_model_cost(cost_data, usage, "1h"), base_input * 2.0)

    # an unspecified TTL keeps the previous (5-minute) behaviour
    assert math.isclose(compute_model_cost(cost_data, usage), base_input * 1.25)


def test_compute_model_cost_cache_ttl_does_not_affect_other_tokens() -> None:
    cost_data = ModelCost(
        input=1000.0, output=2000.0, input_cache_write=0.0, input_cache_read=100.0
    )
    usage = ModelUsage(
        input_tokens=10,
        output_tokens=5,
        total_tokens=45,
        input_tokens_cache_read=30,
    )

    assert math.isclose(
        compute_model_cost(cost_data, usage, "1h"),
        compute_model_cost(cost_data, usage),
    )


class _Rates(TypedDict):
    input: float
    output: float
    input_cache_write: float
    input_cache_read: float


# OpenAI gpt-5.5 pricing: standard up to 272k prompt tokens, long-context above
_STANDARD = _Rates(
    input=5.00, output=30.00, input_cache_write=5.00, input_cache_read=0.50
)
_LONG = _Rates(
    input=10.00, output=45.00, input_cache_write=10.00, input_cache_read=1.00
)
_LONG_CONTEXT = 272_000


def _tiered_cost() -> ModelCost:
    return ModelCost(
        **_STANDARD,
        tiers=[
            ModelCostTier(max_input_tokens=_LONG_CONTEXT, **_STANDARD),
            ModelCostTier(max_input_tokens=None, **_LONG),
        ],
    )


def _call(
    prompt: int,
    output: int = 5_000,
    input_tokens_cache_read: int | None = None,
    input_tokens_cache_write: int | None = None,
) -> ModelUsage:
    return ModelUsage(
        input_tokens=prompt,
        output_tokens=output,
        total_tokens=prompt
        + output
        + (input_tokens_cache_read or 0)
        + (input_tokens_cache_write or 0),
        input_tokens_cache_read=input_tokens_cache_read,
        input_tokens_cache_write=input_tokens_cache_write,
    )


def test_compute_model_cost_tiers_bill_each_call_at_its_band() -> None:
    cost_data = _tiered_cost()

    # (50k * 5 + 5k * 30) / 1M = 0.4000
    assert math.isclose(compute_model_cost(cost_data, _call(50_000)), 0.4000)
    # (300k * 10 + 5k * 45) / 1M = 3.2250
    assert math.isclose(compute_model_cost(cost_data, _call(300_000)), 3.2250)


def test_compute_model_cost_tier_bound_is_inclusive() -> None:
    cost_data = _tiered_cost()

    assert math.isclose(
        compute_model_cost(cost_data, _call(_LONG_CONTEXT, output=0)),
        _LONG_CONTEXT * 5.00 / 1_000_000,
    )
    assert math.isclose(
        compute_model_cost(cost_data, _call(_LONG_CONTEXT + 1, output=0)),
        (_LONG_CONTEXT + 1) * 10.00 / 1_000_000,
    )


def test_compute_model_cost_three_tiers_selects_middle_band() -> None:
    def tier(max_input_tokens: int | None, input: float) -> ModelCostTier:
        return ModelCostTier(
            max_input_tokens=max_input_tokens,
            input=input,
            output=2 * input,
            input_cache_write=0.0,
            input_cache_read=0.0,
        )

    cost_data = ModelCost(
        input=1.0,
        output=2.0,
        input_cache_write=0.0,
        input_cache_read=0.0,
        # deliberately unsorted: selection must not depend on declaration order
        tiers=[tier(None, 4.0), tier(32_000, 1.0), tier(128_000, 2.0)],
    )

    assert math.isclose(compute_model_cost(cost_data, _call(10_000, output=0)), 0.01)
    assert math.isclose(compute_model_cost(cost_data, _call(64_000, output=0)), 0.128)
    assert math.isclose(compute_model_cost(cost_data, _call(200_000, output=0)), 0.8)


def test_compute_model_cost_tier_uses_prompt_including_cached_tokens() -> None:
    cost_data = _tiered_cost()
    # 50k billed input + 250k cache-read = 300k prompt, above 272k
    usage = _call(50_000, output=5_000, input_tokens_cache_read=250_000)

    # long band: (50k * 10 + 5k * 45 + 250k * 1) / 1M = 0.9750
    # (selecting on input_tokens alone would give the standard band: 0.5250)
    assert math.isclose(compute_model_cost(cost_data, usage), 0.9750)


def test_compute_model_cost_tiers_bill_per_call_not_accumulated_usage() -> None:
    cost_data = _tiered_cost()

    # forty 50k calls cost $16.00; one 2M-token call at the sum costs $29.00
    per_call_total = 40 * compute_model_cost(cost_data, _call(50_000))
    assert math.isclose(per_call_total, 16.00)
    assert math.isclose(
        compute_model_cost(cost_data, _call(2_000_000, output=200_000)), 29.00
    )


def test_compute_model_cost_1h_cache_write_uses_selected_band_rate() -> None:
    cost_data = _tiered_cost()
    usage = _call(0, output=0, input_tokens_cache_write=1_000_000)

    # 1M cache-write tokens select the long band ($10/M at the 5m rate)
    assert math.isclose(compute_model_cost(cost_data, usage, "5m"), 10.00)
    assert math.isclose(compute_model_cost(cost_data, usage, "1h"), 10.00 * 2.0 / 1.25)


def test_compute_model_cost_top_level_rates_ignored_when_tiers_set() -> None:
    cost_data = ModelCost(
        **_LONG,
        tiers=[
            ModelCostTier(max_input_tokens=_LONG_CONTEXT, **_STANDARD),
            ModelCostTier(max_input_tokens=None, **_LONG),
        ],
    )

    assert math.isclose(compute_model_cost(cost_data, _call(50_000)), 0.4000)


def test_compute_model_cost_tiers_round_trip_from_yaml() -> None:
    loaded = yaml.safe_load(
        """
        input: 5.00
        output: 30.00
        input_cache_write: 5.00
        input_cache_read: 0.50
        tiers:
          - max_input_tokens: 272000
            input: 5.00
            output: 30.00
            input_cache_write: 5.00
            input_cache_read: 0.50
          - max_input_tokens: null
            input: 10.00
            output: 45.00
            input_cache_write: 10.00
            input_cache_read: 1.00
        """
    )
    cost_data = ModelCost(**loaded)

    assert math.isclose(compute_model_cost(cost_data, _call(50_000)), 0.4000)
    assert math.isclose(compute_model_cost(cost_data, _call(300_000)), 3.2250)


def test_model_cost_without_tiers_is_unchanged() -> None:
    cost_data = ModelCost(**_STANDARD)

    assert cost_data.tiers is None
    assert math.isclose(compute_model_cost(cost_data, _call(300_000)), 1.6500)


def test_model_cost_tiers_require_exactly_one_unbounded_band() -> None:
    with pytest.raises(ValidationError, match="unbounded"):
        ModelCost(**_STANDARD, tiers=[])
    with pytest.raises(ValidationError, match="unbounded"):
        ModelCost(
            **_STANDARD,
            tiers=[ModelCostTier(max_input_tokens=_LONG_CONTEXT, **_STANDARD)],
        )
    with pytest.raises(ValidationError, match="unbounded"):
        ModelCost(
            **_STANDARD,
            tiers=[
                ModelCostTier(max_input_tokens=None, **_STANDARD),
                ModelCostTier(max_input_tokens=None, **_LONG),
            ],
        )


def test_model_cost_tiers_require_unique_bounds() -> None:
    with pytest.raises(ValidationError, match="unique"):
        ModelCost(
            **_STANDARD,
            tiers=[
                ModelCostTier(max_input_tokens=_LONG_CONTEXT, **_STANDARD),
                ModelCostTier(max_input_tokens=_LONG_CONTEXT, **_LONG),
                ModelCostTier(max_input_tokens=None, **_LONG),
            ],
        )


def test_model_cost_tier_rejects_negative_bound_and_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        ModelCostTier(max_input_tokens=-1, **_STANDARD)
    with pytest.raises(ValidationError, match="max_input_token"):
        ModelCostTier.model_validate({"max_input_token": 272000, **_STANDARD})
