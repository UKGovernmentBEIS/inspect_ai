import tempfile
from zipfile import ZIP_DEFLATED, ZipFile

from pydantic import BaseModel

from inspect_ai._util.file import basename, dirname, file, filesystem

from ..types import SampleSummary
from .types import AttachmentData, EventData


class Segment(BaseModel):
    id: int
    last_events: int
    last_attachments: int


class SegmentData(BaseModel):
    events: list[EventData]
    attachments: list[AttachmentData]


class SegmentFile(BaseModel):
    id: str | int
    epoch: int
    data: SegmentData


class SampleManifest(BaseModel):
    summary: SampleSummary
    segments: list[int]


class Manifest(BaseModel):
    samples: list[SampleManifest]
    segments: list[Segment]


MANIFEST = "manifest.json"


class SampleBufferFilestore:
    def __init__(self, location: str) -> None:
        self._fs = filesystem(location)
        self._dir = f"{dirname(location)}{self._fs.sep}.buffer{self._fs.sep}{basename(location)}{self._fs.sep}"
        self._fs.mkdir(self._dir, exist_ok=True)

    def write_manifest(self, manifest: Manifest) -> None:
        with tempfile.NamedTemporaryFile(mode="w") as manifest_file:
            # write the file locally
            with file(manifest_file.name, "w") as f:
                f.write(manifest.model_dump_json(indent=2))

            # transfer it up (use a mv so it's atomic)
            manifest_target = f"{self._dir}{MANIFEST}"
            manifest_temp = f"{manifest_target}.temp"
            self._fs.put_file(manifest_file.name, manifest_temp)
            self._fs.mv(manifest_temp, manifest_target)

    def write_segment(self, id: int, files: list[SegmentFile]) -> None:
        with tempfile.NamedTemporaryFile(mode="w+b") as segment_file:
            # write the segment file locally
            with ZipFile(
                segment_file, mode="a", compression=ZIP_DEFLATED, compresslevel=5
            ) as zip:
                for file in files:
                    zip.writestr(
                        segment_file_name(file.id, file.epoch),
                        file.data.model_dump_json(),
                    )

            # transfer it
            self._fs.put_file(segment_file.name, f"{self._dir}{segment_name(id)}")

    def read_manifest(self) -> Manifest | None:
        manifest_file = f"{self._dir}{MANIFEST}"
        try:
            with file(manifest_file, "r") as f:
                contents = f.read()
                return Manifest.model_validate_json(contents)
        except FileNotFoundError:
            return None

    def read_segment_data(
        self, id: int, sample_id: str | int, epoch_id: int
    ) -> SegmentData:
        segment_file = f"{self._dir}{segment_name(id)}"
        with file(segment_file, "rb") as f:
            with ZipFile(f, mode="r") as zip:
                with zip.open(segment_file_name(sample_id, epoch_id), "r") as sf:
                    return SegmentData.model_validate_json(sf.read())


def segment_name(id: int) -> str:
    return f"segment.{id}.zip"


def segment_file_name(id: str | int, epoch: int) -> str:
    return f"{id}_{epoch}.json"
