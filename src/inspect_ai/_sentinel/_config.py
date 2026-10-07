import importlib
import json
from collections.abc import Callable, Hashable, Mapping, Sequence
from typing import TYPE_CHECKING, Any, TypeAlias, Union, cast

import yaml

from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.file import exists, local_path
from inspect_ai._util.registry import is_registry_object
from inspect_ai.util._resource import resource

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
            "[bold]ERROR[/bold]: Sentinel support requires the inspect_sentinel package, "
            "which is not released yet. Install it from GitHub with:\n\n"
            "[bold]pip install git+https://github.com/meridianlabs-ai/inspect_sentinel[/bold]"
        ) from ex


def resolve_sentinel_spec(spec: SentinelSpec) -> "Sentinels":
    _require_sentinel()
    from inspect_sentinel._integration import sentinel_from_config

    if isinstance(spec, str) and exists(path := local_path(spec)):
        sentinels = sentinel_from_config(_read_config_file(path))
    elif isinstance(spec, str | SentinelConfig) or not _is_constructed(spec):
        sentinels = sentinel_from_config(cast(str | SentinelConfig, spec))
    else:
        sentinels = cast("Sentinels", spec)
    resolve_sentinel_root(sentinels)
    return sentinels


def _read_config_file(path: str) -> Any:
    """The value of the `sentinel` key in a YAML or JSON configuration file."""
    text = resource(path, type="file")
    try:
        content = _unique_keys(_parse(text), path, "")
    except (json.JSONDecodeError, yaml.YAMLError) as ex:
        raise ValueError(f"{path}: could not parse the file: {ex}") from ex
    if not isinstance(content, dict) or set(cast(dict[str, Any], content)) != {
        "sentinel"
    }:
        raise ValueError(
            f"{path}: a sentinel config file is a mapping whose only key is 'sentinel'."
        )
    value = cast(dict[str, Any], content)["sentinel"]
    if isinstance(value, str):
        raise ValueError(
            f"{path}: 'sentinel' must be an entry, a list of entries, or a mapping of entries, not a string."
        )
    return value


class _Pairs(list[tuple[object, object]]):
    pass


class _PairsLoader(yaml.SafeLoader):
    pass


def _construct_pairs(loader: yaml.SafeLoader, node: yaml.MappingNode) -> _Pairs:
    loader.flatten_mapping(node)
    construct: Callable[..., object] = cast(Any, loader).construct_object
    return _Pairs(
        (construct(key, deep=True), construct(value, deep=True))
        for key, value in node.value
    )


_PairsLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_pairs
)


def _parse(text: str) -> object:
    # PyYAML rejects tab indentation, which JSON allows
    try:
        return json.loads(text, object_pairs_hook=_Pairs)
    except json.JSONDecodeError:
        return yaml.load(text, Loader=_PairsLoader)


def _unique_keys(value: object, file: str, path: str) -> object:
    if isinstance(value, _Pairs):
        mapping: dict[object, object] = {}
        for key, item in value:
            where = path or "the top level"
            if not isinstance(key, Hashable):
                raise ValueError(f"{file}: {where}: a key must be a scalar.")
            if key in mapping:
                raise ValueError(f"{file}: {where}: duplicate key {key!r}.")
            mapping[key] = _unique_keys(
                item, file, f"{path}.{key}" if path else str(key)
            )
        return mapping
    if isinstance(value, list):
        items = cast(list[object], value)
        return [
            _unique_keys(item, file, f"{path}[{i}]") for i, item in enumerate(items)
        ]
    return value


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
