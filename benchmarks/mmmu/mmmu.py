import ast
import base64
from io import BytesIO

from datasets import concatenate_datasets, load_dataset
from PIL import Image

from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.dataset._dataset import MemoryDataset
from inspect_ai.model import ChatMessageUser, ContentImage, ContentText, GenerateConfig
from inspect_ai.scorer import choice, model_graded_fact
from inspect_ai.solver import generate, multiple_choice, prompt_template

# Scratch Notes:
# Passing images seems to only work for OpenAI models currently?
# https://inspect.ai-safety-institute.org.uk/datasets.html#image-input
# https://github.com/UKGovernmentBEIS/inspect_ai/blob/52688ccdc88b1dee6abaaa1144e731257b637f6b/src/inspect_ai/_util/content.py#L24
#




# Helper function to convert images to data URLs
def image_to_data_url(image):
    if isinstance(image, Image.Image):
        buffered = BytesIO()
        image.save(buffered, format="PNG")
        image_bytes = buffered.getvalue()
    else:
        with open(image, "rb") as image_file:
            image_bytes = image_file.read()

    encoded_string = base64.b64encode(image_bytes).decode('utf-8')
    mime_type = "image/png"
    return f"data:{mime_type};base64,{encoded_string}"

# Map records to Inspect Sample for multiple-choice questions
def record_to_sample_multiple_choice(record):
    answers_list = ast.literal_eval(record["options"])
    content_list = [ContentText(text=record['question'])]
    # TODO: factor this loop out into separate function?
    for i in range(1, 8):
        image_field = f'image_{i}'
        if record.get(image_field):
            content_list.append(ContentImage(image=image_to_data_url(record[image_field])))

    return Sample(
        input=[ChatMessageUser(content=content_list)],
        choices=answers_list,
        target=record["answer"],
        metadata={"subfield": record["subfield"]},
    )

# Map records to Inspect Sample for open-ended questions
def record_to_sample_open_ended(record):
    content_list = [ContentText(text=record['question'])]
    # TODO: factor this loop out into separate function?
    for i in range(1, 8):
        image_field = f'image_{i}'
        if record.get(image_field):
            content_list.append(ContentImage(image=image_to_data_url(record[image_field])))

    return Sample(
        input=[ChatMessageUser(content=content_list)],
        target=record["answer"],
        metadata={"subfield": record["subfield"]},
    )

MULT_CHOICE_PROMPT = r"""
Answer with the option's letter from the given choices directly.
{prompt}
""".strip()

# Shared task function for multiple-choice questions
def mmmu_task_multiple_choice(dataset):
    multiple_choice_questions_hf = dataset.filter(lambda example: example['question_type'] == 'multiple-choice')
    multiple_choice_questions_inspect = MemoryDataset(
        samples=[record_to_sample_multiple_choice(data) for data in multiple_choice_questions_hf],
        name="MMMU-Multiple-Choice",
        location="MMMU/MMMU"
    )

    return Task(
        dataset=multiple_choice_questions_inspect,
        plan=[prompt_template(MULT_CHOICE_PROMPT), multiple_choice()],
        scorer=choice(),
        config=GenerateConfig(temperature=0)
    )

OPEN_PROMPT = r"""
Answer the question using a single word or phrase.
Unless the question asks for an equation as an answer, don't answer with an equation. Lean towards answering with a number, where relevant.
{prompt}
""".strip()

# Shared task function for open-ended questions
def mmmu_task_open(dataset):
    open_ended_questions_hf = dataset.filter(lambda example: example['question_type'] == 'open')
    open_ended_questions_inspect = MemoryDataset(
        samples=[record_to_sample_open_ended(data) for data in open_ended_questions_hf],
        name="MMMU-Open-Ended",
        location="MMMU/MMMU"
    )

    return Task(
        dataset=open_ended_questions_inspect,
        plan=[prompt_template(OPEN_PROMPT), generate()],
        scorer=model_graded_fact(),
        config=GenerateConfig(temperature=0)
    )

subjects_list = [
        'Accounting', 'Agriculture', 'Architecture_and_Engineering', 'Art', 'Art_Theory',
        'Basic_Medical_Science', 'Biology', 'Chemistry', 'Clinical_Medicine', 'Computer_Science',
        'Design', 'Diagnostics_and_Laboratory_Medicine', 'Economics', 'Electronics', 'Energy_and_Power',
        'Finance', 'Geography', 'History', 'Literature', 'Manage', 'Marketing', 'Materials', 'Math',
        'Mechanical_Engineering', 'Music', 'Pharmacy', 'Physics', 'Psychology', 'Public_Health', 'Sociology'
    ]

@task
def mmmu_multiple_choice():
    path = "MMMU/MMMU"
    datasets = [load_dataset(path, subject, split="dev") for subject in subjects_list]
    combined_dataset = concatenate_datasets(datasets)

    return mmmu_task_multiple_choice(combined_dataset)

@task
def mmmu_open():
    path = "MMMU/MMMU"
    datasets = [load_dataset(path, subject, split="dev") for subject in subjects_list]
    combined_dataset = concatenate_datasets(datasets)

    return mmmu_task_open(combined_dataset)
