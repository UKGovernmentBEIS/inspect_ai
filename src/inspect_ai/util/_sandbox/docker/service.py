import re
from dataclasses import dataclass

from typing_extensions import TypedDict


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
    start_period + (retries * (interval + timeout))

    Failing probes don't count against `retries` until the start period has
    elapsed, so the retry budget is additional to (not inclusive of) it.

    Default values (from Docker documentation):
    - start_period: 0s
    - retries: 3
    - interval: 30s
    - timeout: 30s
    """
    healthcheck = service.get("healthcheck", None)
    if healthcheck is None:
        return 0

    # Parse duration strings with defaults
    start_period = parse_duration(healthcheck.get("start_period", "0s"))
    retries = healthcheck.get("retries", 3)
    interval = parse_duration(healthcheck.get("interval", "30s"))
    timeout = parse_duration(healthcheck.get("timeout", "30s"))

    # Calculate total time in seconds
    total_time = start_period.seconds + retries * (interval.seconds + timeout.seconds)

    return int(total_time)


@dataclass
class Duration:
    nanoseconds: int

    @property
    def seconds(self) -> float:
        return self.nanoseconds / 1_000_000_000


DURATION_UNITS = {
    "ns": 1,
    "us": 1_000,
    "µs": 1_000,  # U+00B5 micro sign
    "μs": 1_000,  # U+03BC Greek letter mu (both accepted by Go's ParseDuration)
    "ms": 1_000_000,
    "s": 1_000_000_000,
    "m": 60_000_000_000,
    "h": 3_600_000_000_000,
}

# longest first so that "ms" isn't matched as "m"
DURATION_UNIT = "|".join(sorted(DURATION_UNITS, key=len, reverse=True))

# a number (Go's ParseDuration permits a decimal point) followed by a unit
DURATION_COMPONENT = rf"(\d+(?:\.\d+)?|\.\d+)({DURATION_UNIT})"
DURATION = re.compile(f"(?:{DURATION_COMPONENT})+")


def parse_duration(duration_str: str) -> Duration:
    """Parse a Docker compose style duration string (e.g. "1h30m", "1.5s")."""
    if not duration_str:
        return Duration(0)

    # fullmatch first, so that unparseable text is an error rather than
    # being silently skipped over
    stripped = "".join(duration_str.split())
    if not DURATION.fullmatch(stripped):
        raise ValueError(f"Invalid duration format: {duration_str}")

    total_nanoseconds = sum(
        float(number) * DURATION_UNITS[unit]
        for number, unit in re.findall(DURATION_COMPONENT, stripped)
    )
    return Duration(round(total_nanoseconds))
