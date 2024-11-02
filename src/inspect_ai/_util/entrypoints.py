from importlib.metadata import entry_points
from logging import getLogger

logger = getLogger(__name__)


def ensure_entry_points(package: str | None = None) -> None:
    # have we already loaded all entry points?
    global _inspect_ai_eps_loaded_all
    if _inspect_ai_eps_loaded_all:
        return None

    # have we already loaded entry points for this package?
    if package in _inspect_ai_eps_loaded:
        return None

    # enumerate entry points
    eps = entry_points(group="inspect_ai")
    for ep in eps:
        try:
            # if there is a package filter then condition on that
            if package is not None:
                if ep.name and (ep.name == package):
                    ep.load()
                    _inspect_ai_eps_loaded.append(package)

            # if there is no package filter then load unconditionally
            # and mark us as fully loaded
            else:
                ep.load()
                _inspect_ai_eps_loaded_all = True

        except Exception as ex:
            logger.warning(
                f"Unexpected exception loading entrypoints from '{ep.value}': {ex}"
            )


# inspect extension entry points
_inspect_ai_eps_loaded: list[str] = []
_inspect_ai_eps_loaded_all: bool = False
