import os
import tempfile

import pytest
from test_helpers.utils import skip_if_trio

from inspect_ai import Task, eval
from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.file import filesystem
from inspect_ai.dataset import Sample
from inspect_ai.log._bundle import bundle_log_dir, embed_log_dir
from inspect_ai.scorer import match


@pytest.mark.slow
@skip_if_trio
def test_s3_bundle(mock_s3) -> None:
    # run an eval to generate a log file to this directory
    s3_fs = filesystem("s3://test-bucket/")

    # target directories
    log_dir = "s3://test-bucket/test_s3_bundle/logs"
    output_dir = "s3://test-bucket/test_s3_bundle/view"

    eval(
        tasks=[
            Task(dataset=[Sample(input="Say Hello", target="Hello")], scorer=match())
            for i in range(0, 2)
        ],
        model="mockllm/model",
        log_dir=log_dir,
    )

    # bundle to the output dir
    bundle_log_dir(log_dir, output_dir)

    # ensure files are what we expect
    expected = [
        "index.html",
        "assets",
        "assets/index.js",
        "assets/index.css",
        "logs",
        "logs/listing.json",
    ]

    for exp in expected:
        assert s3_fs.exists(os.path.join(output_dir, exp))


def test_bundle() -> None:
    with tempfile.TemporaryDirectory() as working_dir:
        # run an eval to generate a log file to this directory
        log_dir = os.path.join(working_dir, "logs")
        output_dir = os.path.join(working_dir, "output")

        eval(
            tasks=[
                Task(
                    dataset=[Sample(input="Say Hello", target="Hello")], scorer=match()
                )
                for i in range(0, 2)
            ],
            model="mockllm/model",
            log_dir=log_dir,
        )

        # bundle to the output dir
        bundle_log_dir(log_dir, output_dir)

        # ensure files are what we expect
        expected = [
            "index.html",
            "assets",
            "assets/index.js",
            "assets/index.css",
            "logs",
            "logs/listing.json",
        ]
        for exp in expected:
            abs = os.path.join(output_dir, exp)
            assert os.path.exists(abs)

        # ensure there is a non-listing.json log file present in logs
        non_manifest_logs = [
            f
            for f in os.listdir(os.path.join(output_dir, "logs"))
            if f.endswith(".eval") and f != "logs.eval"
        ]
        assert len(non_manifest_logs) == 2


@skip_if_trio
def test_s3_embed(mock_s3) -> None:
    s3_fs = filesystem("s3://test-bucket/")

    log_dir = "s3://test-bucket/test_s3_embed/logs"

    eval(
        tasks=[
            Task(dataset=[Sample(input="Say Hello", target="Hello")], scorer=match())
            for i in range(0, 2)
        ],
        model="mockllm/model",
        log_dir=log_dir,
    )

    # embed the viewer
    embed_log_dir(log_dir)

    # ensure viewer files are present
    viewer_expected = [
        "viewer/index.html",
        "viewer/assets",
        "viewer/assets/index.js",
        "viewer/assets/index.css",
        "viewer/robots.txt",
    ]
    for exp in viewer_expected:
        assert s3_fs.exists(os.path.join(log_dir, exp))

    # ensure listing.json is in the viewer dir
    assert s3_fs.exists(os.path.join(log_dir, "viewer/listing.json"))

    # ensure no log files were copied into the viewer dir
    viewer_dir = os.path.join(log_dir, "viewer")
    viewer_files = s3_fs.ls(viewer_dir, recursive=True)
    eval_files = [f for f in viewer_files if f.name.endswith(".eval")]
    assert len(eval_files) == 0


def test_embed() -> None:
    with tempfile.TemporaryDirectory() as working_dir:
        log_dir = os.path.join(working_dir, "logs")

        eval(
            tasks=[
                Task(
                    dataset=[Sample(input="Say Hello", target="Hello")], scorer=match()
                )
                for i in range(0, 2)
            ],
            model="mockllm/model",
            log_dir=log_dir,
        )

        # embed the viewer
        embed_log_dir(log_dir)

        # ensure viewer files are present
        viewer_dir = os.path.join(log_dir, "viewer")
        viewer_expected = [
            "index.html",
            "assets",
            "assets/index.js",
            "assets/index.css",
            "robots.txt",
        ]
        for exp in viewer_expected:
            assert os.path.exists(os.path.join(viewer_dir, exp))

        # ensure listing.json is in the viewer dir
        assert os.path.exists(os.path.join(viewer_dir, "listing.json"))

        # ensure no log files were copied into the viewer dir
        viewer_files = []
        for root, _dirs, files in os.walk(viewer_dir):
            viewer_files.extend(files)
        eval_files = [f for f in viewer_files if f.endswith(".eval")]
        assert len(eval_files) == 0

        # ensure index.html has the log_dir context set to ".."
        with open(os.path.join(viewer_dir, "index.html")) as f:
            contents = f.read()
        assert '"log_dir": ".."' in contents


def test_bundle_output_dir_cannot_be_subdir_of_log_dir(tmp_path) -> None:
    log_dir = tmp_path / "logs"
    output_dir = log_dir / "output"

    log_dir.mkdir()

    with pytest.raises(PrerequisiteError, match="cannot be a subdirectory"):
        bundle_log_dir(str(log_dir), str(output_dir))
