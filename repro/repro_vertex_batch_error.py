

from inspect_ai import eval

eval(
    "repro/test_task.py",
    model="google/vertex/gemini-2.0-flash",
    batch=True,
)

