import inspect
from functools import wraps
from pathlib import Path
from typing import Any, Callable, Sequence, TypeVar, cast, overload

from inspect_ai._util.package import get_installed_package_name
from inspect_ai._util.registry import (
    RegistryInfo,
    extract_named_params,
    is_registry_object,
    registry_add,
    registry_info,
    registry_name,
    registry_tag,
    registry_unqualified_name,
)

from ._scanner.scanner import Scanner
from ._transcript.transcripts import Transcripts


class ScanDef:
    def __init__(
        self,
        *,
        transcripts: Transcripts | None = None,
        scanners: Sequence[Scanner[Any] | tuple[str, Scanner[Any]]]
        | dict[str, Scanner[Any]],
        name: str | None = None,
    ):
        # save transcripts and name
        self._trancripts = transcripts
        self._name = name

        # resolve scanners and confirm unique names
        self._scanners: dict[str, Scanner[Any]] = {}
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
    def scanners(self) -> dict[str, Scanner[Any]]:
        return self._scanners


ScanDefType = TypeVar("ScanDefType", bound=Callable[..., ScanDef])

SCANDEF_FILE_ATTR = "__scandef_file__"
SCANDEF_ALL_PARAMS_ATTR = "__scandef_all_params__"


@overload
def scandef(func: ScanDefType) -> ScanDefType: ...


@overload
def scandef(
    *, name: str | None = ..., **attribs: Any
) -> Callable[[ScanDefType], ScanDefType]: ...


def scandef(*args: Any, name: str | None = None, **attribs: Any) -> Any:
    r"""Decorator for registering scan definitions.

    Args:
      *args: Function returning `ScanDef` targeted by
        plain task decorator without attributes (e.g. `@scandef`)
      name:
        Optional name for scandef. If the decorator has no name
        argument then the name of the function
        will be used to automatically assign a name.
      **attribs: (dict[str,Any]): Additional scandef attributes.

    Returns:
        ScanDef with registry attributes.
    """

    def create_scandef_wrapper(scandef_type: ScanDefType) -> ScanDefType:
        # Get the name and parameters of the task
        scandef_name = registry_name(
            scandef_type, name or getattr(scandef_type, "__name__")
        )
        params = list(inspect.signature(scandef_type).parameters.keys())

        # Create and return the wrapper function
        @wraps(scandef_type)
        def wrapper(*w_args: Any, **w_kwargs: Any) -> ScanDef:
            # Create the scandef
            scandef_instance = scandef_type(*w_args, **w_kwargs)

            # Tag the task with registry information
            registry_tag(
                scandef_type,
                scandef_instance,
                RegistryInfo(
                    type="scandef",
                    name=scandef_name,
                    metadata=dict(attribs=attribs, params=params),
                ),
                *w_args,
                **w_kwargs,
            )

            # extract all task parameters including defaults
            named_params = extract_named_params(scandef_type, True, *w_args, **w_kwargs)
            setattr(scandef_instance, SCANDEF_ALL_PARAMS_ATTR, named_params)

            # if its not from an installed package then it is a "local"
            # module import, so set its task file and run dir
            if get_installed_package_name(scandef_type) is None:
                module = inspect.getmodule(scandef_type)
                if module and hasattr(module, "__file__") and module.__file__:
                    file = Path(getattr(module, "__file__"))
                    setattr(scandef_instance, SCANDEF_FILE_ATTR, file.as_posix())

            # Return the task instance
            return scandef_instance

        # functools.wraps overrides the return type annotation of the inner function, so
        # we explicitly set it again
        wrapper.__annotations__["return"] = ScanDef

        # Register the task and return the wrapper
        wrapped_scandef_type = cast(ScanDefType, wrapper)
        registry_add(
            wrapped_scandef_type,
            RegistryInfo(
                type="scandef",
                name=scandef_name,
                metadata=(dict(attribs=attribs, params=params)),
            ),
        )
        return wrapped_scandef_type

    if args:
        # The decorator was used without arguments: @scandef
        func = args[0]
        return create_scandef_wrapper(func)
    else:
        # The decorator was used with arguments: @scandef(name="foo")
        def decorator(func: ScanDefType) -> ScanDefType:
            return create_scandef_wrapper(func)

        return decorator
