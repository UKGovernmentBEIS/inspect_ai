# from https://pyomo.readthedocs.io/en/stable/_modules/pyomo/common/deprecation.html


import inspect
import logging
import textwrap
from types import FrameType
from typing import Any, Set


def relocated_module_attribute(
    local: str,
    target: str,
    version: str | None = None,
    remove_in: str | None = None,
    msg: str | None = None,
    f_globals: dict[str, Any] | None = None,
) -> None:
    """Provide a deprecation path for moved / renamed module attributes

    This function declares that a local module attribute has been moved
    to another location.  For Python 3.7+, it leverages a
    module.__getattr__ method to manage the deferred import of the
    object from the new location (on request), as well as emitting the
    deprecation warning.

    Params:

        local (str): The original (local) name of the relocated attribute
        target (str): The new absolute import name of the relocated attribute
        version (str): The Pyomo version when this move was released
          (passed to deprecation_warning)
        remove_in (str | None): The Pyomo version when this deprecation path
          will be removed (passed to deprecation_warning)
        msg (str | None): If not None, then this specifies a custom deprecation
          message to be emitted when the attribute is accessed from its original
         location.

    """
    # Historical note: This method only works for Python >= 3.7.  There
    # were backports to previous Python interpreters, but were removed
    # after SHA 4e04819aaeefc2c08b7718460918885e12343451
    if f_globals is None:
        frame = inspect.currentframe()
        if frame:
            back = frame.f_back
            if back:
                f_globals = back.f_globals
                if f_globals["__name__"].startswith("importlib."):
                    raise RuntimeError(
                        "relocated_module_attribute() called from a cythonized "
                        "module without passing f_globals"
                    )
    if f_globals is None:
        raise RuntimeError("No f_globals available.")
    _relocated = f_globals.get("__relocated_attrs__", None)
    if _relocated is None:
        f_globals["__relocated_attrs__"] = _relocated = {}
        _mod_getattr = f_globals.get("__getattr__", None)

        def __getattr__(name: str) -> Any:
            info = _relocated.get(name, None)
            if info is not None:
                target_obj = _import_object(name, *info)
                f_globals[name] = target_obj
                return target_obj
            elif _mod_getattr is not None:
                return _mod_getattr(name)
            raise AttributeError(
                "module '%s' has no attribute '%s'" % (f_globals["__name__"], name)
            )

        f_globals["__getattr__"] = __getattr__
    _relocated[local] = (target, version, remove_in, msg)


def _import_object(
    name: str,
    target: str,
    version: str | None = None,
    remove_in: str | None = None,
    msg: str | None = None,
) -> Any:
    from importlib import import_module

    modname, targetname = target.rsplit(".", 1)
    _object = getattr(import_module(modname), targetname)
    if msg is None:
        if inspect.isclass(_object):
            _type = "class"
        elif inspect.isfunction(_object):
            _type = "function"
        else:
            _type = "attribute"
        msg = (
            f"the '{name}' {_type} has been moved to '{target}'."
            " Please update your import."
        )
    deprecation_warning(msg, version=version, remove_in=remove_in)
    return _object


def deprecation_warning(
    msg: str,
    version: str | None = None,
    remove_in: str | None = None,
    calling_frame: FrameType | None = None,
) -> None:
    logger = logging.getLogger(__name__)

    msg = textwrap.fill(
        f"DEPRECATED: {default_deprecation_msg(None, msg, version, remove_in)}",
        width=70,
    )
    if calling_frame is None:
        # The useful thing to let the user know is what called the
        # function that generated the deprecation warning.  The current
        # globals() is *this* module.  Walking up the stack to find the
        # frame where the globals() changes tells us the module that is
        # issuing the deprecation warning.  As we assume that *that*
        # module will not trigger its own deprecation warnings, we will
        # walk farther up until the globals() changes again.
        calling_frame = _find_calling_frame(2)
    if calling_frame is not None:
        info = inspect.getframeinfo(calling_frame)
        msg += "\n(called from %s:%s)" % (info.filename.strip(), info.lineno)
        if msg in _emitted_warnings:
            return
        _emitted_warnings.add(msg)

    from inspect_ai._util.logger import warn_once

    warn_once(logger, msg)


_emitted_warnings: Set[str] = set()


def _find_calling_frame(module_offset: int) -> FrameType | None:
    g = [globals()]
    frame = inspect.currentframe()
    if frame is not None:
        calling_frame = frame.f_back
        while calling_frame is not None:
            if calling_frame.f_globals is g[-1]:
                calling_frame = calling_frame.f_back
            elif len(g) < module_offset:
                g.append(calling_frame.f_globals)
            else:
                break
        return calling_frame
    else:
        return None


def default_deprecation_msg(
    obj: Any, user_msg: str, version: str | None, remove_in: str | None
) -> str:
    """Generate the default deprecation message.

    See deprecated() function for argument details.
    """
    if user_msg is None:
        if inspect.isclass(obj):
            _obj = " class"
        elif inspect.ismethod(obj):
            _obj = " method"
        elif inspect.isfunction(obj) or inspect.isbuiltin(obj):
            _obj = " function"
        else:
            # either @deprecated() an unknown type or called from
            # deprecation_warning()
            _obj = ""

        _qual = getattr(obj, "__qualname__", "") or ""
        if _qual.endswith(".__init__") or _qual.endswith(".__new__"):
            _obj = f' class ({_qual.rsplit(".", 1)[0]})'
        elif _qual and _obj:
            _obj += f" ({_qual})"

        user_msg = (
            "This%s has been deprecated and may be removed in a "
            "future release." % (_obj,)
        )
    comment = []
    if version:
        comment.append("deprecated in %s" % (version,))
    if remove_in:
        comment.append("will be removed in %s" % (remove_in))
    if comment:
        return user_msg + "  (%s)" % (", ".join(comment),)
    else:
        return user_msg
