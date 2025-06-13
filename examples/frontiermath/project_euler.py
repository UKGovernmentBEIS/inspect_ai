from inspect_ai import Task, task
from inspect_ai.dataset import Sample

from .agent import frontiermath_agent
from .scorer import verification_code_scorer


@task
def project_euler():
    return Task(
        dataset=[
            Sample(
                input="Find the sum of all multiples of 3 or 5 below 1000.",
                metadata={
                    "answer_type": "Python int",
                    "verification_code": "def verify(a):\n    return a == 233168",
                },
            ),
            Sample(
                input="Find the sum of the even Fibonacci numbers not exceeding four million.",
                metadata={
                    "answer_type": "Python int",
                    "verification_code": "def verify(a):\n    return a == 4613732",
                },
            ),
            Sample(
                input="What is the largest prime factor of 600851475143?",
                metadata={
                    "answer_type": "Python int",
                    "verification_code": "def verify(a):\n    return a == 6857",
                },
            ),
        ],
        solver=[frontiermath_agent()],
        scorer=verification_code_scorer(),
    )
