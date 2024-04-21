from utils import run_example, skip_if_no_openai


@skip_if_no_openai
def test_examples():
    run_example("security_guide.py", "openai/gpt-4")
    run_example("popularity.py", "openai/gpt-4")
