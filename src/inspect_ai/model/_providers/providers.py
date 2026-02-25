from inspect_ai._util.error import pip_dependency_error
from inspect_ai._util.version import verify_required_version

from .._model import ModelAPI
from .._registry import modelapi

# Defer importing model api classes until they are actually used
# (this allows the package to load without the optional deps)
# Note that some api providers (e.g. Cloudflare, AzureAI) don't
# strictly require this treatment but we do it anyway for uniformity,


@modelapi(name="groq")
def groq() -> type[ModelAPI]:
    FEATURE = "Groq API"
    PACKAGE = "groq"
    MIN_VERSION = "0.28.0"

    # verify we have the package
    try:
        import groq  # noqa: F401
    except ImportError:
        raise pip_dependency_error(FEATURE, [PACKAGE])

    # verify version
    verify_required_version(FEATURE, PACKAGE, MIN_VERSION)

    # in the clear
    from .groq import GroqAPI

    return GroqAPI


@modelapi(name="openai")
def openai() -> type[ModelAPI]:
    # validate
    validate_openai_client("OpenAI API")

    # in the clear
    from .openai import OpenAIAPI

    return OpenAIAPI


@modelapi(name="openai-api")
def openai_api() -> type[ModelAPI]:
    # validate
    validate_openai_client("OpenAI Compatible API")

    # in the clear
    from .openai_compatible import OpenAICompatibleAPI

    return OpenAICompatibleAPI


@modelapi(name="anthropic")
def anthropic() -> type[ModelAPI]:
    # validate
    validate_anthropic_client("Anthropic API")

    # in the clear
    from .anthropic import AnthropicAPI

    return AnthropicAPI


@modelapi(name="google")
def google() -> type[ModelAPI]:
    # validate
    validate_google_client("Google API")

    # in the clear
    from .google import GoogleGenAIAPI

    return GoogleGenAIAPI


@modelapi(name="hf")
def hf() -> type[ModelAPI]:
    try:
        from .hf import HuggingFaceAPI
    except ImportError:
        raise pip_dependency_error(
            "Hugging Face Models", ["torch", "transformers", "accelerate"]
        )

    return HuggingFaceAPI


@modelapi(name="vllm")
def vllm() -> type[ModelAPI]:
    # Only validate OpenAI compatibility (needed for the API interface)
    validate_openai_client("vLLM API")

    # Import VLLMAPI without checking for vllm package yet
    # The actual vllm dependency will only be checked if needed to start a server
    from .vllm import VLLMAPI

    return VLLMAPI


@modelapi(name="cf")
def cf() -> type[ModelAPI]:
    from .cloudflare import CloudFlareAPI

    return CloudFlareAPI


@modelapi(name="mistral")
def mistral() -> type[ModelAPI]:
    FEATURE = "Mistral API"
    PACKAGE = "mistralai"
    MIN_VERSION = "1.9.11"

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


@modelapi(name="grok")
def grok() -> type[ModelAPI]:
    FEATURE = "Grok API"
    PACKAGE = "xai_sdk"
    MIN_VERSION = "1.4.0"

    # verify we have the package
    try:
        import xai_sdk  # type: ignore[import-untyped] # noqa: F401
    except ImportError:
        raise pip_dependency_error(FEATURE, [PACKAGE])

    # verify version
    verify_required_version(FEATURE, PACKAGE, MIN_VERSION)

    # in the clear
    from .grok import GrokAPI

    return GrokAPI


@modelapi(name="together")
def together() -> type[ModelAPI]:
    # validate
    validate_openai_client("TogetherAI API")

    # in the clear
    from .together import TogetherAIAPI

    return TogetherAIAPI


@modelapi(name="fireworks")
def fireworks() -> type[ModelAPI]:
    validate_openai_client("FireworksAI API")
    from .fireworks import FireworksAIAPI

    return FireworksAIAPI


@modelapi(name="sambanova")
def sambanova() -> type[ModelAPI]:
    validate_openai_client("SambaNova API")
    from .sambanova import SambaNovaAPI

    return SambaNovaAPI


@modelapi(name="ollama")
def ollama() -> type[ModelAPI]:
    # validate
    validate_openai_client("Ollama API")

    # in the clear
    from .ollama import OllamaAPI

    return OllamaAPI


@modelapi(name="openrouter")
def openrouter() -> type[ModelAPI]:
    # validate
    validate_openai_client("OpenRouter API")

    # in the clear
    from .openrouter import OpenRouterAPI

    return OpenRouterAPI


@modelapi(name="perplexity")
def perplexity() -> type[ModelAPI]:
    # validate
    validate_openai_client("Perplexity API")

    # in the clear
    from .perplexity import PerplexityAPI

    return PerplexityAPI


@modelapi(name="llama-cpp-python")
def llama_cpp_python() -> type[ModelAPI]:
    # validate
    validate_openai_client("llama-cpp-python API")

    # in the clear
    from .llama_cpp_python import LlamaCppPythonAPI

    return LlamaCppPythonAPI


@modelapi(name="azureai")
def azureai() -> type[ModelAPI]:
    FEATURE = "AzureAI API"
    PACKAGE = "azure-ai-inference"

    # verify we have the package
    try:
        import azure.ai.inference  # noqa: F401
    except ImportError:
        raise pip_dependency_error(FEATURE, [PACKAGE])

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


@modelapi(name="sagemaker")
def sagemaker() -> type[ModelAPI]:
    from .sagemaker import SagemakerAPI

    return SagemakerAPI


@modelapi(name="sglang")
def sglang() -> type[ModelAPI]:
    # Only validate OpenAI compatibility (needed for the API interface)
    validate_openai_client("SGLang API")

    # Import SGLangAPI without checking for sglang package yet
    # The actual sglang dependency will only be checked if needed to start a server
    from .sglang import SGLangAPI

    return SGLangAPI


@modelapi(name="transformer_lens")
def transformer_lens() -> type[ModelAPI]:
    FEATURE = "TransformerLens API"
    PACKAGE = "transformer_lens"

    # verify we have the package
    try:
        import transformer_lens  # type: ignore # noqa: F401
    except ImportError:
        raise pip_dependency_error(FEATURE, [PACKAGE])

    # in the clear
    from .transformer_lens import TransformerLensAPI

    return TransformerLensAPI


@modelapi(name="nnterp")
def nnterp() -> type[ModelAPI]:
    FEATURE = "NNterp API"
    PACKAGE = "nnterp"

    # verify we have the package
    try:
        import nnterp  # type: ignore # noqa: F401
    except ImportError:
        raise pip_dependency_error(FEATURE, [PACKAGE])

    # in the clear
    from .nnterp import NNterpAPI

    return NNterpAPI


@modelapi(name="none")
def none() -> type[ModelAPI]:
    from .none import NoModel

    return NoModel


@modelapi(name="hf-inference-providers")
def hf_inference_providers() -> type[ModelAPI]:
    # validate
    validate_openai_client("HF Inference Providers API")

    # in the clear
    from .hf_inference_providers import HFInferenceProvidersAPI

    return HFInferenceProvidersAPI


def validate_openai_client(feature: str) -> None:
    FEATURE = feature
    PACKAGE = "openai"
    MIN_VERSION = "2.17.0"

    # verify we have the package
    try:
        import openai  # noqa: F401
    except ImportError:
        raise pip_dependency_error(FEATURE, [PACKAGE])

    # verify version
    verify_required_version(FEATURE, PACKAGE, MIN_VERSION)


def validate_anthropic_client(feature: str) -> None:
    PACKAGE = "anthropic"
    MIN_VERSION = "0.80.0"

    # verify we have the package
    try:
        import anthropic  # noqa: F401
    except ImportError:
        raise pip_dependency_error(feature, [PACKAGE])

    # verify version
    verify_required_version(feature, PACKAGE, MIN_VERSION)


def validate_google_client(feature: str) -> None:
    PACKAGE = "google-genai"
    MIN_VERSION = "1.56.0"

    # verify we have the package
    try:
        import google.genai  # type: ignore  # noqa: F401
    except ImportError:
        raise pip_dependency_error(feature, [PACKAGE])

    # verify version
    verify_required_version(feature, PACKAGE, MIN_VERSION)
