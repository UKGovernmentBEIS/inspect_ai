import inspect
import json
from collections.abc import Hashable, Mapping, Sequence
from logging import getLogger
from typing import Any, NamedTuple, cast

import yaml

from inspect_ai._util.file import exists, local_path
from inspect_ai._util.logger import warn_once
from inspect_ai._util.registry import (
    RegistryDict,
    RegistryInfo,
    RegistryType,
    create_registry_object,
    has_registry_params,
    is_registry_dict,
    is_registry_object,
    registry_find,
    registry_info,
    registry_lookup,
    registry_unqualified_name,
    registry_value,
)
from inspect_ai.util._resource import resource

from ._config import SentinelConfig, SentinelEntry

logger = getLogger(__name__)

_KINDS: tuple[RegistryType, ...] = ("monitor", "protocol")

_ENTRY_FIELDS = tuple(SentinelEntry.model_fields)

# the registry metadata key where @monitor and @protocol record a factory's version
_VERSION = "version"


class _Factory(NamedTuple):
    kind: RegistryType
    name: str
    factory: object


def sentinel_from_config(
    config: str | SentinelConfig | Sequence[Mapping[str, Any]] | Mapping[str, Any],
) -> object:
    """Build the monitors and protocols a configuration describes.

    Each entry is constructed through the registry with its `params` and its nested entries, which are built first. An entry whose recorded `version` differs from the installed factory's is built anyway, with a warning naming both versions; its `meta` is ignored. One entry, or a bare registered name, builds one instance, which resolves as the root itself; a list or mapping builds a list or mapping.

    A name without a package prefix finds a monitor or protocol registered under it, or else the one registered under it in any package, loading every package's entry points if none is registered yet.

    Args:
        config: A YAML or JSON file whose only key is `sentinel`, a registered monitor or protocol name, or the configuration itself: one entry, a list of entries, or a mapping of instance names to entries.

    Raises:
        ValueError: If the configuration is invalid; the message names the entry, as in `sentinel.attempt.children[1]`.
        TypeError: If a factory rejects its arguments, with the entry named the same way.
    """
    if isinstance(config, str):
        return _from_string(config)
    if isinstance(config, SentinelConfig):
        return _build_layer(config.model_dump(), "sentinel")
    return _build_layer(config, "sentinel")


def validate_instance_name(name: object) -> str:
    """Return `name` if it is a string that can be a `SentinelEvent.path` segment.

    Raises:
        ValueError: If `name` is not a non-empty string without `/`.
    """
    if not isinstance(name, str) or name == "" or "/" in name:
        raise ValueError(
            f"Instance name {name!r} must be a non-empty string without '/'."
        )
    return name


def _from_string(config: str) -> object:
    path = local_path(config)
    if exists(path):
        return _build_layer(_read_file(path), "sentinel")
    if _find_all(config):
        return _build_entry({"name": config}, "sentinel")
    raise ValueError(
        f"{config!r} is neither a config file nor a registered monitor or protocol."
    )


def _read_file(path: str) -> object:
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
    return cast(dict[str, Any], content)["sentinel"]


class _Pairs(list[tuple[object, object]]):
    pass


class _PairsLoader(yaml.SafeLoader):
    pass


def _construct_pairs(loader: yaml.SafeLoader, node: yaml.MappingNode) -> _Pairs:
    loader.flatten_mapping(node)
    return _Pairs(
        (
            loader.construct_object(key, deep=True),
            loader.construct_object(value, deep=True),
        )
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


def _build_layer(layer: object, path: str) -> object:
    if isinstance(layer, Mapping):
        entries = cast(Mapping[object, object], layer)
        if isinstance(entries.get("name"), str):
            return _build_entry(entries, path)
        built: dict[str, object] = {}
        for key, entry in entries.items():
            try:
                name = validate_instance_name(key)
            except ValueError as ex:
                raise ValueError(f"{path}: {ex}") from ex
            built[name] = _build_entry(entry, f"{path}.{name}")
        return built
    if isinstance(layer, Sequence) and not isinstance(layer, str):
        items = cast(Sequence[object], layer)
        return [_build_entry(entry, f"{path}[{i}]") for i, entry in enumerate(items)]
    raise ValueError(
        f"{path} must be a list or a mapping of entries, not {type(layer).__name__}."
    )


def _build_entry(entry: object, path: str) -> object:
    if not isinstance(entry, Mapping):
        raise ValueError(f"{path} must be a mapping with a 'name', not {entry!r}.")
    fields = cast(Mapping[str, object], entry)
    name = fields.get("name")
    if not isinstance(name, str):
        raise ValueError(
            f"{path}: an entry needs a 'name' naming a monitor or protocol."
        )
    params = fields.get("params", {})
    if not isinstance(params, Mapping):
        raise ValueError(f"{path}.params must be a mapping of arguments.")
    args = dict(cast(Mapping[str, object], params))
    found = _find(name, path)
    _check_version(found, fields.get(_VERSION), path)
    signature = inspect.signature(cast(Any, found.factory)).parameters
    accepted = [key for key, p in signature.items() if p.kind is not p.VAR_KEYWORD]
    any_key = len(accepted) < len(signature)
    for key, value in fields.items():
        if key in _ENTRY_FIELDS:
            continue
        if key not in accepted and not any_key:
            raise ValueError(
                f"{path}: {key!r} is not a parameter of {name}; an entry takes 'name', 'params', and nested entries under one of {name}'s parameters {accepted}."
            )
        if key in args:
            raise ValueError(f"{path}: {key!r} is given both nested and in params.")
        args[key] = _build_layer(value, f"{path}.{key}")
    try:
        return create_registry_object(found.kind, found.name, args)
    except (TypeError, ValueError) as ex:
        # a TypeError keeps its class, such as inspect_sentinel's PortabilityError
        error = type(ex) if isinstance(ex, TypeError) else ValueError
        raise error(f"{path}: {ex}") from ex


def _check_version(found: _Factory, recorded: object, path: str) -> None:
    if recorded is None:
        return
    if not isinstance(recorded, int) or isinstance(recorded, bool):
        raise ValueError(f"{path}.version must be an integer, not {recorded!r}.")
    installed = _version(registry_info(found.factory))
    if recorded != installed:
        warn_once(
            logger,
            f"{found.name} was recorded at version {recorded} but version {installed} is installed; building it anyway.",
        )


def _version(info: RegistryInfo) -> int:
    return cast(int, info.metadata.get(_VERSION, 0))


def _find(name: str, path: str) -> _Factory:
    found = _find_all(name)
    if not found:
        raise ValueError(f"{path}: {name!r} is not a registered monitor or protocol.")
    if len(found) > 1:
        candidates = ", ".join(f"{f.kind} {f.name}" for f in found)
        raise ValueError(f"{path}: {name!r} is ambiguous; it names {candidates}.")
    return found[0]


def _find_all(name: str) -> list[_Factory]:
    exact = [
        _factory(factory)
        for factory in (registry_lookup(kind, name) for kind in _KINDS)
        if factory is not None
    ]
    if exact or "/" in name:
        return exact
    return [
        _factory(factory)
        for factory in registry_find(
            lambda info: info.type in _KINDS and registry_unqualified_name(info) == name
        )
    ]


def _factory(factory: object) -> _Factory:
    info = registry_info(factory)
    return _Factory(info.type, info.name, factory)


def config_from_sentinel(sentinels: object) -> SentinelConfig:
    """Record constructed monitors and protocols as the configuration that rebuilds them.

    The inverse of `sentinel_from_config`, for the eval log and retry: each instance becomes an entry with its registry name, the params it was created with, and its factory's version unless that is 0, and a param holding monitors or protocols becomes nested entries. A monitor or protocol from a package is recorded by its name without the package prefix when that finds it and nothing else. A lone instance is recorded as a lone entry, so it rebuilds as the root it was.

    Args:
        sentinels: One monitor or protocol, or a sequence or mapping of instance names to them, as `Task(sentinel=)` accepts.

    Raises:
        TypeError: If a value is not a configured monitor or protocol.
    """
    if is_registry_object(sentinels):
        return SentinelConfig(_instance_entry(sentinels))
    if isinstance(sentinels, Mapping):
        mapping = cast(Mapping[str, object], sentinels)
        return SentinelConfig(
            {name: _instance_entry(child) for name, child in mapping.items()}
        )
    items = cast(Sequence[object], sentinels)
    return SentinelConfig([_instance_entry(child) for child in items])


def _instance_entry(instance: object) -> SentinelEntry:
    return _config_entry(_registry_dict(instance), _version(registry_info(instance)))


def _registry_dict(instance: object) -> RegistryDict:
    if not has_registry_params(instance) or registry_info(instance).type not in _KINDS:
        raise TypeError(
            f"{getattr(instance, '__name__', instance)!r} is not a configured monitor or protocol."
        )
    return cast(RegistryDict, registry_value(instance))


def _config_layer(
    layer: Sequence[RegistryDict] | Mapping[str, RegistryDict],
) -> SentinelConfig:
    if isinstance(layer, Mapping):
        return SentinelConfig({name: _nested_entry(d) for name, d in layer.items()})
    return SentinelConfig([_nested_entry(d) for d in layer])


def _nested_entry(recorded: RegistryDict) -> SentinelEntry:
    # registry params hold nested instances as dicts, so the version comes from
    # the factory they name
    factory = registry_lookup(recorded["type"], recorded["name"])
    version = 0 if factory is None else _version(registry_info(factory))
    return _config_entry(recorded, version)


def _config_entry(recorded: RegistryDict, version: int) -> SentinelEntry:
    params: dict[str, Any] = {}
    nested: dict[str, SentinelConfig] = {}
    for key, value in recorded["params"].items():
        layer = None if key in _ENTRY_FIELDS else _sentinel_layer(value)
        if layer is None:
            params[key] = value
        else:
            nested[key] = _config_layer(layer)
    fields: dict[str, Any] = {"name": _config_name(recorded["name"]), "params": params}
    if version != 0:
        fields[_VERSION] = version
    return SentinelEntry.model_validate({**fields, **nested})


def _sentinel_layer(
    value: object,
) -> Sequence[RegistryDict] | Mapping[str, RegistryDict] | None:
    if isinstance(value, list) and value:
        items = cast(list[object], value)
        if all(_is_sentinel_dict(item) for item in items):
            return cast(list[RegistryDict], items)
    elif isinstance(value, dict) and value:
        entries = cast(dict[str, object], value)
        if not is_registry_dict(entries) and all(
            _is_sentinel_dict(item) for item in entries.values()
        ):
            return cast(dict[str, RegistryDict], entries)
    return None


def _is_sentinel_dict(value: object) -> bool:
    return is_registry_dict(value) and value["type"] in _KINDS


def _config_name(name: str) -> str:
    bare = registry_unqualified_name(name)
    if bare == name:
        return name
    found = _find_all(bare)
    return bare if len(found) == 1 and found[0].name == name else name
