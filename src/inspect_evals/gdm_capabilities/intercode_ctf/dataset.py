import os
import shutil
import zipfile
from glob import glob
from pathlib import Path
from typing import Any

import requests
from platformdirs import user_cache_dir

from inspect_ai.dataset import Dataset, Sample, json_dataset


def read_dataset(shuffle: bool = False, force_download: bool = False) -> Dataset:
    # ensure the data is downloaded
    INTERCODE_DATA_DIR = (
        Path(user_cache_dir("inspect_evals")) / "gdm_intercode_ctf" / "data"
    )
    _ensure_data(INTERCODE_DATA_DIR, force_download)

    # record to sample
    def record_to_sample(record: dict[str, Any]) -> Sample:
        # collect files
        task_id = record["task_id"]
        task_assets = INTERCODE_DATA_DIR / "task_assets" / str(task_id)
        task_files = [
            os.path.relpath(file, INTERCODE_DATA_DIR)
            for file in glob(f"{task_assets}/*")
            if os.path.isfile(file)
        ]
        files = {os.path.basename(file): file for file in task_files}

        # read solution
        with open(f"{task_assets}/solution/README.md") as f:
            solution = f.read()

        # return sample
        return Sample(
            id=task_id,
            input=record["query"],
            target=record["gold"],
            metadata={
                "source": record["source"],
                "tags": record["tags"],
                "solution": solution,
            },
            files=files,
            setup=record.get("setup", None),
        )

    # read dataset. we filter out samples that required internet access, as
    # is also done in the GDM paper (https://arxiv.org/pdf/2403.13793)
    excluded = [
        1,
        9,
        14,
        16,
        20,
        28,
        29,
        35,
        39,
        41,
        42,
        43,
        54,
        57,
        62,
        66,
        73,
        87,
        88,
        89,
        95,
    ]
    return json_dataset(
        json_file=f"{INTERCODE_DATA_DIR}/ic_ctf.json",
        sample_fields=record_to_sample,
        shuffle=shuffle,
    ).filter(lambda sample: sample.id not in excluded)


def _ensure_data(data_dir: Path, force_download: bool) -> None:
    repo_url = "https://github.com/princeton-nlp/intercode"
    zip_path = "intercode_main.zip"
    src_dir = "intercode-master"

    if data_dir.is_dir() and force_download:
        shutil.rmtree(data_dir)

    data_dir.parent.mkdir(parents=True, exist_ok=True)

    if not data_dir.is_dir():
        if not os.path.exists(zip_path):
            _download_latest_repo_zip(repo_url, zip_path)
        _unzip_file(zip_path, ".")
        if os.path.exists(zip_path):
            os.remove(zip_path)

        src = os.path.join(src_dir, "data", "ctf")
        os.rename(src, data_dir)
        if os.path.exists(src_dir):
            shutil.rmtree(src_dir)


def _download_latest_repo_zip(repo_url: str, output_path: str) -> None:
    # Get the repository name from the URL
    repo_name = repo_url.split("github.com/")[1]

    # Construct the URL to the latest release zip file
    zip_url = f"https://github.com/{repo_name}/archive/refs/heads/master.zip"

    # Download the zip file
    print(f"Downloading {zip_url}")
    response = requests.get(zip_url)
    if response.status_code == 200:
        with open(output_path, "wb") as file:
            file.write(response.content)
    else:
        raise RuntimeError(
            f"Failed to download source from {repo_name} - {response.status_code}"
        )


def _unzip_file(zip_path: str, extract_to: str) -> None:
    print(f"Unzipping {zip_path}")
    with zipfile.ZipFile(zip_path, "r") as zip_ref:
        zip_ref.extractall(extract_to)
