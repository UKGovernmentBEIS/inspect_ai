import importlib
from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Annotated, Any, TypeAlias, Union, cast

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

from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.registry import is_registry_object

if TYPE_CHECKING:
    from inspect_sentinel import Protocol
    from inspect_sentinel._integration import Sentinels
else:
    Sentinels: TypeAlias = Any


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


def _require_sentinel() -> None:
    try:
        importlib.import_module("inspect_sentinel._integration")
    except ImportError as ex:
        raise PrerequisiteError(
            "[bold]ERROR[/bold]: Sentinel support requires the inspect_sentinel package. "
            "Install it with:\n\n"
            "[bold]pip install inspect-sentinel[/bold]"
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
