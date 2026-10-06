from collections.abc import Mapping
from typing import TYPE_CHECKING, Annotated, Any, Literal, TypeAlias, cast

from pydantic import (
    BaseModel,
    ConfigDict,
    Discriminator,
    Field,
    FiniteFloat,
    JsonValue,
    RootModel,
    StrictInt,
    Tag,
)

SentinelAction: TypeAlias = Literal[
    "continue", "modify", "reject", "terminate", "escalate"
]
"""What a sentinel protocol can decide about the step it examined."""

SentinelSuspicion: TypeAlias = (
    FiniteFloat | Annotated[dict[str, FiniteFloat], Field(min_length=1)]
)
"""How suspicious a step is: one finite score, or a non-empty dict of scores for several dimensions."""


class SentinelEntry(BaseModel):
    """One configured monitor or protocol.

    Any key besides `name`, `params`, `version` and `meta` names a parameter of the factory whose value is nested monitors or protocols, such as `monitors` for `threshold` or `children` for `concurrent`; it holds a list or a mapping of entries, and `nested` returns them.
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
    | Annotated[list[SentinelEntry], Tag("list")]
    | Annotated[dict[str, SentinelEntry], Tag("mapping")],
    Discriminator(
        _layer_kind,
        custom_error_type="sentinel_layer",
        custom_error_message="A sentinel layer is an entry with a string 'name', a list of entries, or a mapping of instance names to entries",
    ),
]


class SentinelConfig(RootModel[SentinelLayer]):
    """A sentinel configuration: one entry, a list of entries, or a mapping of instance names to entries.

    The value of the `sentinel:` key in a configuration file, and what the eval log records. A mapping is one entry when its `name` is a string, and a mapping of instance names when every value is an entry, so an instance named `name` still configures a mapping.
    """


SentinelEntry.model_rebuild()
