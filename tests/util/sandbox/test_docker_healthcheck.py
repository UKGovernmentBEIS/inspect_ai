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


def test_parse_duration_empty():
    assert parse_duration("").seconds == 0.0


def test_parse_duration_invalid():
    with pytest.raises(ValueError):
        parse_duration("invalid")
    with pytest.raises(ValueError):
        parse_duration("30x")  # invalid unit


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
    # Default values: interval=30s, timeout=30s, retries=3, start_period=0s
    # Total = 0 + (3 * (30 + 30)) = 180 seconds
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
    # start_period=10s, interval=5s, timeout=3s, retries=5
    # Total = 10 + (5 * (3 + 5)) = 50 seconds
    assert service_healthcheck_time(service) == 50.0


def test_service_with_partial_custom_values() -> None:
    service: ComposeService = {
        "image": "nginx",
        "healthcheck": {
            "start_period": "10s",
            "timeout": "3s",
        },
    }
    # start_period=10s, interval=30s (default), timeout=3s, retries=3 (default)
    # Total = 10 + (3 * (3 + 30)) = 109 seconds
    assert service_healthcheck_time(service) == 109.0


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
    # web: 10 + (5 * (3 + 5)) = 50 seconds
    # db: 30 + (3 * (5 + 10)) = 75 seconds
    # max should be 75 seconds
    assert services_healthcheck_time(services) == 75.0


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
    # web: 10 + (5 * (3 + 5)) = 50 seconds
    # db: 0 seconds (no healthcheck)
    # max should be 50 seconds
    assert services_healthcheck_time(services) == 50.0
