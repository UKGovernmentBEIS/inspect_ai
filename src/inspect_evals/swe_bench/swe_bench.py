"""SWE-bench: Can Language Models Resolve Real-World GitHub Issues?

Carlos E. Jimenez, John Yang, Alexander Wettig, Shunyu Yao, Kexin Pei, Ofir Press, Karthik Narasimhan
https://arxiv.org/abs/2310.06770
"""

import json
import logging
import os
from logging import getLogger
from pathlib import Path
from textwrap import dedent

from platformdirs import user_cache_dir

from inspect_ai import Task, task
from inspect_ai.dataset import FieldSpec, hf_dataset
from inspect_ai.scorer import Scorer
from inspect_ai.solver import (
    Solver,
    basic_agent,
    system_message,
)
from inspect_ai.tool import bash

from .scorers import swe_bench_scorer

COMPOSE_FILES_DIR = Path(user_cache_dir("inspect_swebench_eval")) / "compose_files /"
DEFAULT_INPUT_PROMPT = "Please solve the following coding issue:\n\n{issue_text}"


logger = logging.getLogger(__name__)


@task
def swe_bench(
    dataset: str = "princeton-nlp/SWE-bench_Verified",
    split: str = "test",
    solver: Solver | None = None,
    max_messages: int = 30,
    input_prompt: str = DEFAULT_INPUT_PROMPT,
    instance_ids: list[str] | None = None,
    scorer: Scorer | list[Scorer] | None = None,
) -> Task:
    """Returns a Task, representing an evaluation on SWE-bench.

    Args.
        dataset : str
            The dataset to use. This should  either be the name of a dataset in the HF hub, or a path to a dataset on disk.
        split : str
            The split of the dataset to load.
        solver : Solver
            The solver to use when creating the task. If None, uses the default solver.
        max_messages : int
            The maximum number of messages to generate for each sample.
        instance_ids : list[str]
            A list of instance_ids to filter the dataset by. If None, all instances are used.
        scorer : Scorer | list[Scorer] | None
            The scorer to use when evaluating swe_bench. If None, uses the default scorer. Mostly commonly, this will be a list of scorers to compare to baselines (see the README for more information).

    """
    getLogger().handlers = []  # Swe-bench adds a global logger, which we disable.

    samples = hf_dataset(
        dataset,
        split=split,
        sample_fields=FieldSpec(
            input="problem_statement",
            id="instance_id",
            metadata=[
                "base_commit",
                "patch",
                "PASS_TO_PASS",
                "FAIL_TO_PASS",
                "test_patch",
                "version",
                "repo",
                "environment_setup_commit",
                "hints_text",
                "created_at",
            ],
        ),
    )

    for sample in samples:
        # Turn the saved strings into list objects
        sample.metadata = sample.metadata or {}
        sample.metadata["PASS_TO_PASS"] = json.loads(sample.metadata["PASS_TO_PASS"])
        sample.metadata["FAIL_TO_PASS"] = json.loads(sample.metadata["FAIL_TO_PASS"])

    if instance_ids is not None:
        samples = samples.filter(lambda x: x.id in instance_ids)

    # Build the images for the samples - can take a long time
    # (import done inline to defer dependendcy binding until usage)
    from .build_images import build_images

    id_to_docker_image = build_images(samples)

    for sample in samples:
        sample.metadata = sample.metadata or {}
        sample.input = input_prompt.format(issue_text=sample.input)
        sample.sandbox = (
            "docker",
            get_compose_file(str(sample.id), id_to_docker_image),
        )
        sample.setup = get_setup_script(
            sample.metadata["repo"],
            sample.metadata["version"],
            sample.metadata["base_commit"],
        )

    return Task(
        name=f"{dataset}_{split}",
        dataset=samples,
        solver=solver or default_solver(),
        scorer=scorer or swe_bench_scorer(),
        max_messages=max_messages,
    )


def default_solver() -> Solver:
    return basic_agent(
        init=system_message(
            "Please solve the coding task below. Once you are done, use your submit tool."
        ),
        tools=[bash(timeout=180)],
    )


def get_setup_script(repo: str, version: str, base_commit: str) -> str:
    """Create a list of bash commands to set up the repository for testing. These are ran at the start of the sample,  clone the repository, and do some extra repository-specific installation steps over and above what is in the environment images."""
    from swebench.harness.constants import (  # type: ignore
        MAP_REPO_TO_INSTALL,
        MAP_REPO_VERSION_TO_SPECS,
    )

    newline = "\n"
    setup_script = dedent(
        f"""#!/bin/bash
        set -euo pipefail -x

        # We clone the repository and set the permissions so the non-root user can run tests
        rm -rf /testbed/*
        git clone -o origin https://github.com/{repo} /testbed/
        chmod -R 777 /testbed/
        cd /testbed/
        git reset --hard {base_commit}
        git remote remove origin
        source /opt/miniconda3/bin/activate
        conda activate testbed
        echo "Current environment: $CONDA_DEFAULT_ENV"

        # We then do any repo-specific install scripts
        {MAP_REPO_TO_INSTALL.get(repo,"")}
        {newline.join(MAP_REPO_VERSION_TO_SPECS[repo][version].get('pre_install',[]))}
        {MAP_REPO_VERSION_TO_SPECS[repo][version].get('install','')}
    """
    )

    return setup_script


def get_compose_file(instance_id: str, ids_to_docker_image: dict[str, str]) -> str:
    image_name = ids_to_docker_image[instance_id]

    COMPOSE_FILES_DIR.mkdir(parents=True, exist_ok=True)
    compose_file_path = f"{COMPOSE_FILES_DIR}/{image_name}.yaml"
    if os.path.exists(compose_file_path):
        return compose_file_path

    # If the image is found, we can now create the compose file.
    image_compose_file = COMPOSE_FILES_DIR / f"{image_name}.yaml"
    with image_compose_file.open(mode="w+") as f:
        f.write(f"""services:
  default:
    image: {image_name}
    command: "sleep infinity"
    working_dir: /testbed
    x-local: true""")

    return str(image_compose_file)
