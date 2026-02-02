import logging
import os
import zipfile
from typing import Any

logger = logging.getLogger(__name__)

zipfile_compress_kwargs: dict[str, Any]
if os.getenv("INSPECT_USE_ZSTD"):
    zipfile_compress_kwargs = {
        "compression": zipfile.ZIP_ZSTANDARD,  # type: ignore[attr-defined]
        "compresslevel": None,
    }
else:
    zipfile_compress_kwargs = {
        "compression": zipfile.ZIP_DEFLATED,
        "compresslevel": 5,
    }


__all__ = ["zipfile_compress_kwargs"]
