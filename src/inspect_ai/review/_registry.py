import inspect
from typing import Any, Callable, TypeVar, cast

from typing_extensions import overload

from inspect_ai._util.registry import (
    RegistryInfo,
    registry_add,
    registry_name,
    registry_tag,
)

from ._reviewer import Reviewer

ReviewerType = TypeVar("ReviewerType", bound=Callable[..., Reviewer])


@overload
def reviewer(func: ReviewerType) -> ReviewerType: ...


@overload
def reviewer(
    *, name: str | None = ..., **attribs: Any
) -> Callable[[ReviewerType], ReviewerType]: ...


def reviewer(*args: Any, name: str | None = None, **attribs: Any) -> Any:
    r"""Decorator for registering reviewers.

    Args:
      *args: Function returning `Reviewer` targeted by
        plain reviewer decorator without attributes (e.g. `@reviewer`)
      name:
        Optional name for reviewer. If the decorator has no name
        argument then the name of the function
        will be used to automatically assign a name.
      **attribs: Additional reviewer attributes.

    Returns:
        Reviewer with registry attributes.
    """

    def create_reviewer_wrapper(reviewer_type: ReviewerType) -> ReviewerType:
        reviewer_name = registry_name(
            reviewer_type, name or getattr(reviewer_type, "__name__")
        )
        params = list(inspect.signature(reviewer_type).parameters.keys())

        def wrapper(*w_args: Any, **w_kwargs: Any) -> Reviewer:
            reviewer_instance = reviewer_type(*w_args, **w_kwargs)
            registry_tag(
                reviewer_type,
                reviewer_instance,
                RegistryInfo(
                    type="reviewer",
                    name=reviewer_name,
                    metadata=dict(attribs=attribs, params=params),
                ),
                *w_args,
                **w_kwargs,
            )
            return reviewer_instance

        registry_add(
            wrapper,
            RegistryInfo(
                type="reviewer",
                name=reviewer_name,
                metadata=dict(attribs=attribs, params=params),
            ),
        )
        return cast(ReviewerType, wrapper)

    if args:
        return create_reviewer_wrapper(args[0])
    else:

        def decorator(func: ReviewerType) -> ReviewerType:
            return create_reviewer_wrapper(func)

        return decorator
