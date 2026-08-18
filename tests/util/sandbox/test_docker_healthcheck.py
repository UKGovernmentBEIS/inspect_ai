import pytest

from inspect_ai.util._sandbox.docker.service import (
    ComposeService,
    parse_duration,
    service_healthcheck_time,
    services_healthcheck_time,
)


# Duration Parser Tests
def test_parse_duration_simple():
    assert parse_duration("30s").seconds == 30.0
    assert parse_duration("1m").seconds == 60.0
    assert parse_duration("1h").seconds == 3600.0


def test_parse_duration_combined():
    assert parse_duration("1m30s").seconds == 90.0
    assert parse_duration("1h30m").seconds == 5400.0
    assert parse_duration("2h30m15s").seconds == 9015.0


def test_parse_duration_with_spaces():
    assert parse_duration("1h 30m").seconds == 5400.0
    assert parse_duration("1h 30m 15s").seconds == 5415.0


def test_parse_duration_milliseconds():
    assert parse_duration("100ms").seconds == 0.1
    assert parse_duration("1s500ms").seconds == 1.5


def test_parse_duration_microseconds():
    assert parse_duration("500us").seconds == 0.0005
    assert parse_duration("500µs").seconds == 0.0005


def test_parse_duration_fractional():
    assert parse_duration("5.0s").seconds == 5.0
    assert parse_duration("1.5s").seconds == 1.5
    assert parse_duration(".5s").seconds == 0.5
    assert parse_duration("1.5m30.5s").seconds == 120.5


def test_parse_duration_empty():
    assert parse_duration("").seconds == 0.0


def test_parse_duration_invalid():
    with pytest.raises(ValueError):
        parse_duration("invalid")
    with pytest.raises(ValueError):
        parse_duration("30x")  # invalid unit
    with pytest.raises(ValueError):
        parse_duration("30")  # missing unit
    with pytest.raises(ValueError):
        parse_duration("30s bogus")  # trailing garbage
    with pytest.raises(ValueError):
        parse_duration("1.2.3s")  # malformed number (previously parsed as 3s)
    with pytest.raises(ValueError):
        parse_duration("-5s")  # negative (previously parsed as +5s)
    with pytest.raises(ValueError):
        parse_duration("30s@bogus")  # trailing garbage (previously parsed as 30s)
    with pytest.raises(ValueError):
        parse_duration("   ")  # whitespace only


# Service Healthcheck Time Tests
def test_service_without_healthcheck() -> None:
    service: ComposeService = {
        "image": "nginx",
    }
    assert service_healthcheck_time(service) == 0.0


def test_service_with_default_values() -> None:
    service: ComposeService = {
        "image": "nginx",
        "healthcheck": {},
    }
    assert service_healthcheck_time(service) == 180.0


def test_service_with_custom_values() -> None:
    service: ComposeService = {
        "image": "nginx",
        "healthcheck": {
            "start_period": "10s",
            "interval": "5s",
            "timeout": "3s",
            "retries": 5,
        },
    }
    # 10s start period + 3s for a probe crossing its boundary + 5 * (5s + 3s)
    assert service_healthcheck_time(service) == 53.0


def test_service_with_long_start_period() -> None:
    # the grace period dominates the retry budget: a service that becomes
    # healthy at t=200s must not be timed out (see #4698)
    service: ComposeService = {
        "image": "nginx",
        "healthcheck": {
            "start_period": "300s",
            "interval": "5s",
            "timeout": "30s",
            "retries": 3,
        },
    }
    # worst case, the last uncounted probe starts at t=300 and fails at t=330,
    # after which the three counted probes run to t=435
    assert service_healthcheck_time(service) == 435.0


def test_service_with_fractional_durations() -> None:
    # the budget must never round below the schedule it comes from: the single
    # probe here may not finish until t=1.2s
    service: ComposeService = {
        "image": "nginx",
        "healthcheck": {
            "interval": "0.6s",
            "timeout": "600ms",
            "retries": 1,
        },
    }
    assert service_healthcheck_time(service) == 2.0


def test_service_with_partial_custom_values() -> None:
    service: ComposeService = {
        "image": "nginx",
        "healthcheck": {
            "start_period": "10s",
            "timeout": "3s",
        },
    }
    assert service_healthcheck_time(service) == 112.0


# Total Healthcheck Time Tests
def test_total_time_no_services() -> None:
    services: dict[str, ComposeService] = {}
    assert services_healthcheck_time(services) == 0.0


def test_total_time_no_healthchecks() -> None:
    services: dict[str, ComposeService] = {
        "web": {"image": "nginx"},
        "db": {
            "image": "postgres",
        },
    }
    assert services_healthcheck_time(services) == 0.0


def test_total_time_multiple_services() -> None:
    services: dict[str, ComposeService] = {
        "web": {
            "image": "nginx",
            "healthcheck": {
                "start_period": "10s",
                "interval": "5s",
                "timeout": "3s",
                "retries": 5,
            },
        },
        "db": {
            "image": "postgres",
            "healthcheck": {
                "start_period": "30s",
                "interval": "10s",
                "timeout": "5s",
                "retries": 3,
            },
        },
    }
    assert services_healthcheck_time(services) == 80.0


def test_total_time_mixed_services() -> None:
    services: dict[str, ComposeService] = {
        "web": {
            "image": "nginx",
            "healthcheck": {
                "start_period": "10s",
                "interval": "5s",
                "timeout": "3s",
                "retries": 5,
            },
        },
        "db": {
            "image": "postgres",
        },
    }
    assert services_healthcheck_time(services) == 53.0
