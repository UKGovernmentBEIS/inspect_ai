from .model_router import VLLMRouter
from .._registry import modelapi


@modelapi(name="vllm_router")
def vllm_router():
    return VLLMRouter
