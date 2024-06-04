from test_helpers.utils import run_example, skip_if_github_action, skip_if_no_openai


@skip_if_no_openai
@skip_if_github_action
def test_examples():
    run_example("security_guide.py", "openai/gpt-4")
    run_example("popularity.py", "openai/gpt-4")
