import importlib
import typing
from collections.abc import Awaitable, Callable, Mapping, Sequence
from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING, Annotated, Any, TypeAlias, Union, cast

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    JsonValue,
    RootModel,
    StrictInt,
    Tag,
)

from inspect_ai._util.config import parse_cli_args
from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.file import exists, local_path
from inspect_ai._util.registry import is_registry_object
from inspect_ai._util.version import has_required_version

if TYPE_CHECKING:
    import inspect_sentinel._integration
    from inspect_sentinel import Protocol


# The shape of inspect_sentinel's `Sentinels`, so that public signatures type
# check without inspect_sentinel installed. A monitor takes (context, step) and a
# protocol (context, step, escalations), as inspect_sentinel's own types define.
SentinelFunction: TypeAlias = Callable[..., Awaitable[Any]]


class SentinelGroup(typing.Protocol):
    @property
    def functions(self) -> Sequence[SentinelFunction]: ...


Sentinel: TypeAlias = SentinelFunction | SentinelGroup

Sentinels: TypeAlias = Sentinel | Mapping[str, Sentinel] | Sequence[Sentinel]


class SentinelEntry(BaseModel):
    """One configured monitor or protocol.

    Any key besides `name`, `params`, `version` and `meta` names a parameter of the factory whose value is nested monitors or protocols, such as `monitors` for `threshold` or `children` for `concurrent`; it holds an entry, a list of entries, or a mapping of instance names to entries, and `nested` returns them.

    Experimental: not yet a stable API; may change without notice.
    """

    model_config = ConfigDict(extra="allow")

    name: str
    """Registry name of the factory; a bare name also finds one in `inspect_sentinel`."""

    params: dict[str, Any] = Field(default_factory=dict)
    """Arguments passed to the factory, other than the nested ones."""

    version: StrictInt | None = Field(default=None, exclude_if=lambda v: v is None)
    """The factory's version as `@monitor(version=)` or `@protocol(version=)` declared it, recorded when not 0."""

    meta: dict[str, JsonValue] | None = Field(
        default=None, exclude_if=lambda v: v is None
    )
    """Reserved for fields added later; readers keep it without interpreting it."""

    if not TYPE_CHECKING:
        # pydantic validates each extra as a nested layer, so an error carries
        # its location; hidden from the checker, which sees an invalid override
        __pydantic_extra__: dict[str, "SentinelConfig"] = Field(init=False)

    @property
    def nested(self) -> dict[str, "SentinelConfig"]:
        """Nested monitors or protocols, by the factory parameter they are passed as."""
        return cast(dict[str, SentinelConfig], dict(self.__pydantic_extra__ or {}))


def _layer_kind(value: object) -> str | None:
    if isinstance(value, SentinelEntry):
        return "entry"
    if isinstance(value, list):
        return "list"
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, object], value)
        if isinstance(mapping.get("name"), str):
            return "entry"
        if all(isinstance(v, Mapping | SentinelEntry) for v in mapping.values()):
            return "mapping"
    return None


SentinelLayer: TypeAlias = Annotated[
    Annotated[SentinelEntry, Tag("entry")]
    | Annotated[list[SentinelEntry], Field(min_length=1), Tag("list")]
    | Annotated[dict[str, SentinelEntry], Field(min_length=1), Tag("mapping")],
    Discriminator(
        _layer_kind,
        custom_error_type="sentinel_layer",
        custom_error_message="A sentinel layer is an entry with a string 'name', a list of entries, or a mapping of instance names to entries",
    ),
]


class SentinelConfig(RootModel[SentinelLayer]):
    """A sentinel configuration: one entry, a list of entries, or a mapping of instance names to entries.

    The value of the `sentinel:` key in a configuration file, and what the eval log records. A mapping is one entry when its `name` is a string, and a mapping of instance names when every value is an entry, so an instance named `name` still configures a mapping.

    Experimental: not yet a stable API; may change without notice.
    """


SentinelEntry.model_rebuild()

SentinelRoot: TypeAlias = "Protocol"

SentinelSpec: TypeAlias = Union[
    str,
    Sentinels,
    SentinelConfig,
    Sequence[Mapping[str, Any]],
    Mapping[str, Mapping[str, Any]],
]


def sentinel_with_args(
    sentinel: str | None,
    args: tuple[str, ...] | list[str] | None,
    *,
    sentinel_source: str = "--sentinel",
    args_source: str = "--sentinel-arg",
) -> str | SentinelConfig | None:
    """A registered monitor or protocol name with `key=value` arguments, as the entry that builds it.

    The arguments become the entry's `params`, parsed like `-T` and `-S` values. A config file carries its own params, so arguments are rejected with a file, as they are without a sentinel. A path that exists is a file, as `inspect_sentinel` decides.

    Args:
        sentinel: A config file or a registered monitor or protocol name.
        args: `key=value` arguments for the named monitor or protocol.
        sentinel_source: The option or variable that gave `sentinel`, for errors.
        args_source: The option or variable that gave `args`, for errors.
    """
    if not args:
        return sentinel
    if sentinel is None:
        raise PrerequisiteError(f"{args_source} requires {sentinel_source}.")
    malformed = [arg for arg in args if "=" not in arg]
    if malformed:
        raise PrerequisiteError(f"{args_source} takes key=value, not {malformed[0]!r}.")
    if exists(local_path(sentinel)):
        raise PrerequisiteError(
            f"{args_source} cannot be used with the sentinel config file '{sentinel}'; "
            "set params in the file instead."
        )
    params: dict[str, Any] = {}
    for arg in args:
        try:
            params.update(parse_cli_args([arg]))
        except yaml.YAMLError as ex:
            raise PrerequisiteError(
                f"{args_source} {arg!r} does not have a valid YAML value: "
                f"{getattr(ex, 'problem', None) or ex}."
            ) from None
    return SentinelConfig.model_validate({"name": sentinel, "params": params})


SENTINEL_MIN_VERSION = "0.3.0"
"""The oldest inspect_sentinel that this inspect_ai works with."""


def _require_sentinel() -> None:
    try:
        importlib.import_module("inspect_sentinel._integration")
    except ImportError as ex:
        raise PrerequisiteError(
            "[bold]ERROR[/bold]: Sentinel support requires the inspect_sentinel package. "
            "Install it with:\n\n"
            "[bold]pip install inspect-sentinel[/bold]"
        ) from ex
    try:
        supported = has_required_version("inspect-sentinel", SENTINEL_MIN_VERSION)
    except PackageNotFoundError as ex:
        raise PrerequisiteError(
            "[bold]ERROR[/bold]: The installed inspect_sentinel has no package metadata, "
            "so its version can't be checked. Sentinel support requires "
            f"inspect-sentinel>={SENTINEL_MIN_VERSION}. Install it with:\n\n"
            f'[bold]pip install "inspect-sentinel>={SENTINEL_MIN_VERSION}"[/bold]'
        ) from ex
    if not supported:
        raise PrerequisiteError(
            f"[bold]ERROR[/bold]: Sentinel support requires inspect-sentinel>={SENTINEL_MIN_VERSION} "
            f"(you have version {version('inspect-sentinel')} installed). "
            "Upgrade it with:\n\n"
            f'[bold]pip install --upgrade "inspect-sentinel>={SENTINEL_MIN_VERSION}"[/bold]'
        )


def resolve_sentinel_spec(spec: SentinelSpec) -> Sentinels:
    _require_sentinel()
    from inspect_sentinel._integration import sentinel_from_config

    if isinstance(spec, str | SentinelConfig) or not _is_constructed(spec):
        sentinels: Sentinels = sentinel_from_config(cast(str | SentinelConfig, spec))
    else:
        sentinels = cast(Sentinels, spec)
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


def resolve_sentinel_root(sentinels: Sentinels) -> SentinelRoot:
    _require_sentinel()
    from inspect_sentinel._integration import resolve_sentinel

    return resolve_sentinel(cast("inspect_sentinel._integration.Sentinels", sentinels))


def sentinel_config(sentinels: Sentinels) -> SentinelConfig:
    _require_sentinel()
    from inspect_sentinel._integration import config_from_sentinel

    return config_from_sentinel(
        cast("inspect_sentinel._integration.Sentinels", sentinels)
    )
