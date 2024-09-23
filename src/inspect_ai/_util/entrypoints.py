from importlib.metadata import EntryPoints, entry_points
from logging import getLogger

logger = getLogger(__name__)


def ensure_entry_points() -> None:
    # ensure that inspect model provider extensions are loaded if
    # they haven't been already
    global _inspect_ai_eps
    if not _inspect_ai_eps:
        _inspect_ai_eps = entry_points(group="inspect_ai")
        for ep in _inspect_ai_eps:
            try:
                ep.load()
            except Exception as ex:
                logger.warning(
                    f"Unexpected exception loading entrypoints from '{ep.value}': {ex}"
                )


# inspect extension entry points
_inspect_ai_eps: EntryPoints | None = None
