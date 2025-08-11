from datetime import date

from inspect_ai.analysis._prepare.model_data.model_data import read_model_info


def test_read_model_info():
    models = read_model_info()
    # Assert OpenAI is present (check all fields)
    o3_model = models.get("openai/o3")
    assert o3_model.model == "o3"
    assert o3_model.organization == "OpenAI"
    assert o3_model.release_date == date.fromisoformat("2025-04-16")
    assert o3_model.knowledge_cutoff_date == date.fromisoformat("2024-05-31")
    assert o3_model.context_length == 200000
    assert o3_model.reasoning is True

    # Assert Anthropic is present
    assert models.get("anthropic/claude-3-7-sonnet").model == "Claude Sonnet 3.7"

    # Assert name overriding is working
    assert (
        models.get("anthropic/claude-3-5-sonnet-20241022").model == "Claude Sonnet 3.6"
    )

    # Assert GDM is present
    assert models.get("google/gemini-1.5-flash").context_length == 1048576
