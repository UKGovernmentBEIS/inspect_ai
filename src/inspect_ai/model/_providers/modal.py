from .openai import (
    OpenAIAPI,
    chat_message_assistant,
)
from .._generate_config import GenerateConfig
from typing_extensions import override
from openai.types.chat import (
    ChatCompletion,
)
from inspect_ai.tool._tool_info import ToolInfo
from inspect_ai._util.constants import DEFAULT_MAX_TOKENS
from .._model_output import (
    ChatCompletionChoice,
    Logprob,
    Logprobs,
    ModelOutput,
    ModelUsage,
    StopReason,
)
import os

MODAL_API_KEY = "MODAL_API_KEY"
WORKSPACE ="WORKSPACE"
APP_NAME = "APP_NAME"
FUNCTION_NAME = "FUNCTION_NAME"

class ModalVllm(OpenAIAPI):
    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
    ) -> None:
        if not api_key:
            api_key = os.environ.get(MODAL_API_KEY, None)
            if not api_key:
                raise RuntimeError(f"{MODAL_API_KEY} environment variable not set")

        workspace = os.environ.get(WORKSPACE, None)
        app_name = os.environ.get(APP_NAME, None)
        function_name = os.environ.get(FUNCTION_NAME, None)
        #https://johanwork--example-vllm-openai-compatible-serve.modal.run

        #client.base_url = f"https://{workspace}--{app_name}-{function_name}.modal.run/v1"
        # TODO REMOVE this
        base_url = "https://johanwork--example-vllm-openai-compatible-serve.modal.run/v1"

        print(base_url)

        super().__init__(base_url=base_url, api_key=api_key, config=config)

    # Together uses a default of 512 so we bump it up
    @override
    def max_tokens(self) -> int:
        return DEFAULT_MAX_TOKENS

    #TODO what should we change here? 
    # Together has a slightly different logprobs structure to OpenAI, so we need to remap it.