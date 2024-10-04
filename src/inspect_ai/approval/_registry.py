import inspect
from typing import Any, Callable, TypeVar, cast

from typing_extensions import overload

from inspect_ai._util.registry import (
    RegistryInfo,
    registry_add,
    registry_name,
    registry_tag,
)

from ._approver import Approver

ApproverType = TypeVar("ApproverType", bound=Callable[..., Approver])


@overload
def approver(func: ApproverType) -> ApproverType: ...


@overload
def approver(
    *, name: str | None = ..., **attribs: Any
) -> Callable[[ApproverType], ApproverType]: ...


def approver(*args: Any, name: str | None = None, **attribs: Any) -> Any:
    r"""Decorator for registering approvers.

    Args:
      *args: Function returning `Approver` targeted by
        plain approver decorator without attributes (e.g. `@approver`)
      name (str | None):
        Optional name for approver. If the decorator has no name
        argument then the name of the function
        will be used to automatically assign a name.
      **attribs: (dict[str,Any]): Additional approver attributes.

    Returns:
        Approver with registry attributes.
    """

    def create_approver_wrapper(approver_type: ApproverType) -> ApproverType:
        # Get the name and parameters of the task
        approver_name = registry_name(
            approver_type, name or getattr(approver_type, "__name__")
        )
        params = list(inspect.signature(approver_type).parameters.keys())

        # Create and return the wrapper function
        def wrapper(*w_args: Any, **w_kwargs: Any) -> Approver:
            # Create the approver
            approver_instance = approver_type(*w_args, **w_kwargs)

            # Tag the approver with registry information
            registry_tag(
                approver_type,
                approver_instance,
                RegistryInfo(
                    type="approver",
                    name=approver_name,
                    metadata=dict(attribs=attribs, params=params),
                ),
                *w_args,
                **w_kwargs,
            )

            # Return the approver instance
            return approver_instance

        # Register the approver and return the wrapper
        return approver_register(
            approver=cast(ApproverType, wrapper),
            name=approver_name,
            attribs=attribs,
            params=params,
        )

    if args:
        # The decorator was used without arguments: @approver
        func = args[0]
        return create_approver_wrapper(func)
    else:
        # The decorator was used with arguments: @approver(name="foo")
        def decorator(func: ApproverType) -> ApproverType:
            return create_approver_wrapper(func)

        return decorator


def approver_register(
    approver: ApproverType, name: str, attribs: dict[str, Any], params: list[str]
) -> ApproverType:
    registry_add(
        approver,
        RegistryInfo(
            type="approver", name=name, metadata=dict(attribs=attribs, params=params)
        ),
    )
    return approver
