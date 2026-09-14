import os
from logging import getLogger

import psutil

from inspect_ai._util.file import filesystem

from .database import (
    SampleBufferDatabase,
    cleanup_sample_buffer_databases,
    cleanup_sample_buffer_db,
    sample_buffer_db_pid,
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


def cleanup_sample_buffers_for_log(location: str) -> bool:
    """Remove the sample buffers of a log no other process is writing.

    Deletes the log's buffer databases and its filestore directory. A
    database created by another process that is still alive means that
    process may still be writing the log, so nothing is removed. Databases
    this process created are removed regardless: the caller is the process
    that opened them and runs only once the attempt that did so has ended.

    Args:
        location: Eval log location whose buffers to remove.

    Returns:
        ``True`` when the log's buffers were removed (or it had none),
        ``False`` when another live process holds a buffer database for it.
    """
    dbs = sample_buffer_dbs(location)
    for db in dbs:
        pid = sample_buffer_db_pid(db)
        if pid is not None and pid != os.getpid() and psutil.pid_exists(pid):
            return False
    for db in dbs:
        cleanup_sample_buffer_db(db)
    fs = filesystem(location)
    filestore_dir = sample_buffer_filestore_dir(location, fs)
    if fs.exists(filestore_dir):
        cleanup_sample_buffer_filestore(filestore_dir, fs)
    return True


async def cleanup_sample_buffers(log_dir: str) -> None:
    try:
        cleanup_sample_buffer_databases()
        await cleanup_sample_buffer_filestores(log_dir)
    except Exception as ex:
        logger.warning(f"Unexpected error cleaning up sample buffers: {ex}")
