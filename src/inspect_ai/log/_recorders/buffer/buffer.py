from .database import SampleBufferDatabase, cleanup_sample_buffer_databases
from .types import SampleBuffer


def sample_buffer(location: str) -> SampleBuffer:
    return SampleBufferDatabase(location)


def cleanup_sample_buffers(log_dir: str) -> None:
    cleanup_sample_buffer_databases()
