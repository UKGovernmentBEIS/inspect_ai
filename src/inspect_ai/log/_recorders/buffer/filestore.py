import tempfile
from logging import getLogger
from typing import Literal
from zipfile import ZIP_DEFLATED, ZipFile

from pydantic import BaseModel
from typing_extensions import override

from inspect_ai._util.file import basename, dirname, file, filesystem

from ..types import SampleSummary
from .types import AttachmentData, EventData, SampleBuffer, SampleData, Samples

logger = getLogger(__name__)


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


class SampleBufferFilestore(SampleBuffer):
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
        try:
            with file(self._manifest_file(), "r") as f:
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

    def cleanup(self) -> None:
        try:
            self._fs.rm(self._dir, recursive=True)
        except Exception as ex:
            logger.warning(
                f"Error cleaning up sample buffer database at {self._dir}: {ex}"
            )

    @override
    def get_samples(
        self, etag: str | None = None
    ) -> Samples | Literal["NotModified"] | None:
        # get the etag on the filestore
        try:
            info = self._fs.info(self._manifest_file())
            fs_etag = info.etag or f"{info.mtime}{info.size}"
        except FileNotFoundError:
            return None

        # if the etag matches then return not modified
        if etag == fs_etag:
            return "NotModified"

        # read the manifest
        manifest = self.read_manifest()
        if manifest is None:
            return None

        # provide samples + etag from the manifest
        return Samples(samples=[sm.summary for sm in manifest.samples], etag=fs_etag)

    @override
    def get_sample_data(
        self,
        id: str | int,
        epoch: int,
        after_event_id: int | None = None,
        after_attachment_id: int | None = None,
    ) -> SampleData | None:
        # read the manifest
        manifest = self.read_manifest()
        if manifest is None:
            return None

        # find this sample in the manifest
        sample = next(
            (
                sample.summary
                for sample in manifest.samples
                if sample.summary.id == id and sample.summary.epoch == epoch
            ),
            None,
        )
        if sample is None:
            return None

        # determine which segments we need to return in order to
        # satisfy the after_event_id and after_attachment_id
        after_event_id = after_event_id or -1
        after_attachment_id = after_attachment_id or -1
        segments = [
            segment
            for segment in manifest.segments
            if segment.last_events > after_event_id
            or segment.last_attachments > after_attachment_id
        ]

        # collect data from the segments
        sample_data = SampleData(events=[], attachments=[])
        for segment in segments:
            data = self.read_segment_data(segment.id, id, epoch)
            sample_data.events.extend(data.events)
            sample_data.attachments.extend(data.attachments)

        return sample_data

    def _manifest_file(self) -> str:
        return f"{self._dir}{MANIFEST}"


def segment_name(id: int) -> str:
    return f"segment.{id}.zip"


def segment_file_name(id: str | int, epoch: int) -> str:
    return f"{id}_{epoch}.json"
