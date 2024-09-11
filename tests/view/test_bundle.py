import os
import tempfile

from inspect_ai import Task, eval
from inspect_ai._view.bundle import bundle
from inspect_ai.dataset import Sample
from inspect_ai.scorer import match


def test_bundle() -> None:
    # run eval with a solver that fails 20% of the time
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
        bundle(log_dir, output_dir)

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
