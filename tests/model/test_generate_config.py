from inspect_ai.model import GenerateConfig


def test_generate_config_merge_copies_nested_override_values() -> None:
    base = GenerateConfig(max_tokens=64)
    override = GenerateConfig(
        extra_body={"background": True},
        extra_headers={"x-test-header": "value"},
    )

    merged = base.merge(override)
    assert merged.extra_body == {"background": True}
    assert merged.extra_headers == {"x-test-header": "value"}
    assert merged.extra_body is not override.extra_body
    assert merged.extra_headers is not override.extra_headers

    merged.extra_body["background"] = False
    merged.extra_headers["x-test-header"] = "other"

    assert override.extra_body == {"background": True}
    assert override.extra_headers == {"x-test-header": "value"}
