import logging
import os
import zipfile

logger = logging.getLogger(__name__)

zipfile_compress_kwargs = {
    "compression": zipfile.ZIP_DEFLATED,
    "compresslevel": 5,
}

if os.getenv("INSPECT_USE_ZSTD"):
    if hasattr(zipfile, "ZIP_ZSTANDARD"):
        logger.info(
            "Using zstandard compression. This will produce eval logs that are incompatible with Python < 3.14."
        )
        zipfile_compress_kwargs["compression"] = zipfile.ZIP_ZSTANDARD
        zipfile_compress_kwargs["compresslevel"] = None
    else:
        logger.warning(
            "INSPECT_USE_ZSTD was set but zstandard is not supported; are you using Python >= 3.14? Falling back to deflate."
        )

__all__ = ["zipfile_compress_kwargs"]
