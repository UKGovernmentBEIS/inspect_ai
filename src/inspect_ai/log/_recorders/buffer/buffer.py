from logging import getLogger

from inspect_ai._util.file import filesystem

from .database import (
    SampleBufferDatabase,
    cleanup_sample_buffer_databases,
    cleanup_sample_buffer_db,
    sample_buffer_dbs,
)
from .filestore import (
    SampleBufferFilestore,
    cleanup_sample_buffer_filestore,
    cleanup_sample_buffer_filestores,
    sample_buffer_filestore_dir,
)
from .types import SampleBuffer

logger = getLogger(__name__)


def sample_buffer(location: str) -> SampleBuffer:
    try:
        return SampleBufferDatabase(location, create=False)
    except FileNotFoundError:
        return SampleBufferFilestore(location, create=False)


def running_tasks(log_dir: str) -> list[str]:
    tasks = SampleBufferDatabase.running_tasks(log_dir)
    if tasks is not None:
        return tasks
    else:
        return SampleBufferFilestore.running_tasks(log_dir) or []


def cleanup_sample_buffers_for_log(location: str) -> None:
    """Remove the sample buffers of the log at ``location``.

    Deletes the log's local buffer databases and its filestore directory.
    The caller establishes that the log's writer has ended first.

    Args:
        location: Eval log location whose buffers to remove.
    """
    for db in sample_buffer_dbs(location):
        cleanup_sample_buffer_db(db)
    fs = filesystem(location)
    filestore_dir = sample_buffer_filestore_dir(location, fs)
    if fs.exists(filestore_dir):
        cleanup_sample_buffer_filestore(filestore_dir, fs)


async def cleanup_sample_buffers(log_dir: str) -> None:
    try:
        cleanup_sample_buffer_databases()
        await cleanup_sample_buffer_filestores(log_dir)
    except Exception as ex:
        logger.warning(f"Unexpected error cleaning up sample buffers: {ex}")
