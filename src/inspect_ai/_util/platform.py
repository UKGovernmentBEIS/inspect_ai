import importlib.util
import os

from .error import set_exception_hook


def running_in_notebook() -> bool:
    try:
        from IPython import get_ipython  # type: ignore

        if "IPKernelApp" not in get_ipython().config:  # type: ignore
            return False
    except ImportError:
        return False
    except AttributeError:
        return False
    return True


def platform_init() -> None:
    # set exception hook if we haven't already
    set_exception_hook()

    # if we are running in a notebook, confirm that we have ipywidgets
    if running_in_notebook():
        # check for required packages
        if not have_package("ipywidgets"):
            raise ModuleNotFoundError(
                "To using inspect_ai within a notebook, please install ipywidgets with:\n\n"
                + "pip install ipywidgets\n"
            )

        # activate nest_asyncio (required so we operate properly within
        # the Jupyter async event loop)
        import nest_asyncio  # type: ignore

        nest_asyncio.apply()


def have_package(package: str) -> bool:
    return importlib.util.find_spec(package) is not None


def is_running_in_jupyterlab() -> bool:
    return os.getenv("JPY_SESSION_NAME", None) is not None


def is_running_in_vscode() -> bool:
    # Check if running in VS Code Jupyter notebook or interactive window
    if (
        os.getenv("VSCODE_IPYTHON_KERNEL") is not None
        or os.getenv("VSCODE_CLI_REQUIRE_TOKEN") is not None
        or os.getenv("VSCODE_PID") is not None
        or os.getenv("VSCODE_CWD") is not None
    ):
        return True
    # Check if running in a VS Code terminal
    if os.getenv("TERM_PROGRAM") == "vscode":
        return True

    # If none of the conditions are met, we assume it's not running in VS Code
    return False


def is_windows() -> bool:
    return os.name == "nt"
