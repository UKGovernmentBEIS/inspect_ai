import inspect
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Sequence, TypeVar, cast, overload

from inspect_ai._util.package import get_installed_package_name
from inspect_ai._util.registry import (
    RegistryInfo,
    is_registry_object,
    registry_add,
    registry_info,
    registry_name,
    registry_tag,
    registry_unqualified_name,
)
from inspect_ai.scanner._scanner.types import ScannerInput

from ._scanner.scanner import Scanner
from ._transcript.transcripts import Transcripts


class ScanJob:
    def __init__(
        self,
        *,
        transcripts: Transcripts | None = None,
        scanners: Sequence[Scanner[ScannerInput] | tuple[str, Scanner[ScannerInput]]]
        | dict[str, Scanner[ScannerInput]],
        name: str | None = None,
    ):
        # save transcripts and name
        self._trancripts = transcripts
        self._name = name

        # resolve scanners and confirm unique names
        self._scanners: dict[str, Scanner[ScannerInput]] = {}
        if isinstance(scanners, dict):
            self._scanners = scanners
        else:
            for scanner in scanners:
                if isinstance(scanner, tuple):
                    name, scanner = scanner
                else:
                    name = registry_unqualified_name(scanner)
                if name in self._scanners:
                    raise ValueError(
                        f"Scanners must have unique names (found duplicate name '{name}'). Use a tuple of str,Scanner to explicitly name a scanner."
                    )
                self._scanners[name] = scanner

    @property
    def name(self) -> str:
        if self._name is not None:
            return self._name
        elif is_registry_object(self):
            return registry_info(self).name
        else:
            return "scan"

    @property
    def transcripts(self) -> Transcripts | None:
        return self._trancripts

    @property
    def scanners(self) -> dict[str, Scanner[ScannerInput]]:
        return self._scanners


ScanJobType = TypeVar("ScanJobType", bound=Callable[..., ScanJob])

SCANJOB_FILE_ATTR = "__scanjob_file__"


@overload
def scanjob(func: ScanJobType) -> ScanJobType: ...


@overload
def scanjob(
    *,
    name: str | None = ...,
) -> Callable[[ScanJobType], ScanJobType]: ...


def scanjob(
    func: ScanJobType | None = None, *, name: str | None = None
) -> ScanJobType | Callable[[ScanJobType], ScanJobType]:
    r"""Decorator for registering scan jobs.

    Args:
      func: Function returning `ScanJob` targeted by
        plain task decorator without attributes (e.g. `@scanjob`)
      name:
        Optional name for scanjob. If the decorator has no name
        argument then the name of the function
        will be used to automatically assign a name.

    Returns:
        ScanJob with registry attributes.
    """

    def create_scanjob_wrapper(scanjob_type: ScanJobType) -> ScanJobType:
        # Get the name and parameters of the task
        scanjob_name = registry_name(
            scanjob_type, name or getattr(scanjob_type, "__name__")
        )
        params = list(inspect.signature(scanjob_type).parameters.keys())

        # Create and return the wrapper function
        @wraps(scanjob_type)
        def wrapper(*w_args: Any, **w_kwargs: Any) -> ScanJob:
            # Create the scanjob
            scanjob_instance = scanjob_type(*w_args, **w_kwargs)

            # Tag the task with registry information
            registry_tag(
                scanjob_type,
                scanjob_instance,
                RegistryInfo(
                    type="scanjob",
                    name=scanjob_name,
                    metadata=dict(params=params),
                ),
                *w_args,
                **w_kwargs,
            )

            # if its not from an installed package then it is a "local"
            # module import, so set its task file and run dir
            if get_installed_package_name(scanjob_type) is None:
                module = inspect.getmodule(scanjob_type)
                if module and hasattr(module, "__file__") and module.__file__:
                    file = Path(getattr(module, "__file__"))
                    setattr(scanjob_instance, SCANJOB_FILE_ATTR, file.as_posix())

            # Return the task instance
            return scanjob_instance

        # functools.wraps overrides the return type annotation of the inner function, so
        # we explicitly set it again
        wrapper.__annotations__["return"] = ScanJob

        # Register the task and return the wrapper
        wrapped_scanjob_type = cast(ScanJobType, wrapper)
        registry_add(
            wrapped_scanjob_type,
            RegistryInfo(
                type="scanjob",
                name=scanjob_name,
                metadata=(dict(params=params)),
            ),
        )
        return wrapped_scanjob_type

    if func:
        return create_scanjob_wrapper(func)
    else:
        # The decorator was used with arguments: @scanjob(name="foo")
        def decorator(func: ScanJobType) -> ScanJobType:
            return create_scanjob_wrapper(func)

        return decorator
