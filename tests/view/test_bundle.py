import glob
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
    expected_exact = ["index.html", "assets", "logs", "logs/listing.json"]
    for exp in expected_exact:
        assert s3_fs.exists(os.path.join(output_dir, exp))

    # hashed asset filenames
    assets = s3_fs.ls(os.path.join(output_dir, "assets"))
    asset_names = [os.path.basename(a.name) for a in assets]
    assert any(f.endswith(".js") and f.startswith("index-") for f in asset_names)
    assert any(f.endswith(".css") and f.startswith("index-") for f in asset_names)


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
        expected_exact = ["index.html", "assets", "logs", "logs/listing.json"]
        for exp in expected_exact:
            assert os.path.exists(os.path.join(output_dir, exp))

        # hashed asset filenames
        assert glob.glob(os.path.join(output_dir, "assets", "index-*.js"))
        assert glob.glob(os.path.join(output_dir, "assets", "index-*.css"))

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

    # ensure viewer files are present directly in the log dir
    viewer_expected = ["index.html", "assets", "robots.txt", "listing.json"]
    for exp in viewer_expected:
        assert s3_fs.exists(os.path.join(log_dir, exp))

    # hashed asset filenames
    assets = s3_fs.ls(os.path.join(log_dir, "assets"))
    asset_names = [os.path.basename(a.name) for a in assets]
    assert any(f.endswith(".js") and f.startswith("index-") for f in asset_names)
    assert any(f.endswith(".css") and f.startswith("index-") for f in asset_names)

    # ensure old viewer/ subdirectory was not created
    assert not s3_fs.exists(os.path.join(log_dir, "viewer"))


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

        # ensure viewer files are present directly in the log dir
        viewer_expected = ["index.html", "assets", "robots.txt", "listing.json"]
        for exp in viewer_expected:
            assert os.path.exists(os.path.join(log_dir, exp))

        # hashed asset filenames
        assert glob.glob(os.path.join(log_dir, "assets", "index-*.js"))
        assert glob.glob(os.path.join(log_dir, "assets", "index-*.css"))

        # ensure old viewer/ subdirectory was not created
        assert not os.path.exists(os.path.join(log_dir, "viewer"))

        # ensure index.html has the log_dir context set to "."
        with open(os.path.join(log_dir, "index.html")) as f:
            contents = f.read()
        assert '"log_dir": "."' in contents


def test_bundle_output_dir_cannot_be_subdir_of_log_dir(tmp_path) -> None:
    log_dir = tmp_path / "logs"
    output_dir = log_dir / "output"

    log_dir.mkdir()

    with pytest.raises(PrerequisiteError, match="cannot be a subdirectory"):
        bundle_log_dir(str(log_dir), str(output_dir))
