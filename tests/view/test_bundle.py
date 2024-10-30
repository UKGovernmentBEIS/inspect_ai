import os
import tempfile

import pytest

from inspect_ai import Task, eval
from inspect_ai._util.file import filesystem
from inspect_ai.dataset import Sample
from inspect_ai.log._bundle import bundle_log_dir
from inspect_ai.scorer import match


@pytest.mark.slow
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
        "logs/logs.json",
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
            "logs/logs.json",
        ]
        for exp in expected:
            abs = os.path.join(output_dir, exp)
            assert os.path.exists(abs)

        # ensure there is a non-logs.json log file present in logs
        non_manifest_logs = [
            f
            for f in os.listdir(os.path.join(output_dir, "logs"))
            if f.endswith(".json") and f != "logs.json"
        ]
        assert len(non_manifest_logs) == 2
