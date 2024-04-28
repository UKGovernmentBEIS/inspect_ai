"""
Measuring Massive Multitask Language Understanding

Dan Hendrycks, Collin Burns, Steven Basart, Andy Zou,
Mantas Mazeika, Dawn Song, Jacob Steinhardt
https://arxiv.org/abs/2009.03300

Based on: https://github.com/openai/simple-evals/blob/main/mmlu_eval.py

# eval all subjects w/ 500 randomly selected samples
inspect eval mmlu.py@mmlu --limit 500

# add chain of thought
inspect eval mmlu.py@mmlu --limit 500 -T cot=true

# eval selected subjects
inspect eval mmlu.py@mmlu -T subjects=anatomy,astronomy

# eval single subjects
inspect eval mmlu.py@mmlu_anatomy
inspect eval mmlu.py@mmlu_astronomy
"""

from inspect_ai import Task, task
from inspect_ai.dataset import Sample, csv_dataset
from inspect_ai.model import GenerateConfig
from inspect_ai.scorer import answer
from inspect_ai.solver import multiple_choice


# map records to inspect sample
def record_to_sample(record):
    return Sample(
        input=record["Question"],
        choices=[
            str(record["A"]),
            str(record["B"]),
            str(record["C"]),
            str(record["D"]),
        ],
        target=record["Answer"],
        metadata={"subject": record["Subject"]},
    )


# read dataset globally so it can be shared by all of the tasks
# (shuffle so that --limit draws from multiple subjects)
dataset = csv_dataset(
    csv_file="datasets/mmlu.csv",
    sample_fields=record_to_sample,
    shuffle=True,
)


@task
def mmlu(subjects=[], cot=False):
    # filter dataset if requested
    subjects = subjects if isinstance(subjects, list) else [subjects]
    if len(subjects) > 0:
        task_dataset = dataset.filter(
            name=f"{dataset.name}-{'-'.join(subjects)}",
            predicate=lambda sample: sample.metadata["subject"] in subjects,
        )
    else:
        task_dataset = dataset

    # return task
    return Task(
        dataset=task_dataset,
        plan=multiple_choice(cot=cot),
        scorer=answer("letter"),
        config=GenerateConfig(temperature=0.5),
    )


@task
def mmlu_abstract_algebra(cot=False):
    return mmlu("abstract_algebra", cot)


@task
def mmlu_anatomy(cot=False):
    return mmlu("anatomy", cot)


@task
def mmlu_astronomy(cot=False):
    return mmlu("astronomy", cot)


@task
def mmlu_business_ethics(cot=False):
    return mmlu("business_ethics", cot)


@task
def mmlu_clinical_knowledge(cot=False):
    return mmlu("clinical_knowledge", cot)


@task
def mmlu_college_biology(cot=False):
    return mmlu("college_biology", cot)


@task
def mmlu_college_chemistry(cot=False):
    return mmlu("college_chemistry", cot)


@task
def mmlu_college_computer_science(cot=False):
    return mmlu("college_computer_science", cot)


@task
def mmlu_college_mathematics(cot=False):
    return mmlu("college_mathematics", cot)


@task
def mmlu_college_medicine(cot=False):
    return mmlu("college_medicine", cot)


@task
def mmlu_college_physics(cot=False):
    return mmlu("college_physics", cot)


@task
def mmlu_computer_security(cot=False):
    return mmlu("computer_security", cot)


@task
def mmlu_conceptual_physics(cot=False):
    return mmlu("conceptual_physics", cot)


@task
def mmlu_electrical_engineering(cot=False):
    return mmlu("electrical_engineering", cot)


@task
def mmlu_elementary_mathematics(cot=False):
    return mmlu("elementary_mathematics", cot)


@task
def mmlu_formal_logic(cot=False):
    return mmlu("formal_logic", cot)


@task
def mmlu_global_facts(cot=False):
    return mmlu("global_facts", cot)


@task
def mmlu_high_school_biology(cot=False):
    return mmlu("high_school_biology", cot)


@task
def mmlu_high_school_chemistry(cot=False):
    return mmlu("high_school_chemistry", cot)


@task
def mmlu_high_school_computer_science(cot=False):
    return mmlu("high_school_computer_science", cot)


@task
def mmlu_high_school_european_history(cot=False):
    return mmlu("high_school_european_history", cot)


@task
def mmlu_high_school_geography(cot=False):
    return mmlu("high_school_geography", cot)


@task
def mmlu_high_school_government_and_politics(cot=False):
    return mmlu("high_school_government_and_politics", cot)


@task
def mmlu_high_school_macroeconomics(cot=False):
    return mmlu("high_school_macroeconomics", cot)


@task
def mmlu_high_school_mathematics(cot=False):
    return mmlu("high_school_mathematics", cot)


@task
def mmlu_high_school_microeconomics(cot=False):
    return mmlu("high_school_microeconomics", cot)


@task
def mmlu_high_school_physics(cot=False):
    return mmlu("high_school_physics", cot)


@task
def mmlu_high_school_psychology(cot=False):
    return mmlu("high_school_psychology", cot)


@task
def mmlu_high_school_statistics(cot=False):
    return mmlu("high_school_statistics", cot)


@task
def mmlu_high_school_us_history(cot=False):
    return mmlu("high_school_us_history", cot)


@task
def mmlu_high_school_world_history(cot=False):
    return mmlu("high_school_world_history", cot)


@task
def mmlu_human_aging(cot=False):
    return mmlu("human_aging", cot)


@task
def mmlu_human_sexuality(cot=False):
    return mmlu("human_sexuality", cot)


@task
def mmlu_international_law(cot=False):
    return mmlu("international_law", cot)


@task
def mmlu_jurisprudence(cot=False):
    return mmlu("jurisprudence", cot)


@task
def mmlu_logical_fallacies(cot=False):
    return mmlu("logical_fallacies", cot)


@task
def mmlu_machine_learning(cot=False):
    return mmlu("machine_learning", cot)


@task
def mmlu_management(cot=False):
    return mmlu("management", cot)


@task
def mmlu_marketing(cot=False):
    return mmlu("marketing", cot)


@task
def mmlu_miscellaneous(cot=False):
    return mmlu("miscellaneous", cot)


@task
def mmlu_moral_disputes(cot=False):
    return mmlu("moral_disputes", cot)


@task
def mmlu_moral_scenarios(cot=False):
    return mmlu("moral_scenarios", cot)


@task
def mmlu_nutrition(cot=False):
    return mmlu("nutrition", cot)


@task
def mmlu_philosophy(cot=False):
    return mmlu("philosophy", cot)


@task
def mmlu_prehistory(cot=False):
    return mmlu("prehistory", cot)


@task
def mmlu_professional_accounting(cot=False):
    return mmlu("professional_accounting", cot)


@task
def mmlu_professional_law(cot=False):
    return mmlu("professional_law", cot)


@task
def mmlu_professional_medicine(cot=False):
    return mmlu("professional_medicine", cot)


@task
def mmlu_professional_psychology(cot=False):
    return mmlu("professional_psychology", cot)


@task
def mmlu_public_relations(cot=False):
    return mmlu("public_relations", cot)


@task
def mmlu_security_studies(cot=False):
    return mmlu("security_studies", cot)


@task
def mmlu_sociology(cot=False):
    return mmlu("sociology", cot)


@task
def mmlu_us_foreign_policy(cot=False):
    return mmlu("us_foreign_policy", cot)


@task
def mmlu_virology(cot=False):
    return mmlu("virology", cot)


@task
def mmlu_world_religions(cot=False):
    return mmlu("world_religions", cot)
