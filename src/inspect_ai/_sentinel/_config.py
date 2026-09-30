import importlib
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, TypeAlias, Union, cast

from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.registry import is_registry_object

if TYPE_CHECKING:
    from inspect_sentinel import Protocol
    from inspect_sentinel._integration import SentinelConfig, Sentinels

SentinelRoot: TypeAlias = "Protocol"

SentinelSpec: TypeAlias = Union[
    str,
    "Sentinels",
    "SentinelConfig",
    Sequence[Mapping[str, Any]],
    Mapping[str, Mapping[str, Any]],
]


def _require_sentinel() -> None:
    try:
        importlib.import_module("inspect_sentinel._integration")
    except ImportError as ex:
        raise PrerequisiteError(
            "[bold]ERROR[/bold]: Sentinel support requires the inspect_sentinel package. "
            "Install with:\n\n[bold]pip install inspect_sentinel[/bold]"
        ) from ex


def resolve_sentinel_spec(spec: SentinelSpec) -> "Sentinels":
    _require_sentinel()
    from inspect_sentinel._integration import SentinelConfig, sentinel_from_config

    if isinstance(spec, str | SentinelConfig) or not _is_constructed(spec):
        return sentinel_from_config(cast("str | SentinelConfig", spec))
    return cast("Sentinels", spec)


def _is_constructed(spec: object) -> bool:
    if is_registry_object(spec):
        return True
    if isinstance(spec, Mapping):
        values = list(cast(Mapping[str, object], spec).values())
    elif isinstance(spec, Sequence) and not isinstance(spec, str):
        values = list(cast(Sequence[object], spec))
    else:
        raise TypeError(
            f"sentinel must be a monitor, a protocol, a list or mapping of them, or a configuration, not {type(spec).__name__}."
        )
    constructed = [is_registry_object(value) for value in values]
    if any(constructed) and not all(constructed):
        raise TypeError(
            "sentinel mixes constructed monitors or protocols with configuration entries."
        )
    return bool(values) and all(constructed)


def resolve_sentinel_root(sentinels: "Sentinels") -> SentinelRoot:
    _require_sentinel()
    from inspect_sentinel._integration import resolve_sentinel

    return resolve_sentinel(sentinels)


def sentinel_config_data(sentinels: "Sentinels") -> list[Any] | dict[str, Any]:
    _require_sentinel()
    from inspect_sentinel._integration import config_from_sentinel

    data: list[Any] | dict[str, Any] = config_from_sentinel(sentinels).model_dump()
    return data
