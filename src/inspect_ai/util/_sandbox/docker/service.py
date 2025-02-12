import re
from dataclasses import dataclass
from typing import TypedDict


class ComposeServiceHealthcheck(TypedDict, total=False):
    start_period: str
    interval: str
    retries: int
    timeout: str


ComposeService = TypedDict(
    "ComposeService",
    {
        "image": str,
        "build": str,
        "container_name": str,
        "x-default": bool,
        "x-local": bool,
        "healthcheck": ComposeServiceHealthcheck,
    },
    total=False,
)


def services_healthcheck_time(services: dict[str, ComposeService]) -> int:
    max_time = 0

    for _, service in services.items():
        service_time = service_healthcheck_time(service)
        max_time = max(max_time, service_time)

    return max_time


def service_healthcheck_time(service: ComposeService) -> int:
    """
    Calculate the maximum time a single service's healthcheck could take.

    The total time is:
    start_period + (retries * (timeout))

    Default values (from Docker documentation):
    - timeout: 30s
    - retries: 3
    - start_period: 0s
    """
    healthcheck = service.get("healthcheck", None)
    if healthcheck is None:
        return 0

    # Parse duration strings with defaults
    start_period = parse_duration(healthcheck.get("start_period", "0s"))
    timeout = parse_duration(healthcheck.get("timeout", "30s"))
    retries = healthcheck.get("retries", 3)

    # Compute and return total time
    total_time = start_period.seconds + (retries * (timeout.seconds))
    return int(total_time)


@dataclass
class Duration:
    nanoseconds: int

    @property
    def seconds(self) -> float:
        return self.nanoseconds / 1_000_000_000


def parse_duration(duration_str: str) -> Duration:
    """Parse a Docker compose style duration string."""
    if not duration_str:
        return Duration(0)

    units = {
        "ns": 1,
        "us": 1_000,
        "ms": 1_000_000,
        "s": 1_000_000_000,
        "m": 60_000_000_000,
        "h": 3_600_000_000_000,
    }

    duration_str = "".join(duration_str.split())
    pattern = re.compile(r"(\d+)([a-z]+)")
    matches = pattern.findall(duration_str)

    if not matches:
        raise ValueError(f"Invalid duration format: {duration_str}")

    total_nanoseconds = 0
    for number, unit in matches:
        if unit not in units:
            raise ValueError(f"Invalid unit: {unit}")
        total_nanoseconds += int(number) * units[unit]

    return Duration(total_nanoseconds)
