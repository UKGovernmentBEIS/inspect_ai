import pytest

from inspect_ai.model import GenerateConfig
from inspect_ai.util import AdaptiveConcurrency


def test_generate_config_merge_copies_nested_override_values() -> None:
    base = GenerateConfig(max_tokens=64)
    override = GenerateConfig(
        extra_body={"background": True},
        extra_headers={"x-test-header": "value"},
    )

    merged = base.merge(override)
    assert merged.extra_body == {"background": True}
    assert merged.extra_headers == {"x-test-header": "value"}
    assert merged.extra_body is not override.extra_body
    assert merged.extra_headers is not override.extra_headers

    merged.extra_body["background"] = False
    merged.extra_headers["x-test-header"] = "other"

    assert override.extra_body == {"background": True}
    assert override.extra_headers == {"x-test-header": "value"}


# AdaptiveConcurrency tests


def test_adaptive_connections_defaults() -> None:
    a = AdaptiveConcurrency()
    assert a.min == 4
    assert a.start == 20
    assert a.max == 200
    # advanced tuning fields default to documented values
    assert a.cooldown_seconds == 15.0
    assert a.decrease_factor == 0.8
    assert a.scale_up_percent == 0.05


def test_adaptive_connections_struct() -> None:
    a = AdaptiveConcurrency(min=4, max=80, start=20)
    assert (a.min, a.max, a.start) == (4, 80, 20)


def test_adaptive_connections_shorthand_two_values() -> None:
    a = AdaptiveConcurrency.model_validate("4-80")
    assert (a.min, a.max, a.start) == (4, 80, 20)


def test_adaptive_connections_shorthand_clamps_implicit_start_to_max() -> None:
    # max < default start (20) → start clamped down to max
    a = AdaptiveConcurrency.model_validate("1-15")
    assert (a.min, a.max, a.start) == (1, 15, 15)


def test_adaptive_connections_shorthand_clamps_implicit_start_to_min() -> None:
    # min > default start → start clamped up to min
    a = AdaptiveConcurrency.model_validate("30-100")
    assert (a.min, a.max, a.start) == (30, 100, 30)


def test_adaptive_connections_struct_clamps_implicit_start() -> None:
    # struct form with no explicit start: same clamping behavior as shorthand
    a = AdaptiveConcurrency(min=1, max=15)
    assert (a.min, a.max, a.start) == (1, 15, 15)
    a = AdaptiveConcurrency(min=30, max=100)
    assert (a.min, a.max, a.start) == (30, 100, 30)


def test_adaptive_connections_explicit_start_preserved_through_clamping() -> None:
    # explicit start is never clamped (and out-of-bounds still errors)
    a = AdaptiveConcurrency.model_validate("1-10-15")
    assert (a.min, a.max, a.start) == (1, 15, 10)
    a = AdaptiveConcurrency(min=1, max=15, start=5)
    assert (a.min, a.max, a.start) == (1, 15, 5)
    with pytest.raises(ValueError):
        AdaptiveConcurrency(min=1, max=15, start=30)


def test_adaptive_connections_shorthand_three_values() -> None:
    a = AdaptiveConcurrency.model_validate("4-20-80")
    assert (a.min, a.max, a.start) == (4, 80, 20)


def test_adaptive_connections_shorthand_invalid() -> None:
    with pytest.raises(ValueError):
        AdaptiveConcurrency.model_validate("not-a-number")
    with pytest.raises(ValueError):
        AdaptiveConcurrency.model_validate("1-2-3-4")


def test_adaptive_connections_bounds_validation() -> None:
    # min < 1
    with pytest.raises(ValueError):
        AdaptiveConcurrency(min=0, max=80)
    # max < min
    with pytest.raises(ValueError):
        AdaptiveConcurrency(min=10, max=5)
    # start out of bounds
    with pytest.raises(ValueError):
        AdaptiveConcurrency(min=4, max=80, start=2)
    with pytest.raises(ValueError):
        AdaptiveConcurrency(min=4, max=80, start=100)


def test_generate_config_accepts_bool_for_adaptive_connections() -> None:
    cfg = GenerateConfig(adaptive_connections=True)
    assert cfg.adaptive_connections is True

    cfg = GenerateConfig(adaptive_connections=False)
    assert cfg.adaptive_connections is False


def test_generate_config_accepts_struct_for_adaptive_connections() -> None:
    cfg = GenerateConfig(adaptive_connections=AdaptiveConcurrency(min=4, max=80))
    assert isinstance(cfg.adaptive_connections, AdaptiveConcurrency)
    assert cfg.adaptive_connections.min == 4


def test_generate_config_round_trip_adaptive_connections() -> None:
    cfg = GenerateConfig(
        adaptive_connections=AdaptiveConcurrency(min=4, max=80, start=20)
    )
    data = cfg.model_dump()
    restored = GenerateConfig.model_validate(data)
    assert isinstance(restored.adaptive_connections, AdaptiveConcurrency)
    assert restored.adaptive_connections.min == 4
    assert restored.adaptive_connections.max == 80
    assert restored.adaptive_connections.start == 20


def test_generate_config_round_trip_adaptive_advanced_fields() -> None:
    cfg = GenerateConfig(
        adaptive_connections=AdaptiveConcurrency(
            min=2,
            max=50,
            start=10,
            cooldown_seconds=30.0,
            decrease_factor=0.5,
            scale_up_percent=0.1,
        )
    )
    restored = GenerateConfig.model_validate(cfg.model_dump())
    a = restored.adaptive_connections
    assert isinstance(a, AdaptiveConcurrency)
    assert a.cooldown_seconds == 30.0
    assert a.decrease_factor == 0.5
    assert a.scale_up_percent == 0.1


def test_generate_config_old_log_no_adaptive_connections_field() -> None:
    # simulate old log: dict without the new field
    cfg = GenerateConfig.model_validate({"max_connections": 20})
    assert cfg.adaptive_connections is None
    assert cfg.max_connections == 20


def test_generate_config_merge_picks_up_adaptive_connections() -> None:
    base = GenerateConfig(max_connections=10)
    override = GenerateConfig(adaptive_connections=AdaptiveConcurrency(min=4, max=80))
    merged = base.merge(override)
    assert isinstance(merged.adaptive_connections, AdaptiveConcurrency)
    assert merged.max_connections == 10  # untouched
