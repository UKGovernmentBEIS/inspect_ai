
from typing import Dict, List
from f1 import f1_scorer
from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.dataset._sources.hf import hf_dataset
from inspect_ai.model._generate_config import GenerateConfig


@task
def quac():
    dataset = hf_dataset(
        path="allenai/quac",
        sample_fields=record_to_sample,
        split="train",
        shuffle=True,
        trust=True
    )
    dataset = dataset[:10]
    
    return Task(
        dataset=dataset,
        scorer=f1_scorer(),
        config=GenerateConfig(temperature=0.5),
    )
    
def record_to_sample(record) -> Sample:
    return Sample(
        input=format_input(record),
        target=format_target(record),
        id=record["dialogue_id"],
    )
    
def format_input(doc) -> str:
    wikipedia_title = f"""wikipedia_page_title: {doc["wikipedia_page_title"]}"""
    background = f"""background: {doc["background"]}"""
    section_title = f"""section_title: {doc["section_title"]}"""
    context = f"""context: {doc["context"]}"""
    
    questions = doc["questions"]
    previous_questions_answers = []
    
    # We just append everything but the last question for now
    for idx, question in enumerate(questions[:-1]):
        answer = doc["answers"]["texts"][idx][0]
        question = f"""question: {question}"""
        answer = f"""answer: {answer}"""
        previous_questions_answers.append(question)
        previous_questions_answers.append(answer)
        
    # We use the last question as current question for now 
    current_question = questions[-1]
    
    input_str = "\n".join([wikipedia_title, background, section_title, context, "\n".join(previous_questions_answers), current_question, """answer:"""])
    return input_str

def format_target(doc: Dict) -> List[str]:
    target = " | ".join(doc["answers"]["texts"][-1])
    return target
