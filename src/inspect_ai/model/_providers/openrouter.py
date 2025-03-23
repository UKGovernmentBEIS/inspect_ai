import json
import os
from typing import Any, TypedDict

from typing_extensions import NotRequired, override

from inspect_ai._util.error import PrerequisiteError
from inspect_ai.model._openai import OpenAIResponseError
from inspect_ai.model._providers.util import model_base_url
from inspect_ai.model._providers.util.util import environment_prerequisite_error

from .._generate_config import GenerateConfig
from .openai import OpenAIAPI

OPENROUTER_API_KEY = "OPENROUTER_API_KEY"


class ErrorResponse(TypedDict):
    code: int
    message: str
    metadata: NotRequired[dict[str, Any]]


class OpenRouterError(Exception):
    def __init__(self, response: ErrorResponse) -> None:
        self.response = response

    @property
    def message(self) -> str:
        return f"Error {self.response['code']} - {self.response['message']}"

    def __str__(self) -> str:
        return (
            self.message + ("\n" + json.dumps(self.response["metadata"], indent=2))
            if "metadata" in self.response
            else ""
        )


class OpenRouterAPI(OpenAIAPI):
    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
        **model_args: Any,
    ) -> None:
        # api_key
        if not api_key:
            api_key = os.environ.get(OPENROUTER_API_KEY, None)
            if not api_key:
                raise environment_prerequisite_error("OpenRouter", OPENROUTER_API_KEY)

        # base_url
        base_url = model_base_url(base_url, "OPENROUTER_BASE_URL")
        base_url = base_url if base_url else "https://openrouter.ai/api/v1"

        # collect known model args that we forward to generate
        def collect_model_arg(name: str) -> Any | None:
            nonlocal model_args
            value = model_args.get(name, None)
            if value is not None:
                model_args.pop(name)
            return value

        # models arg
        self.models = collect_model_arg("models")
        if self.models is not None:
            if not isinstance(self.models, list):
                raise PrerequisiteError("models must be a list of strings")

        # providers arg
        self.provider = collect_model_arg("provider")
        if self.provider is not None:
            if not isinstance(self.provider, dict):
                raise PrerequisiteError("provider must be a dict")

        # transforms arg
        self.transforms = collect_model_arg("transforms")
        if self.transforms is not None:
            if not isinstance(self.transforms, list):
                raise PrerequisiteError("transforms must be a list of strings")

        # call super
        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            config=config,
            **model_args,
        )

    @override
    def on_response(self, response: dict[str, Any]) -> None:
        """Handle documented OpenRouter error conditions.

        https://openrouter.ai/docs/api-reference/errors
        """
        # check if open-router yielded an error (raise explicit
        # OpenAIResponseError for cases where we should retry)
        error: ErrorResponse | None = response.get("error", None)
        if error is not None:
            if error["code"] == 429:
                raise OpenAIResponseError("rate_limit_exceeded", error["message"])
            elif error["code"] in [408, 502]:
                raise OpenAIResponseError("server_error", error["message"])
            else:
                raise OpenRouterError(error)

        # check for an empty response (which they document can occur on
        # startup). for this we'll return a "server_error" which will
        # trigger a retry w/ exponential backoff
        elif response.get("choices", None) is None:
            raise OpenAIResponseError(
                "server_error",
                "Model is warming up, please retry again after waiting for warmup.",
            )

    @override
    def completion_params(self, config: GenerateConfig, tools: bool) -> dict[str, Any]:
        # default params
        params = super().completion_params(config, tools)

        # pass args if specifed
        EXTRA_BODY = "extra_body"
        if self.models or self.provider or self.transforms:
            params[EXTRA_BODY] = params.get(EXTRA_BODY, {})
            if self.models:
                params[EXTRA_BODY]["models"] = self.models
            if self.provider:
                params[EXTRA_BODY]["provider"] = self.provider
            if self.transforms:
                params[EXTRA_BODY]["transforms"] = self.transforms

        return params
