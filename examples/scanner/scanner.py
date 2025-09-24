from pathlib import Path

from inspect_ai.scanner import (
    Result,
    Scanner,
    Transcript,
    scan,
    scanner,
    transcripts,
)
from inspect_ai.scanner._scandef import ScanDef


@scanner(messages="all")
def dummy_scanner() -> Scanner:
    async def execute(transcript: Transcript) -> Result:
        return Result(value=1, explanation="I did the scan")

    return execute


if __name__ == "__main__":
    LOGS_DIR = Path(__file__).parent / "logs"
    SCANS_DIR = Path(__file__).parent / "scans"

    results = scan(
        ScanDef(transcripts=transcripts(LOGS_DIR), scanners=[dummy_scanner()]),
        scans_dir=SCANS_DIR.as_posix(),
    )

    results.scanners["dummy_scanner"].info()
