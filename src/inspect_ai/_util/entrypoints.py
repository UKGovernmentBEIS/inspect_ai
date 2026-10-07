# Backward-compatible re-exports of names that moved to inspect_core.
from inspect_core._entrypoints import (
    _inspect_ai_eps_loaded as _inspect_ai_eps_loaded,
)
from inspect_core._entrypoints import (
    clear_entry_points_state as clear_entry_points_state,
)
from inspect_core._entrypoints import ensure_entry_points as ensure_entry_points

# End of backward-compatible re-exports.
