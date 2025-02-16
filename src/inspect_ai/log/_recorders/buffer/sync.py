from .database import SampleBufferDatabase
from .filestore import (
    Manifest,
    SampleBufferFilestore,
    SampleManifest,
    Segment,
    SegmentFile,
)
from .types import SampleData, Samples


def sync_to_filestore(
    db: SampleBufferDatabase, filestore: SampleBufferFilestore
) -> None:
    # read existing manifest (create an empty one if there is none)
    manifest = filestore.read_manifest() or Manifest()

    # prepare a list of buffered samples from the db
    samples = db.get_samples()
    if samples is None:
        return
    assert isinstance(samples, Samples)

    # at the end of the sync, the manifest should contain only the samples
    # in the db -- create a new list of sample manifests propagating the
    # segment lists from the existing sample manifests
    sample_manifests: list[SampleManifest] = []
    for sample in samples.samples:
        # lookup sample segments in the existing manifest
        segments: list[int] = next(
            (
                s.segments
                for s in manifest.samples
                if s.summary.id == sample.id and s.summary.epoch == sample.epoch
            ),
            [],
        )
        # add to manifests
        sample_manifests.append(SampleManifest(summary=sample, segments=segments))

    # draft of new manifest has the new sample list and the existing segments
    manifest.samples = sample_manifests

    # determine what segment data we already have so we can limit
    # sample queries accordingly
    if len(manifest.segments) > 0:
        last_segment = manifest.segments[-1]
        last_segment_id = last_segment.id
    else:
        last_segment_id = 0

    # work through samples and create segment files for those that need it
    # (update the manifest with the segment id). track the largest event
    # and attachment ids we've seen
    segment_id = last_segment_id + 1
    last_event_id = 0
    last_attachment_id = 0
    segment_files: list[SegmentFile] = []
    for manifest_sample in manifest.samples:
        # get last ids we've seen for this sample
        sample_last_segment_id = (
            manifest_sample.segments[-1] if manifest_sample.segments else None
        )
        sample_last_segment = next(
            (
                segment
                for segment in manifest.segments
                if segment.id == sample_last_segment_id
            ),
            None,
        )
        if sample_last_segment is not None:
            after_event_id = sample_last_segment.last_event_id
            after_attachment_id = sample_last_segment.last_attachment_id
        else:
            after_event_id, after_attachment_id = (0, 0)

        # get sample data
        sample_data = db.get_sample_data(
            id=manifest_sample.summary.id,
            epoch=manifest_sample.summary.epoch,
            after_event_id=after_event_id,
            after_attachment_id=after_attachment_id,
        )
        # if we got sample data....
        if sample_data is not None and (
            len(sample_data.events) > 0 or len(sample_data.attachments) > 0
        ):
            # add to segment file
            segment_files.append(
                SegmentFile(
                    id=manifest_sample.summary.id,
                    epoch=manifest_sample.summary.epoch,
                    data=sample_data,
                )
            )
            # update manifest
            manifest_sample.segments.append(segment_id)

            # update maximums
            last_event_id, last_attachment_id = maximum_ids(
                last_event_id, last_attachment_id, sample_data
            )

    # write the segment file and update the manifest
    if len(segment_files) > 0:
        filestore.write_segment(segment_id, segment_files)
        manifest.segments.append(
            Segment(
                id=segment_id,
                last_event_id=last_event_id,
                last_attachment_id=last_attachment_id,
            )
        )

    # write the manifest (do this even if we had no segments to pickup adds/deletes)
    filestore.write_manifest(manifest)


def maximum_ids(
    event_id: int, attachment_id: int, sample_data: SampleData
) -> tuple[int, int]:
    if sample_data.events:
        event_id = max(event_id, sample_data.events[-1].id)
    if sample_data.attachments:
        attachment_id = max(attachment_id, sample_data.attachments[-1].id)
    return event_id, attachment_id
