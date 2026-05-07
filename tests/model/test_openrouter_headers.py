from inspect_ai.model._providers.openrouter import openrouter_default_headers


def test_openrouter_app_attribution_headers() -> None:
    assert openrouter_default_headers() == {
        "HTTP-Referer": "https://inspect.aisi.org.uk",
        "X-OpenRouter-Title": "Inspect AI",
    }


def test_openrouter_default_headers_override_app_attribution() -> None:
    assert openrouter_default_headers(
        {
            "HTTP-Referer": "https://example.com",
            "X-OpenRouter-Title": "Example App",
            "X-Custom": "1",
        }
    ) == {
        "HTTP-Referer": "https://example.com",
        "X-OpenRouter-Title": "Example App",
        "X-Custom": "1",
    }
