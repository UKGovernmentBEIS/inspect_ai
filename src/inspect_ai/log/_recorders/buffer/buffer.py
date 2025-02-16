from .database import SampleBufferDatabase, cleanup_sample_buffer_databases
from .filestore import SampleBufferFilestore
from .types import SampleBuffer


def sample_buffer(location: str) -> SampleBuffer:
    buffer = SampleBufferDatabase(location, create=False)
    if buffer.exists():
        return buffer
    else:
        return SampleBufferFilestore(location, create=False)


def cleanup_sample_buffers(log_dir: str) -> None:
    cleanup_sample_buffer_databases()
