from importlib.metadata import EntryPoints, entry_points


def ensure_entry_points() -> None:
    # ensure that inspect model provider extensions are loaded if
    # they haven't been already
    global _inspect_ai_eps
    if not _inspect_ai_eps:
        _inspect_ai_eps = entry_points(group="inspect_ai")
        [ep.load() for ep in _inspect_ai_eps]


# inspect extension entry points
_inspect_ai_eps: EntryPoints | None = None
