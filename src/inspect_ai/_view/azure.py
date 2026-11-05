"""Azure-specific helpers used across Inspect view components."""

import os
from typing import Any, Callable

from inspect_ai._util.azure import is_azure_path


def azure_debug_exists(fs: Any, path: str, printer: Callable[[str], None]) -> None:
    """Emit optional debugging information for Azure existence checks."""
    if not (is_azure_path(path) and os.getenv("INSPECT_AZURE_DEBUG")):
        return
    try:
        exists = fs.exists(path)
        printer(f"[azure-debug] exists({path}) -> {exists}")
    except Exception as ex:  # noqa: BLE001
        printer(f"[azure-debug] exists() raised: {ex}")


def azure_runtime_hint(error: Exception) -> str:
    """Standard message guiding users when Azure auth fails."""
    return (
        "Azure storage authentication failed. Try: (a) 'az login' or ensure role "
        "assignment (Storage Blob Data Reader/Contributor), or (b) supply SAS via "
        "AZURE_STORAGE_SAS_TOKEN. If using az:// ensure AZURE_STORAGE_ACCOUNT_NAME is set. "
        f"Original error: {error}"
    )


def normalize_azure_listing_name(log_dir: str, candidate: str) -> str:
    """Normalize abfs* URIs to az:// when the log dir uses az://."""
    if log_dir.startswith("az://") and candidate.startswith(("abfs://", "abfss://")):
        without_scheme = candidate.split("://", 1)[1]
        return f"az://{without_scheme}"
    return candidate
