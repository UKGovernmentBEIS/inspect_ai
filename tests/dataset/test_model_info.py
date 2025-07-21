from inspect_ai.analysis.beta._dataframe.model_data.model_data import read_model_info


def test_read_model_info():
    models = read_model_info()
    assert models.get("claude-3-7-sonnet").model_short_name == "Claude 3.7 Sonnet"
