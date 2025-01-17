from inspect_ai import Task, task
from inspect_ai.dataset import Sample
from inspect_ai.solver import generate
from inspect_ai.scorer import exact
from inspect_ai.model import get_model

# Load environment variables
import os
from dotenv import load_dotenv

load_dotenv()


@task
def gsm8k_eval():
    # Initialize Claude model
    model = get_model("anthropic/claude-3-sonnet-20240229")

    return Task(
        dataset=[
            Sample(
                input="Janet's ducks lay 16 eggs per day. She eats three for breakfast every morning and sells the rest to her neighbors for $2 per egg. How much money does she make per day?",
                target="26",
            ),
            Sample(
                input="A robe takes 2 blue pieces of cloth and half as many red pieces of cloth to make. If Sally has 3 blue pieces of cloth and 4 red pieces of cloth, how many complete robes can she make?",
                target="1",
            ),
        ],
        solver=[
            generate(model=model),
        ],
        scorer=exact(),
    )


if __name__ == "__main__":
    print("Starting GSM8K evaluation...")
    gsm8k_eval()
