import contextlib
from collections.abc import Iterator
from contextvars import ContextVar
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, cast

from pydantic import BaseModel, Field

from inspect_ai._util.config import read_config_object
from inspect_ai._util.registry import registry_create, registry_lookup
from inspect_ai.util._resource import resource

from ._types import InputHandler, InputNotifier


@dataclass
class InputConfig:
    """Resolved input subsystem configuration for an eval run.

    Carries the handler that collects answers, the notifiers that alert the
    user (and any other listeners) when a question is posted, and the
    timeouts that bound each. Construct directly with already-resolved
    callables, or build from an `InputConfigSpec` via `resolve_input_config`.
    """

    input_handler: InputHandler | None = None
    """Handler that collects an answer; `None` falls back to the built-in handler."""

    input_handler_timeout: float = 600.0
    """Seconds to wait for the custom handler before falling back to the built-in handler."""

    input_notifiers: list[InputNotifier] = field(default_factory=list)
    """Fire-and-forget notifiers run in parallel with the handler."""

    notifier_timeout: float = 30.0
    """Per-notifier timeout in seconds; notifiers exceeding it are cancelled silently."""


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


def have_input_config() -> bool:
    return _active_input_config.get(None) is not None


_active_input_config: ContextVar[InputConfig | None] = ContextVar(
    "input_config", default=None
)


# --- Declarative spec types (YAML/JSON-parseable) -----------------------------


class InputHandlerSpec(BaseModel):
    """Declarative spec for a registered input handler."""

    name: str
    """Registered handler name."""

    args: dict[str, Any] = Field(default_factory=dict)
    """Keyword arguments forwarded to the handler factory."""


class InputNotifierSpec(BaseModel):
    """Declarative spec for a registered input notifier."""

    name: str
    """Registered notifier name."""

    args: dict[str, Any] = Field(default_factory=dict)
    """Keyword arguments forwarded to the notifier factory."""


class InputConfigSpec(BaseModel):
    """Declarative input config (YAML/JSON-parseable, registry-name based).

    Resolved into an `InputConfig` via `resolve_input_config` (which
    instantiates each named handler/notifier from the registry) and logged
    back on `EvalConfig.ask_user` for retries.
    """

    input_handler: InputHandlerSpec | None = None
    """Handler to install for the run."""

    input_handler_timeout: float | None = None
    """Override for `InputConfig.input_handler_timeout`."""

    input_notifiers: list[InputNotifierSpec] | None = None
    """Notifiers to install for the run."""

    notifier_timeout: float | None = None
    """Override for `InputConfig.notifier_timeout`."""


def resolve_input_config(
    config: "str | InputConfigSpec | InputConfig | None",
) -> InputConfig | None:
    """Normalize a user-supplied input config into a runtime `InputConfig`.

    Accepts:
      - `None`: returns `None` (no config installed; defaults apply).
      - `InputConfig`: returned as-is (callables already resolved).
      - `InputConfigSpec`: each registered name is instantiated via its factory.
      - `str`: treated as a file path if it exists, otherwise as a registered
        handler name (single-handler shorthand). Mirrors how
        `approval_policies_from_config` (`approval/_policy.py:146-169`)
        normalizes the approval kwarg.
    """
    if config is None:
        return None
    if isinstance(config, InputConfig):
        return config

    if isinstance(config, str):
        if Path(config).exists():
            content = resource(config, type="file")
            spec = InputConfigSpec.model_validate(read_config_object(content))
        elif registry_lookup("input_handler", config):
            spec = InputConfigSpec(input_handler=InputHandlerSpec(name=config))
        else:
            raise ValueError(
                f"Invalid ask_user: {config!r} is not a registered input "
                "handler nor a path to an input config file."
            )
    else:
        spec = config

    resolved = InputConfig()
    if spec.input_handler is not None:
        resolved.input_handler = _instantiate(
            "input_handler", spec.input_handler.name, spec.input_handler.args
        )
    if spec.input_handler_timeout is not None:
        resolved.input_handler_timeout = spec.input_handler_timeout
    if spec.input_notifiers:
        resolved.input_notifiers = [
            _instantiate("input_notifier", n.name, n.args) for n in spec.input_notifiers
        ]
    if spec.notifier_timeout is not None:
        resolved.notifier_timeout = spec.notifier_timeout
    return resolved


def _instantiate(registry_type: str, name: str, args: dict[str, Any]) -> Any:
    # Snake-cased registry types (input_handler, input_notifier, score_reducer)
    # return the raw factory wrapper from `registry_create` rather than
    # auto-invoking it (see `scorer/_reducer/registry.py:154-156` for the same
    # idiom). Call it explicitly with the spec's args to get the handler /
    # notifier callable.
    factory = cast(Callable[..., Any], registry_create(cast(Any, registry_type), name))
    return factory(**args)


def config_from_input_config(config: InputConfig | None) -> InputConfigSpec | None:
    """Reverse-engineer an `InputConfigSpec` from a resolved `InputConfig`.

    Used to log the input config on `EvalConfig.ask_user` so that
    retries round-trip cleanly. Mirrors `config_from_approval_policies`
    (`approval/_policy.py:175-191`); both rely on `registry_log_name` /
    `registry_params` to recover the (name, args) shape from a tagged
    callable. Callables that were not registered via `@input_handler` /
    `@input_notifier` are skipped (silently — they have no spec form to
    serialize), so an in-process test or ad-hoc REPL handler does not
    break log writing.

    Returns `None` when the input has no settings worth logging (no handler,
    no notifiers, default timeouts).
    """
    from inspect_ai._util.registry import (
        is_registry_object,
        registry_log_name,
        registry_params,
    )

    if config is None:
        return None

    handler_spec: InputHandlerSpec | None = None
    if config.input_handler is not None and is_registry_object(config.input_handler):
        handler_spec = InputHandlerSpec(
            name=registry_log_name(config.input_handler),
            args=registry_params(config.input_handler),
        )

    notifier_specs: list[InputNotifierSpec] | None = None
    if config.input_notifiers:
        tagged = [n for n in config.input_notifiers if is_registry_object(n)]
        if tagged:
            notifier_specs = [
                InputNotifierSpec(
                    name=registry_log_name(n),
                    args=registry_params(n),
                )
                for n in tagged
            ]

    default = InputConfig()
    handler_timeout = (
        config.input_handler_timeout
        if config.input_handler_timeout != default.input_handler_timeout
        else None
    )
    notifier_timeout = (
        config.notifier_timeout
        if config.notifier_timeout != default.notifier_timeout
        else None
    )

    if (
        handler_spec is None
        and notifier_specs is None
        and handler_timeout is None
        and notifier_timeout is None
    ):
        return None

    return InputConfigSpec(
        input_handler=handler_spec,
        input_handler_timeout=handler_timeout,
        input_notifiers=notifier_specs,
        notifier_timeout=notifier_timeout,
    )
