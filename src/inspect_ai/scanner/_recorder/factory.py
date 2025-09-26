from .file import FileRecorder
from .recorder import ScanRecorder


def scan_recorder_for_location(scan_location: str) -> ScanRecorder:
    return FileRecorder()


def scan_recorder_type_for_location(scan_location: str) -> type[ScanRecorder]:
    return FileRecorder
