import inspect
from typing import Any, Callable, TypeVar, cast

from typing_extensions import overload

from inspect_ai._util.registry import (
    RegistryInfo,
    registry_add,
    registry_name,
    registry_tag,
)

from ._types import InputHandler, InputNotifier

InputHandlerType = TypeVar("InputHandlerType", bound=Callable[..., InputHandler])
InputNotifierType = TypeVar("InputNotifierType", bound=Callable[..., InputNotifier])


@overload
def input_handler(func: InputHandlerType) -> InputHandlerType: ...


@overload
def input_handler(
    *, name: str | None = ..., **attribs: Any
) -> Callable[[InputHandlerType], InputHandlerType]: ...


def input_handler(*args: Any, name: str | None = None, **attribs: Any) -> Any:
    r"""Decorator for registering input handlers.

    Args:
      *args: Function returning `InputHandler` targeted by
        plain handler decorator without attributes (e.g. `@input_handler`)
      name: Optional name for handler. If the decorator has no name
        argument then the name of the function will be used to
        automatically assign a name.
      **attribs: Additional handler attributes.

    Returns:
        Input handler factory with registry attributes.
    """

    def create_handler_wrapper(handler_type: InputHandlerType) -> InputHandlerType:
        handler_name = registry_name(
            handler_type, name or getattr(handler_type, "__name__")
        )
        params = list(inspect.signature(handler_type).parameters.keys())

        def wrapper(*w_args: Any, **w_kwargs: Any) -> InputHandler:
            handler_instance = handler_type(*w_args, **w_kwargs)
            registry_tag(
                handler_type,
                handler_instance,
                RegistryInfo(
                    type="input_handler",
                    name=handler_name,
                    metadata=dict(attribs=attribs, params=params),
                ),
                *w_args,
                **w_kwargs,
            )
            return handler_instance

        return _register(
            obj=cast(InputHandlerType, wrapper),
            type="input_handler",
            name=handler_name,
            attribs=attribs,
            params=params,
        )

    if args:
        func = args[0]
        return create_handler_wrapper(func)
    else:

        def decorator(func: InputHandlerType) -> InputHandlerType:
            return create_handler_wrapper(func)

        return decorator


@overload
def input_notifier(func: InputNotifierType) -> InputNotifierType: ...


@overload
def input_notifier(
    *, name: str | None = ..., **attribs: Any
) -> Callable[[InputNotifierType], InputNotifierType]: ...


def input_notifier(*args: Any, name: str | None = None, **attribs: Any) -> Any:
    r"""Decorator for registering input notifiers.

    Args:
      *args: Function returning `InputNotifier` targeted by
        plain notifier decorator without attributes (e.g. `@input_notifier`)
      name: Optional name for notifier. If the decorator has no name
        argument then the name of the function will be used to
        automatically assign a name.
      **attribs: Additional notifier attributes.

    Returns:
        Input notifier factory with registry attributes.
    """

    def create_notifier_wrapper(notifier_type: InputNotifierType) -> InputNotifierType:
        notifier_name = registry_name(
            notifier_type, name or getattr(notifier_type, "__name__")
        )
        params = list(inspect.signature(notifier_type).parameters.keys())

        def wrapper(*w_args: Any, **w_kwargs: Any) -> InputNotifier:
            notifier_instance = notifier_type(*w_args, **w_kwargs)
            registry_tag(
                notifier_type,
                notifier_instance,
                RegistryInfo(
                    type="input_notifier",
                    name=notifier_name,
                    metadata=dict(attribs=attribs, params=params),
                ),
                *w_args,
                **w_kwargs,
            )
            return notifier_instance

        return _register(
            obj=cast(InputNotifierType, wrapper),
            type="input_notifier",
            name=notifier_name,
            attribs=attribs,
            params=params,
        )

    if args:
        func = args[0]
        return create_notifier_wrapper(func)
    else:

        def decorator(func: InputNotifierType) -> InputNotifierType:
            return create_notifier_wrapper(func)

        return decorator


_RegisteredT = TypeVar("_RegisteredT", bound=Callable[..., Any])


def _register(
    obj: _RegisteredT,
    type: str,
    name: str,
    attribs: dict[str, Any],
    params: list[str],
) -> _RegisteredT:
    registry_add(
        obj,
        RegistryInfo(
            type=cast(Any, type),
            name=name,
            metadata=dict(attribs=attribs, params=params),
        ),
    )
    return obj
