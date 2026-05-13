"""PEP 562 lazy attribute loader for package ``__init__`` modules.

Several ``inspect_ai`` subpackages re-export both lightweight type/protocol
modules and heavyweight implementation modules. Eagerly importing the latter
from ``__init__.py`` creates a latent circular import between ``log``,
``event``, ``scorer``, ``solver`` and ``agent`` (each package's eager imports
transitively reach back into one of the others before it has finished
initialising). ``lazy_attributes()`` lets a package keep its full public
surface while only paying the import cost for an attribute when it is first
accessed.
"""

import sys
from importlib import import_module
from typing import Any


def lazy_attributes(module_name: str, attrs: dict[str, str]) -> None:
    """Install a PEP 562 ``__getattr__``/``__dir__`` pair on ``module_name``.

    Args:
        module_name: Fully-qualified name of the module to patch
            (callers pass ``__name__``).
        attrs: Mapping of attribute name to the absolute dotted path of the
            module that defines it. The attribute is imported from that
            module on first access and cached on the package.

    Any pre-existing ``__getattr__`` (e.g. one installed by
    :func:`inspect_ai._util.deprecation.relocated_module_attribute`) is
    chained so deprecated aliases keep working.
    """
    mod = sys.modules[module_name]
    # only chain to instance-level hooks set on this module's __dict__;
    # getattr(mod, "__dir__") would return ModuleType.__dir__, which per
    # PEP 562 delegates back to mod.__dict__["__dir__"] -> infinite recursion.
    prev_getattr = vars(mod).get("__getattr__")
    prev_dir = vars(mod).get("__dir__")

    # clear any previously-cached lazy attrs so importlib.reload() picks up
    # fresh values rather than returning stale objects from the old module
    for k in attrs:
        vars(mod).pop(k, None)

    def __getattr__(name: str) -> Any:
        target = attrs.get(name)
        if target is not None:
            val = getattr(import_module(target), name)
            setattr(mod, name, val)
            return val
        if prev_getattr is not None:
            return prev_getattr(name)
        raise AttributeError(f"module {module_name!r} has no attribute {name!r}")

    def __dir__() -> list[str]:
        base = list(prev_dir()) if prev_dir is not None else list(vars(mod))
        return sorted(set(base) | set(attrs))

    mod.__getattr__ = __getattr__  # type: ignore[method-assign]
    mod.__dir__ = __dir__  # type: ignore[method-assign]
