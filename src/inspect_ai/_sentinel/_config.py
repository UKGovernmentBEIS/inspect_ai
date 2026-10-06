import importlib
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Any, TypeAlias, Union, cast

from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.registry import is_registry_object

# isort: split
# Backward-compatible re-exports of names that moved to inspect_ai.core.
from inspect_ai.core._sentinel import SentinelConfig as SentinelConfig
from inspect_ai.core._sentinel import SentinelEntry as SentinelEntry
from inspect_ai.core._sentinel import SentinelLayer as SentinelLayer
from inspect_ai.core._sentinel import _layer_kind as _layer_kind

# End of backward-compatible re-exports.

if TYPE_CHECKING:
    from inspect_sentinel import Protocol
    from inspect_sentinel._integration import Sentinels


SentinelRoot: TypeAlias = "Protocol"

SentinelSpec: TypeAlias = Union[
    str,
    "Sentinels",
    SentinelConfig,
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
    from inspect_sentinel._integration import sentinel_from_config

    if isinstance(spec, str | SentinelConfig) or not _is_constructed(spec):
        sentinels = sentinel_from_config(cast(str | SentinelConfig, spec))
    else:
        sentinels = cast("Sentinels", spec)
    resolve_sentinel_root(sentinels)
    return sentinels


def _is_constructed(spec: object) -> bool:
    if is_registry_object(spec):
        return True
    if isinstance(spec, Mapping):
        values = list(cast(Mapping[str, object], spec).values())
    elif isinstance(spec, Sequence) and not isinstance(spec, str):
        values = list(cast(Sequence[object], spec))
    else:
        raise TypeError(
            f"sentinel must be a protocol, a list or mapping of monitors and protocols, or a configuration, not {type(spec).__name__}."
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


def sentinel_config(sentinels: "Sentinels") -> SentinelConfig:
    _require_sentinel()
    from inspect_sentinel._integration import config_from_sentinel

    return config_from_sentinel(sentinels)
