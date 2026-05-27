import json
from logging import getLogger
from typing import Any

from openai.types.chat import ChatCompletion
from typing_extensions import NotRequired, TypedDict, override

from inspect_ai._util.error import PrerequisiteError
from inspect_ai.model._model import RetryDecision
from inspect_ai.model._openai import OpenAIResponseError

from .._generate_config import GenerateConfig
from .openai_compatible import OpenAICompatibleAPI

ORCAROUTER_API_KEY = "ORCAROUTER_API_KEY"

logger = getLogger(__name__)


class ErrorResponse(TypedDict):
    code: int
    message: str
    metadata: NotRequired[dict[str, Any]]


class OrcaRouterError(Exception):
    def __init__(self, response: ErrorResponse) -> None:
        self.response = response

    @property
    def message(self) -> str:
        return f"Error {self.response['code']} - {self.response['message']}"

    def __str__(self) -> str:
        return (
            self.message + ("\n" + json.dumps(self.response["metadata"], indent=2))
            if "metadata" in self.response
            else self.message
        )


class OrcaRouterAPI(OpenAICompatibleAPI):
    """OpenAI-compatible client for the OrcaRouter inference router.

    OrcaRouter (https://www.orcarouter.ai) is a multi-provider LLM router
    exposed through an OpenAI-compatible API. Requests are forwarded by
    OrcaRouter to the selected upstream using that upstream's native protocol;
    Inspect's standard `reasoning_effort` / `reasoning_tokens` are forwarded as
    top-level OpenAI-compatible fields and so work for upstreams that accept
    that shape (OpenAI o-series / gpt-5 / Gemini / Grok / Qwen / Kimi reasoning
    families). For Anthropic models, pass the Anthropic-native `thinking`
    block via `GenerateConfig.extra_body` instead.

    Custom model args (`-M`):
      * `models`     — list[str], fallback model ids (sent via `extra_body.models`
                       with `route="fallback"`).
      * `referer`    — override the `HTTP-Referer` attribution header.
      * `app_title`  — override the `X-Title` attribution header.
    """

    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
        emulate_tools: bool = False,
        **model_args: Any,
    ) -> None:
        def collect_model_arg(name: str) -> Any | None:
            nonlocal model_args
            value = model_args.get(name, None)
            if value is not None:
                model_args.pop(name)
            return value

        self.models = collect_model_arg("models")
        if self.models is not None and not isinstance(self.models, list):
            raise PrerequisiteError("models must be a list of strings")

        self.referer = collect_model_arg("referer") or "https://inspect.aisi.org.uk/"
        self.app_title = collect_model_arg("app_title") or "Inspect AI"

        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            config=config,
            service="OrcaRouter",
            service_base_url="https://api.orcarouter.ai/v1",
            emulate_tools=emulate_tools,
            **model_args,
        )

    @override
    def should_retry(self, ex: BaseException) -> bool | RetryDecision:
        decision = super().should_retry(ex)
        if isinstance(decision, RetryDecision):
            if decision.retry:
                return decision
        elif decision:
            return RetryDecision.transient()
        if isinstance(ex, json.JSONDecodeError):
            return RetryDecision.transient()
        return RetryDecision.no()

    @override
    def on_response(self, response: dict[str, Any]) -> None:
        """Handle OrcaRouter-shaped error bodies returned with HTTP 200."""
        error: ErrorResponse | None = response.get("error", None)
        if error is not None:
            if error["code"] == 429:
                raise OpenAIResponseError("rate_limit_exceeded", error["message"])
            elif error["code"] in [408, 500, 502, 504]:
                raise OpenAIResponseError("server_error", error["message"])
            else:
                raise OrcaRouterError(error)

        if response.get("choices", None) is None:
            raise OpenAIResponseError(
                "server_error",
                "Empty response from OrcaRouter; retry after upstream warmup.",
            )

    @override
    async def _generate_completion(
        self, request: dict[str, Any], config: GenerateConfig
    ) -> ChatCompletion:
        # inject attribution headers so the OrcaRouter console can attribute
        # traffic to Inspect. Mirrors the convention used by OpenAI-compatible
        # meta-routers (HTTP-Referer + X-Title). User-supplied values via
        # `referer` / `app_title` model args, or config.extra_headers, win.
        extra_headers = request.get("extra_headers") or {}
        extra_headers.setdefault("HTTP-Referer", self.referer)
        extra_headers.setdefault("X-Title", self.app_title)
        request["extra_headers"] = extra_headers
        return await super()._generate_completion(request, config)

    @override
    def completion_params(self, config: GenerateConfig, tools: bool) -> dict[str, Any]:
        params = super().completion_params(config, tools)

        # forward fallback model list via extra_body
        if self.models:
            extra_body = params.get("extra_body") or {}
            extra_body["models"] = self.models
            extra_body.setdefault("route", "fallback")
            params["extra_body"] = extra_body

        return params
