from inspect_ai._util.error import pip_dependency_error
from inspect_ai._util.version import verify_required_version

from .._model import ModelAPI
from .._registry import modelapi

# Defer importing model api classes until they are actually used
# (this allows the package to load without the optional deps)
# Note that some api providers (e.g. Cloudflare, AzureAI) don't
# strictly require this treatment but we do it anyway for uniformity,


@modelapi(name="openai")
def openai() -> type[ModelAPI]:
    # validate
    validate_openai_client("OpenAI API")

    # in the clear
    from .openai import OpenAIAPI

    return OpenAIAPI


@modelapi(name="anthropic")
def anthropic() -> type[ModelAPI]:
    FEATURE = "Anthropic API"
    PACKAGE = "anthropic"
    MIN_VERSION = "0.29.0"

    # verify we have the package
    try:
        import anthropic  # noqa: F401
    except ImportError:
        raise pip_dependency_error(FEATURE, [PACKAGE])

    # verify version
    verify_required_version(FEATURE, PACKAGE, MIN_VERSION)

    # in the clear
    from .anthropic import AnthropicAPI

    return AnthropicAPI


@modelapi(name="google")
def google() -> type[ModelAPI]:
    FEATURE = "Google API"
    PACKAGE = "google-generativeai"
    MIN_VERSION = "0.4.0"

    # verify we have the package
    try:
        import google.generativeai  # type: ignore  # noqa: F401
    except ImportError:
        raise pip_dependency_error(FEATURE, [PACKAGE])

    # verify version
    verify_required_version(FEATURE, PACKAGE, MIN_VERSION)

    # in the clear
    from .google import GoogleAPI

    return GoogleAPI


@modelapi(name="hf")
def hf() -> type[ModelAPI]:
    try:
        from .hf import HuggingFaceAPI
    except ImportError:
        raise pip_dependency_error(
            "Hugging Face Models", ["torch", "transformers", "accelerate"]
        )

    return HuggingFaceAPI


@modelapi(name="cf")
def cf() -> type[ModelAPI]:
    from .cloudflare import CloudFlareAPI

    return CloudFlareAPI


@modelapi(name="mistral")
def mistral() -> type[ModelAPI]:
    FEATURE = "Mistral API"
    PACKAGE = "mistralai"
    MIN_VERSION = "0.1.3"

    # verify we have the package
    try:
        import mistralai  # noqa: F401
    except ImportError:
        raise pip_dependency_error(FEATURE, [PACKAGE])

    # verify version
    verify_required_version(FEATURE, PACKAGE, MIN_VERSION)

    # in the clear
    from .mistral import MistralAPI

    return MistralAPI


@modelapi(name="together")
def together() -> type[ModelAPI]:
    # validate
    validate_openai_client("TogetherAI API")

    # in the clear
    from .together import TogetherAIAPI

    return TogetherAIAPI


@modelapi(name="ollama")
def ollama() -> type[ModelAPI]:
    # validate
    validate_openai_client("Ollama API")

    # in the clear
    from .ollama import OllamaAPI

    return OllamaAPI


@modelapi(name="azureai")
def azureai() -> type[ModelAPI]:
    from .azureai import AzureAIAPI

    return AzureAIAPI


@modelapi(name="bedrock")
def bedrock() -> type[ModelAPI]:
    from .bedrock import BedrockAPI

    return BedrockAPI


@modelapi(name="mockllm")
def mockllm() -> type[ModelAPI]:
    from .mockllm import MockLLM

    return MockLLM


def validate_openai_client(feature: str) -> None:
    FEATURE = feature
    PACKAGE = "openai"
    MIN_VERSION = "1.11.0"

    # verify we have the package
    try:
        import openai  # noqa: F401
    except ImportError:
        raise pip_dependency_error(FEATURE, [PACKAGE])

    # verify version
    verify_required_version(FEATURE, PACKAGE, MIN_VERSION)
