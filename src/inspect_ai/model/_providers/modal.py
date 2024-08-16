import os
from .openai import OpenAIAPI
from .._generate_config import GenerateConfig

MODAL_API_KEY = "MODAL_API_KEY"
WORKSPACE ="WORKSPACE"
APP_NAME = "APP_NAME"
FUNCTION_NAME = "FUNCTION_NAME"

class ModalVllm(OpenAIAPI):
    # This integration is based on deploying a vllm endpoint on modal, for reference  https://github.com/modal-labs/modal-examples/blob/main/06_gpu_and_ml/llm-serving/vllm_inference.py
    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        workspace: str | None = None,
        app_name: str | None = None,
        function_name: str | None = None,
        config: GenerateConfig = GenerateConfig(),
    ) -> None:

        api_key= get_env(MODAL_API_KEY,api_key)
        app_name= get_env(APP_NAME,app_name)
        workspace= get_env(WORKSPACE,workspace)
        function_name= get_env(FUNCTION_NAME,function_name)

        base_url = f"https://{workspace}--{app_name}-{function_name}.modal.run/v1"
        super().__init__(model_name=model_name,base_url=base_url, api_key=api_key, config=config)


def get_env(env_variable:str,variable: str | None = None)->str:
    variable = os.environ.get(env_variable, None)
    if not variable:
        raise RuntimeError(f"{WORKSPACE} environment variable not set")
    return variable
