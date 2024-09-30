import ast
import os
from pathlib import Path
from typing import Any

from datasets import Dataset, concatenate_datasets, load_dataset  # type: ignore
from platformdirs import user_cache_dir

from inspect_ai.model import Content, ContentImage, ContentText


def save_image(
    record: dict[str, Any], image_number: int, subject_dir: Path, question_number: int
) -> str | None:
    """
    Save an image from the provided record to the specified directory.

    Args:
        record (dict): The record containing image data.
        image_number (int): The index of the image field in the record (e.g., 1 for 'image_1').
        subject_dir (Path): The directory where the image should be saved.
        question_number (str): The question number to use in the image filename.

    Returns:
        str or None: The path to the saved image if the image exists in the record; otherwise, None.
    """
    if record.get(f"image_{image_number}"):
        image_filename = f"question_{question_number}_image_{image_number}.png"
        image_path = subject_dir / image_filename
        if not image_path.exists():
            image = record[f"image_{image_number}"]
            print(f"writing image {image_path.name}")
            image.thumbnail((1024, 1024))
            image.save(image_path, format="PNG")
        return image_path.as_posix()
    else:
        return None


def create_content_and_answers_list(
    record: dict[str, Any],
) -> tuple[list[Content], list[str]]:
    """
    Create a list of content elements and a list of answers from a record.

    Args:
        record (dict): The Inspect record containing question, images, and options.


    Returns:
        tuple: A tuple containing:
            - content_list (list): A list of content elements (text and images).
            - answers_list (list): A list of possible answers (for multiple-choice questions).
    """
    # Split the "id" field into components
    components = record["id"].split("_")

    # The subject is everything except the first and last components
    subject = "_".join(components[1:-1])  # Extract the full subject name
    question_number = components[-1]  # Extract the question number

    IMAGE_BASE_DIR = Path(user_cache_dir("inspect_evals")) / "mmmu_images"
    subject_dir = IMAGE_BASE_DIR / subject
    os.makedirs(subject_dir, exist_ok=True)

    content_list: list[Content] = [ContentText(text=record["question"])]
    answers_list: list[str] = []

    for i in range(1, 8):
        image_path = save_image(record, i, subject_dir, question_number)
        if image_path:
            content_list.append(ContentImage(image=image_path))

    # Parse the multiple-choice options
    # If empty, answer is open-ended, answers_list not used for open-ended questions
    options = ast.literal_eval(record["options"])
    answers_list = options

    return content_list, answers_list


def load_and_concatenate_datasets(
    subjects_list: list[str], path: str = "MMMU/MMMU", split: str = "validation"
) -> Dataset:
    """
    Load Huggingface datasets for each subject in the list and concatenate them into a single dataset.

    Args:
        subjects_list (list): A list of subjects to load datasets for.
        path (str, optional): The base path of the datasets. Defaults to "MMMU/MMMU".
        split (str, optional): The dataset split to load (e.g., "dev", "validation"). Defaults to "validation".

    Returns:
        Dataset: A concatenated Huggingface dataset containing all subjects.
    """
    datasets = [load_dataset(path, subject, split=split) for subject in subjects_list]
    combined_dataset = concatenate_datasets(datasets)
    return combined_dataset
