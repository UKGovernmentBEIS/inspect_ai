from pathlib import Path
from typing import Callable

import yaml

from inspect_ai.dataset import Dataset, MemoryDataset, Sample

SUPPORTED_FILE_NAMES = ["challenge.yaml", "challenge.yml"]


def create_dataset(
    challenges_dir: Path | list[Path] | None,
    filters: Callable[[Sample], bool] | list[Callable[[Sample], bool]] | None,
) -> Dataset:
    # If no path specified, run all the challenges.
    if not challenges_dir:
        challenges_dir = Path(__file__).resolve().parent
    challenges_dir = (
        challenges_dir if isinstance(challenges_dir, list) else [challenges_dir]
    )
    challenges = _get_challenges(challenges_dir)
    dataset = MemoryDataset(samples=_create_samples(challenges))
    if filters:
        dataset = _filter_dataset(dataset, filters)
    return dataset


def _get_challenges(challenges_dirs: list[Path]) -> list[Path]:
    def get_challenges(challenge_dir: Path) -> list[Path]:
        if not isinstance(challenge_dir, Path):
            raise TypeError(
                "Expected challenge_dir to be a Path, "
                f"but got {type(challenge_dir).__name__}."
            )

        challenge_dir = challenge_dir.resolve()
        if not challenge_dir.exists():
            raise FileNotFoundError(f"Could not find: {challenge_dir}")

        challenge_dirs = set()
        for file_name in SUPPORTED_FILE_NAMES:
            for file in challenge_dir.rglob(file_name):
                challenge_dirs.add(file.parent)
        return list(challenge_dirs)

    all_challenge_dirs = set()
    for challenge_dir in challenges_dirs:
        all_challenge_dirs.update(get_challenges(challenge_dir))

    return list(all_challenge_dirs)


def _create_samples(challenges: list[Path]) -> list[Sample]:
    def create_sample_per_variant(challenge: Path) -> list[Sample]:
        challenge_info = _load_challenge_info(challenge)
        id = challenge_info["name"]
        target = challenge_info["flag"]
        challenge_files = _get_files(challenge_info.get("files", {}), challenge)
        sandbox = _get_sandbox(challenge_info, challenge)
        tags = challenge_info.get("tags", [])
        variants = challenge_info["variants"]

        samples = []
        if isinstance(variants, list):
            variants = {
                f"variant_{i}": {"prompt": variant}
                for i, variant in enumerate(variants)
            }
        for name, variant in variants.items():
            variant_files = _get_files(variant.get("files", {}), challenge)
            variant_files.update(challenge_files)

            sample = Sample(
                id=id,
                input=variant["prompt"],
                target=target,
                files=variant_files,
                metadata={
                    "variant": name,
                    "ratings": variant.get("ratings", {}),
                    "tags": tags,
                },
                sandbox=sandbox,
            )
            samples.append(sample)

        return samples

    return [
        sample
        for challenge in challenges
        for sample in create_sample_per_variant(challenge)
    ]


def _filter_dataset(
    dataset: MemoryDataset,
    filters: Callable[[Sample], bool] | list[Callable[[Sample], bool]],
) -> MemoryDataset:
    filters = filters if isinstance(filters, list) else [filters]
    for filter in filters:
        dataset = dataset.filter(filter)
    return dataset


def _load_challenge_info(challenge: Path) -> dict:
    # Each challenge directory must have a config file with the challenge information.
    for file_name in SUPPORTED_FILE_NAMES:
        yaml_path = challenge / file_name
        try:
            return _load_challenge_info_from_yaml(yaml_path)
        except FileNotFoundError:
            continue
    raise FileNotFoundError(
        f"Could not find {' or '.join(SUPPORTED_FILE_NAMES)} in {challenge}."
    )


def _load_challenge_info_from_yaml(yaml_path: Path) -> dict:
    with open(yaml_path, "r") as f:
        yaml_data = f.read()
    raw_data = yaml.safe_load(yaml_data)
    return raw_data


def _get_files(files_dict: dict[str, str], challenge: Path) -> dict[str, str]:
    return {
        key: _make_path_absolute(value, challenge) for key, value in files_dict.items()
    }


def _get_sandbox(challenge_info: dict, challenge: Path) -> str | tuple[str, str | None]:
    if sandbox := challenge_info.get("sandbox"):
        try:
            provider = sandbox["provider"]
            if file := sandbox.get("config_file"):
                config_file = _make_path_absolute(file, challenge)
        except KeyError:
            raise KeyError("Could not find sandbox provider in challenge config.")
        return (provider, config_file)
    return "docker"


def _make_path_absolute(path_or_content: str, challenge: Path) -> str:
    if Path(path_or_content).is_absolute():
        return path_or_content
    if (challenge / path_or_content).is_file():
        return str((challenge / path_or_content).resolve())
    return path_or_content
