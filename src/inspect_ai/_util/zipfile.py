import logging
import sys
import zipfile
from typing import Any

logger = logging.getLogger(__name__)

# On Python < 3.14, monkey-patch zipfile to support zstandard compression.
if sys.version_info < (3, 14):
    import zipfile_zstd  # type: ignore[import-not-found, import-untyped]  # noqa: F401

zipfile_compress_kwargs: dict[str, Any] = {
    "compression": zipfile.ZIP_ZSTANDARD,  # type: ignore[attr-defined]
    "compresslevel": None,
}

__all__ = ["zipfile_compress_kwargs"]
