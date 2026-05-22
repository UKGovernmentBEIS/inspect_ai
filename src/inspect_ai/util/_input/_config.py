import contextlib
from collections.abc import Iterator
from contextvars import ContextVar
from dataclasses import dataclass, field

from ._types import InputHandler, InputNotifier


@dataclass
class InputConfig:
    input_handler: InputHandler | None = None
    input_handler_timeout: float = 600.0
    input_notifiers: list[InputNotifier] = field(default_factory=list)
    notifier_timeout: float = 30.0


def active_input_config() -> InputConfig:
    cfg = _active_input_config.get(None)
    return cfg if cfg is not None else InputConfig()


@contextlib.contextmanager
def input_config(config: InputConfig) -> Iterator[None]:
    """Scoped override of the active input configuration."""
    token = _active_input_config.set(config)
    try:
        yield
    finally:
        _active_input_config.reset(token)


def init_input_config(config: InputConfig | None) -> None:
    _active_input_config.set(config)


_active_input_config: ContextVar[InputConfig | None] = ContextVar(
    "input_config", default=None
)
