from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import APIRouter


def get_scout_search_router() -> "APIRouter | None":
    """Return inspect_scout's search router if installed, else None.

    The search routes operate on the same transcript directory the view
    server is pointed at — scout's `transcripts_view()` factory auto-detects
    `.eval` log directories and reads them natively.
    """
    try:
        from inspect_scout._view._api_v2_search import create_search_router
    except Exception:
        return None
    try:
        return create_search_router()
    except Exception:
        return None
