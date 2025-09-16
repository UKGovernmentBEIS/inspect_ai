from dataclasses import dataclass, field
from functools import wraps
from typing import (
    AsyncGenerator,
    Callable,
    Literal,
    ParamSpec,
    Protocol,
    Sequence,
    TypeVar,
    cast,
)

from inspect_ai._util._async import is_callable_coroutine
from inspect_ai._util.registry import (
    RegistryInfo,
    registry_add,
    registry_name,
    registry_tag,
)

from ._filter import (
    EventType,
    MessageType,
    TranscriptContent,
    normalize_events_filter,
    normalize_messages_filter,
)
from ._transcript import Transcript

T = TypeVar("T", covariant=True)
P = ParamSpec("P")


class Loader(Protocol[T]):
    def __call__(
        self,
        input: Transcript | Sequence[Transcript],
        /,
    ) -> AsyncGenerator[T, None]: ...

    __loader__: "LoaderConfig"


@dataclass
class LoaderConfig:
    name: str
    content: TranscriptContent = field(default_factory=TranscriptContent)


LoaderFactory = Callable[P, Loader[T]]


def loader(
    *,
    name: str | None = None,
    messages: list[MessageType] | Literal["all"] | None = None,
    events: list[EventType] | Literal["all"] | None = None,
) -> Callable[[LoaderFactory[P, T]], LoaderFactory[P, T]]:
    messages = normalize_messages_filter(messages) if messages is not None else None
    events = normalize_events_filter(events) if events is not None else None

    def decorate(factory: LoaderFactory[P, T]) -> LoaderFactory[P, T]:
        loader_name = registry_name(
            factory, name or str(getattr(factory, "__name__", "loader"))
        )

        @wraps(factory)
        def factory_wrapper(*args: P.args, **kwargs: P.kwargs) -> Loader[T]:
            loader_fn = factory(*args, **kwargs)

            if not is_callable_coroutine(loader_fn):
                raise TypeError(
                    f"'{loader_name}' is not declared as an async callable."
                )

            loader_config = LoaderConfig(name=loader_name)
            if messages is not None:
                loader_config.content.messages = messages
            if events is not None:
                loader_config.content.events = events
            setattr(loader_fn, "__loader__", loader_config)  # type: ignore[attr-defined]

            registry_tag(
                factory,
                loader_fn,
                RegistryInfo(type="loader", name=loader_name),
                *args,
                **kwargs,
            )
            return loader_fn

        registry_add(
            factory,
            RegistryInfo(type="loader", name=loader_name),
        )
        return cast(LoaderFactory[P, T], factory_wrapper)

    return decorate
