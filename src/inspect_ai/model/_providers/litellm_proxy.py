import os
import re
from collections.abc import AsyncIterable
from contextvars import ContextVar
from logging import getLogger
from typing import Any, Literal, NamedTuple

from openai import (
    APIConnectionError,
    APIError,
    APIResponseValidationError,
    APIStatusError,
    BadRequestError,
)
from openai.types.chat import (
    ChatCompletion,
    ChatCompletionChunk,
    ChatCompletionMessageParam,
    ChatCompletionToolParam,
)
from typing_extensions import override

from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.logger import warn_once
from inspect_ai.tool import ToolChoice, ToolInfo
from inspect_ai.tool._tool_info import INTERNAL_TOOL_TYPE
from inspect_ai.tool._tools._computer._computer import is_computer_tool_info

from .._chat_message import ChatMessage
from .._generate_config import GenerateConfig
from .._model_call import ModelCall
from .._model_data.model_data import ModelInfo
from .._model_info import (
    MODEL_INFO_LOOKUP_API_KEY,
    _get_custom_model_info,
    _get_model_info_direct,
    set_model_info,
)
from .._model_output import ChatCompletionChoice, ModelOutput
from .._openai import (
    OpenAIResponseError,
    chat_choices_from_openai,
    is_gpt_5_model,
    is_o_series_model,
    openai_chat_completion_stream_final,
    openai_refusal_model_output,
)
from .._openai_responses import (
    RESPONSES_VERBATIM,
    _maybe_native_tool_param,
    _tool_param_for_tool_info,
)
from ._anthropic_max_tokens import (
    ANTHROPIC_HIGH_EFFORT_MAX_TOKENS,
    ANTHROPIC_MAX_TOKENS,
    anthropic_effort_max_tokens,
)
from ._litellm_proxy_caching import (
    cache_write_ttl,
    with_cache_breakpoints,
    with_tool_cache_breakpoint,
)
from ._litellm_proxy_errors import litellm_error_model_output, upstream_message
from ._litellm_proxy_model_info import (
    ProxyDeployment,
    proxy_aliases,
    proxy_deployments,
    proxy_model_info,
)
from ._litellm_proxy_names import ProxyResolution, resolve_deployments
from ._litellm_proxy_reasoning import (
    ThinkingBlocksAccumulator,
    choice_with_litellm_reasoning,
    litellm_messages_to_openai,
    with_streamed_thinking_blocks,
    without_thinking_block_deltas,
)
from ._litellm_proxy_reasoning_effort import next_effort, rejected_effort
from ._litellm_proxy_vendor import (
    VENDOR_NAMES,
    Vendor,
    deployment_route,
    frontier_base_model,
    is_openai_api_base,
    upstream_vendor,
)
from ._openai_web_search import maybe_web_search_tool
from .openai_compatible import ModelInfo as CompatibleModelInfo
from .openai_compatible import OpenAICompatibleAPI
from .util import environment_prerequisite_error, model_base_url

logger = getLogger(__name__)

LITELLM_PROXY_API_KEY = "LITELLM_PROXY_API_KEY"
LITELLM_PROXY_BASE_URL = "LITELLM_PROXY_BASE_URL"
# base URL variable used by LiteLLM's own SDK; accepted as an alias
LITELLM_PROXY_API_BASE = "LITELLM_PROXY_API_BASE"
# shorter names, accepted when the `LITELLM_PROXY_` ones are unset
LITELLM_API_KEY = "LITELLM_API_KEY"
LITELLM_BASE_URL = "LITELLM_BASE_URL"


_cache_prompt: ContextVar[bool] = ContextVar(
    "litellm_proxy_cache_prompt", default=False
)
"""Whether the current request gets cache breakpoints (set per generate)."""

_cache_write_ttl: ContextVar[Literal["5m", "1h"] | None] = ContextVar(
    "litellm_proxy_cache_write_ttl", default=None
)
"""TTL of the current request's cache writes, from its usage (for cost)."""

_EXTERNAL_SEARCH_PROVIDERS = ("tavily", "exa", "google")

_PREFILL_REJECTED = re.compile(
    r"assistant (message )?prefill|prefill(ing)? (the )?assistant", re.IGNORECASE
)


class _Registration(NamedTuple):
    user: ModelInfo | None
    """The user's registration that was merged in, if any."""

    registered: ModelInfo
    """What this provider registered."""

    base_url: str | None
    """The proxy it was registered from."""


_registrations: dict[str, _Registration] = {}
"""Model info this provider registered, keyed by model string.

set_model_info() records no provenance, so this tells a registration of ours
(merged again from the user's original when a model is constructed again)
from the user's own.
"""


class LiteLLMProxyAPI(OpenAICompatibleAPI):
    """Provider for models served by a LiteLLM proxy.

    The proxy is self-hosted, so the base URL has no default and must be
    passed as `base_url` or set in `LITELLM_PROXY_BASE_URL` (or
    `LITELLM_PROXY_API_BASE`, or `LITELLM_BASE_URL`). The API key is read
    from `LITELLM_PROXY_API_KEY`, or `LITELLM_API_KEY` when that is unset.

    Construction reads the proxy's `/model/info` listing and the API key's
    key and team aliases (see `_litellm_proxy_model_info`), and fails if it
    cannot read the listing. An alias is resolved to the model name it
    routes to before its deployments are looked up. It then registers
    model info for `litellm-proxy/<alias>`: Inspect's entry for the resolved
    upstream model, with fields it lacks (often cost) filled from the proxy's
    metadata. A registration the user made for `litellm-proxy/<alias>` is
    kept instead.

    Construction fails unless that model info has a context window. Pass
    `require_model_info=False` to allow it anyway, or `model_info=False` to
    skip the listing, the registration and the check.

    When `responses_api` is not passed, GPT-5, o-series and Codex models
    served directly by OpenAI use the Responses API, as with the native
    `openai` provider; everything else uses Chat Completions.
    """

    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
        **model_args: Any,
    ) -> None:
        base_url_vars = [
            LITELLM_PROXY_BASE_URL,
            LITELLM_PROXY_API_BASE,
            LITELLM_BASE_URL,
        ]
        base_url = model_base_url(base_url, base_url_vars)
        if not base_url:
            raise environment_prerequisite_error("LiteLLM Proxy", base_url_vars)
        fetch_model_info = model_args.pop("model_info", True)
        if not isinstance(fetch_model_info, bool):
            raise ValueError("model_info must be a bool")
        require_model_info = model_args.pop("require_model_info", True)
        if not isinstance(require_model_info, bool):
            raise ValueError("require_model_info must be a bool")
        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            config=config,
            service="LiteLLM Proxy",
            api_key_var=(
                LITELLM_API_KEY
                if LITELLM_PROXY_API_KEY not in os.environ
                and LITELLM_API_KEY in os.environ
                else LITELLM_PROXY_API_KEY
            ),
            **model_args,
        )

        # get_model_info() constructs providers with a placeholder key, which
        # the proxy would reject
        self._deployments: list[ProxyDeployment] | None = None
        # the model name a key or team alias routes to, and why aliases
        # couldn't be read
        self._alias_target: str | None = None
        self._alias_error: str | None = None
        if fetch_model_info and self.api_key != MODEL_INFO_LOOKUP_API_KEY:
            assert self.base_url is not None and self.api_key is not None
            headers = dict(self.model_args.get("default_headers") or {})
            deployments = proxy_deployments(self.base_url, self.api_key, headers)
            aliases = proxy_aliases(self.base_url, self.api_key, headers)
            alias = self.service_model_name()
            target = aliases.resolve(alias)
            self._alias_target = target if target != alias else None
            self._alias_error = aliases.error
            if aliases.error:
                warn_once(
                    logger,
                    "Could not read the key and team model aliases from the "
                    f"LiteLLM proxy ({aliases.error}). Model names are looked up "
                    "as listed, so a name that is also an alias of your key or "
                    "team gets the model info of the listed model.",
                )
            self._deployments = [d for d in deployments if d.model_name == target]
        self._resolution: ProxyResolution | None = resolve_deployments(
            self.service_model_name(), self._deployments or []
        )
        self._vendor: Vendor | None = upstream_vendor(
            [
                self._resolution.upstream if self._resolution else None,
                self._resolution.db_key if self._resolution else None,
                self._alias_target,
                self.service_model_name(),
            ]
        )
        if self._deployments is not None:
            self._register_model_info()
            if require_model_info:
                self._check_model_info()

        self._openai_route = bool(self._deployments) and all(
            deployment_route(d.model, d.custom_llm_provider) == "openai"
            and is_openai_api_base(d.api_base)
            for d in self._deployments or []
        )
        if (
            self.responses_api is None
            and self._openai_route
            and self._responses_preferred()
            and config.num_choices is None
            and not self.emulate_tools
        ):
            self.responses_api = True

        # reasoning_effort values the proxy rejected for this model (see generate)
        self._rejected_efforts: set[str] = set()
        self._effort_unsupported = False

    def _model_info_key(self) -> str:
        """The `str(model)` key that model lookups for this model check first."""
        return f"litellm-proxy/{self.service_model_name()}"

    def _register_model_info(self) -> None:
        """Register model info, merged field by field.

        Precedence: the user's registration for this key, then Inspect's
        entry for the resolved model (which includes the user's registration
        for that name, e.g. from `set_model_cost`), then the proxy's metadata.
        An alias that resolves to nothing still gets an (empty) entry, so
        lookups stop there rather than fuzzy matching the alias.
        """
        key = self._model_info_key()
        current = _get_custom_model_info(key)
        previous = _registrations.get(key)
        if previous is not None and current is previous.registered:
            user = previous.user
        else:
            user = current
        db_key = self._resolution.db_key if self._resolution else None
        db = _get_model_info_direct(db_key) if db_key else None
        proxy = proxy_model_info(self._deployments or [])
        info = merged_model_info(user, merged_model_info(db, proxy))
        if (
            previous is not None
            and current is previous.registered
            and previous.base_url != self.base_url
            and previous.registered != info
        ):
            # the model info key is the model name, which has no proxy URL
            warn_once(
                logger,
                f"LiteLLM proxy model '{self.service_model_name()}' is served "
                f"by more than one proxy "
                f"({', '.join(sorted([str(previous.base_url), str(self.base_url)]))}) "
                "with different model info; models with this name use the "
                "info from the one created last.",
            )
        set_model_info(key, info)
        _registrations[key] = _Registration(
            user=user, registered=info, base_url=self.base_url
        )

    def _routed_name(self) -> str:
        """The model name requests are routed to (the alias target, if any)."""
        return self._alias_target or self.service_model_name()

    def _check_model_info(self) -> None:
        info = _get_custom_model_info(self._model_info_key())
        if info is not None and info.input_tokens is not None:
            return
        alias = self.service_model_name()
        about = (
            f" (a key or team alias for '{self._alias_target}')"
            if self._alias_target
            else ""
        )
        db_key = self._resolution.db_key if self._resolution else None
        upstream = self._resolution.upstream if self._resolution else None
        if not self._deployments and self._alias_target:
            found = (
                "The proxy's /model/info listing has no deployment for "
                f"'{self._alias_target}'."
            )
        elif not self._deployments:
            found = (
                "The proxy's /model/info listing has no deployment for it (it "
                "lists only the models the API key may use), and it is not an "
                "alias of the API key or its team."
            )
            if self._alias_error:
                found += f" (The aliases could not be read: {self._alias_error})"
        elif db_key:
            found = (
                f"Inspect's model database has no context window for its upstream "
                f"model '{db_key}' and the proxy reports no max_input_tokens for it."
            )
        elif upstream:
            found = (
                f"Its upstream model '{upstream}' is not in Inspect's model "
                "database and the proxy reports no max_input_tokens for it."
            )
        else:
            found = (
                "The proxy reports neither its upstream model nor "
                "max_input_tokens for it."
            )
        raise PrerequisiteError(
            f"No model info (context window) for LiteLLM proxy model "
            f"'{alias}'{about}. {found}\n\n"
            "Inspect uses it for the context window (compaction) and cost. "
            "To fix, do one of:\n\n"
            f"{self._model_info_fix()}\n"
            f'- call set_model_info("{self._model_info_key()}", '
            "ModelInfo(context_length=...)) before creating the model;\n"
            "- pass -M require_model_info=false."
        )

    def _model_info_fix(self) -> str:
        """The error's first fix: `model_info` to add to the proxy config."""
        alias = self._routed_name()
        if self._vendor is not None:
            return (
                f"- add model_info to the '{alias}' deployment in the proxy "
                "config, naming the model it is closest to as base_model. For "
                f"the current frontier {VENDOR_NAMES[self._vendor]} model:\n\n"
                "      model_info:\n"
                f"        base_model: {frontier_base_model(self._vendor)}\n\n"
                "  base_model also gives LiteLLM the model's capabilities "
                "(e.g. reasoning effort, adaptive thinking, prompt caching), "
                "which it otherwise lacks for a model it doesn't know;"
            )
        return (
            f"- add model_info to the '{alias}' deployment in the proxy "
            "config, naming the model it is closest to as base_model (e.g. "
            "openai/gpt-5), or its limits:\n\n"
            "      model_info:\n"
            "        max_input_tokens: <context window>\n"
            "        max_output_tokens: <output limit>\n\n"
            "  base_model also gives LiteLLM the model's capabilities;"
        )

    def _responses_preferred(self) -> bool:
        """GPT-5 or later, o-series and Codex models, by upstream model family.

        The native `openai` provider uses the Responses API for these. On
        Chat Completions, OpenAI returns none of their reasoning, so it can't
        be carried to the next turn. Unlike the native provider, unrecognized
        names are not treated as frontier codenames: a proxy can send every
        `openai/` deployment to another server (`OPENAI_API_BASE`) without
        listing an `api_base`. A codename gets the default through
        `model_info.base_model`, which the model info check asks for.
        """
        family = self.model_family()
        return is_gpt_5_model(family) or is_o_series_model(family) or "codex" in family

    def _is_claude(self) -> bool:
        return self._vendor == "anthropic"

    @property
    @override
    def schema_exclude_fields(self) -> set[str] | None:
        """None (keep every field) for Claude, which takes full JSON schemas."""
        return None if self._is_claude() else super().schema_exclude_fields

    @override
    def should_stream(self, config: GenerateConfig) -> bool:
        """Stream unless the request can't be streamed.

        Long generations (e.g. high reasoning effort) otherwise hit client
        and proxy timeouts, and a streamed reply keeps its thinking blocks.
        `-M stream=false` opts out. Responses requests are streamed only to
        OpenAI (LiteLLM #43010 affects its conversion for other upstreams).
        """
        return (not self.responses_api or self._openai_route) and self.auto_streamable(
            config
        )

    @override
    def max_tokens_for_config(self, config: GenerateConfig) -> int | None:
        """For Claude, sized as the native provider does for adaptive thinking.

        Anthropic requires max_tokens, and LiteLLM sends 4096 when it lacks
        one for the model. The model's registered output limit caps it. The
        64k floor keys on `reasoning_effort`, which LiteLLM maps to Anthropic's
        effort (the native provider keys it on `config.effort`, which this
        provider does not send).
        """
        if not self._is_claude():
            return super().max_tokens_for_config(config)
        effort = config.reasoning_effort
        max_tokens = ANTHROPIC_MAX_TOKENS + anthropic_effort_max_tokens(effort)
        if effort in ("xhigh", "max"):
            max_tokens = max(max_tokens, ANTHROPIC_HIGH_EFFORT_MAX_TOKENS)
        info = _get_custom_model_info(self._model_info_key())
        if info is not None and info.output_tokens:
            max_tokens = min(max_tokens, info.output_tokens)
        return max_tokens

    @override
    def tools_to_openai(self, tools: list[ToolInfo]) -> list[ChatCompletionToolParam]:
        openai_tools = super().tools_to_openai(tools)
        return (
            with_tool_cache_breakpoint(openai_tools)
            if _cache_prompt.get()
            else openai_tools
        )

    @override
    def on_response(self, response: dict[str, Any]) -> None:
        usage = response.get("usage")
        if not self._is_claude() or not isinstance(usage, dict):
            return
        ttl = cache_write_ttl(usage)
        _cache_write_ttl.set(ttl)
        details = usage.get("prompt_tokens_details") or {}
        if ttl is None and details.get("cache_write_tokens"):
            warn_once(
                logger,
                f"The LiteLLM proxy does not report the TTL of cache writes for "
                f"model '{self.service_model_name()}'; they are costed at the "
                "5-minute rate, which undercounts if the proxy uses a 1-hour TTL.",
            )

    @override
    def cache_write_ttl(self) -> str | None:
        """The TTL the current request's usage reports for its cache writes."""
        return _cache_write_ttl.get()

    @override
    def resolve_tools(
        self, tools: list[ToolInfo], tool_choice: ToolChoice, config: GenerateConfig
    ) -> tuple[list[ToolInfo], ToolChoice, GenerateConfig]:
        for tool in tools:
            self._check_web_search(tool, config)
        if self.responses_api:
            tools = [self._as_function_tool(tool, config) for tool in tools]
        return super().resolve_tools(tools, tool_choice, config)

    def _as_function_tool(self, tool: ToolInfo, config: GenerateConfig) -> ToolInfo:
        """`tool`, sent as a function tool if OpenAI would otherwise host it.

        Of OpenAI's hosted tools, only web search has been verified through
        the proxy. The others (code interpreter, computer use, remote MCP,
        tool search) are sent as function tools, as on Chat Completions.
        `computer()` is always marked as sent verbatim: the Responses code
        requires `store=True` for any `computer()` tool, even one sent as a
        function tool (for models without native computer use).
        """
        options = tool.options or {}
        if (
            options.get(INTERNAL_TOOL_TYPE) == "web_search"
            or RESPONSES_VERBATIM in options
        ):
            return tool
        family = self.model_family()
        is_latest = self.responses_model_info().is_latest()
        if _maybe_native_tool_param(
            tool, family, config, is_latest
        ) is None and not is_computer_tool_info(tool):
            return tool
        param = _tool_param_for_tool_info(
            tool, family, config.model_copy(update={"internal_tools": False}), is_latest
        )
        return tool.model_copy(update={"options": {RESPONSES_VERBATIM: dict(param)}})

    def _check_web_search(self, tool: ToolInfo, config: GenerateConfig) -> None:
        """Fail before sending a `web_search()` that has no provider here.

        Of the built-in providers, only OpenAI's (on the Responses API) is
        sent to the proxy as a hosted tool. Otherwise the tool goes out as a
        function tool, whose execution fails when there is no external
        provider to run the search.
        """
        options = tool.options or {}
        if options.get(INTERNAL_TOOL_TYPE) != "web_search":
            return
        if any(provider in options for provider in _EXTERNAL_SEARCH_PROVIDERS):
            return
        if (
            self.responses_api
            and config.internal_tools is not False
            and maybe_web_search_tool(self.model_family(), tool) is not None
        ):
            return
        fixes = [
            'add an external provider, e.g. web_search("tavily") or '
            'web_search(["anthropic", "tavily"]) ("exa" and "google" also work).'
        ]
        if self._vendor == "openai" and not self.responses_api:
            fixes.append(
                "pass -M responses_api=true to use OpenAI's built-in search "
                '(with the "openai" provider).'
            )
        raise PrerequisiteError(
            f"web_search() has no provider for LiteLLM proxy model "
            f"'{self.service_model_name()}'. Built-in search providers other "
            "than OpenAI's (on the Responses API) are not supported through a "
            "LiteLLM proxy. "
            + ("To fix, do one of:\n\n" if len(fixes) > 1 else "To fix:\n\n")
            + "\n".join(f"- {fix}" for fix in fixes)
        )

    @override
    def input_tokens_name(self) -> str:
        """The registered key, when there is one, so lookups stop there."""
        key = self._model_info_key()
        if _get_custom_model_info(key) is not None:
            return key
        return super().input_tokens_name()

    @override
    def canonical_name(self) -> str:
        """The Inspect database key of the upstream model, when it resolves.

        Otherwise the normalized upstream model name, or the model name
        requests are routed to (the alias, or its target for a key or team
        alias) when the proxy listed no deployment for it or model info was
        not fetched.
        """
        resolution = self._resolution
        if resolution is not None:
            name = resolution.db_key or resolution.upstream
            if name:
                return name
        return self._routed_name()

    @override
    def model_family(self) -> str:
        """The upstream model's name, so request shaping follows the model.

        A `family` registered with `set_model_info` (under the alias, the
        `litellm-proxy/<alias>` model string, or the canonical name) wins.
        The organization is dropped from the canonical name: family checks
        such as `is_o_series_model` match patterns anywhere in the name.
        """
        alias = self.service_model_name()
        canonical = self.canonical_name()
        for name in (alias, self._model_info_key(), canonical):
            info = _get_model_info_direct(name)
            if info is not None and info.family:
                return info.family
        if self._resolution is None:
            return self._routed_name()
        return canonical.split("/")[-1]

    @override
    def chat_choices_from_completion(
        self, completion: ChatCompletion, tools: list[ToolInfo]
    ) -> list[ChatCompletionChoice]:
        # chat_choices_from_openai returns choices ordered by index
        sources = sorted(completion.choices, key=lambda choice: choice.index)
        return [
            choice_with_litellm_reasoning(choice, source.message)
            for choice, source in zip(
                chat_choices_from_openai(completion, tools), sources, strict=True
            )
        ]

    @override
    async def messages_to_openai(
        self, input: list[ChatMessage]
    ) -> list[ChatCompletionMessageParam]:
        messages = await litellm_messages_to_openai(input)
        return with_cache_breakpoints(messages) if _cache_prompt.get() else messages

    @override
    async def stream_completion(
        self, stream: AsyncIterable[ChatCompletionChunk]
    ) -> ChatCompletion:
        accumulators: dict[int, ThinkingBlocksAccumulator] = {}
        completion = await openai_chat_completion_stream_final(
            without_thinking_block_deltas(stream, accumulators)
        )
        return with_streamed_thinking_blocks(completion, accumulators)

    @override
    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput | tuple[ModelOutput | Exception, ModelCall]:
        """Generate, lowering or dropping a `reasoning_effort` the proxy rejects.

        Chat completions requests to Claude models get prompt cache
        breakpoints unless `cache_prompt` is false (see
        `_litellm_proxy_caching`).

        A rejection (see `_litellm_proxy_reasoning_effort`) is remembered for
        this model, a warning names the value used instead, and the request is
        retried. Later requests use the lowered value directly.
        """
        if config.reasoning_tokens is not None:
            warn_once(
                logger,
                "reasoning_tokens is not sent to LiteLLM proxy models (only "
                "reasoning_effort is), so it is ignored.",
            )
        _cache_prompt.set(self._is_claude() and config.cache_prompt is not False)
        _cache_write_ttl.set(None)
        requested = config.reasoning_effort
        # ends: each rejection is recorded, so the next attempt sends a value
        # not yet rejected, or no effort at all
        while True:
            effort = self._effort_for(requested)
            if effort != config.reasoning_effort:
                config = config.model_copy(update={"reasoning_effort": effort})
            result = await super().generate(input, tools, tool_choice, config)
            output = result[0] if isinstance(result, tuple) else result
            rejection = (
                rejected_effort(_error_message(output), effort)
                if effort is not None and isinstance(output, BadRequestError)
                else None
            )
            if rejection is None:
                if requested is not None and effort != requested:
                    instead = (
                        f"using '{effort}'" if effort else "sending no reasoning_effort"
                    )
                    warn_once(
                        logger,
                        f"LiteLLM proxy model '{self.service_model_name()}' does "
                        f"not accept reasoning_effort='{requested}'; {instead}.",
                    )
                return result
            if rejection.kind == "parameter":
                self._effort_unsupported = True
            else:
                assert effort is not None
                self._rejected_efforts.add(effort)

    def _effort_for(self, requested: str | None) -> str | None:
        """The effort to send for `requested`, given the rejections so far."""
        if requested is None or self._effort_unsupported:
            return None
        if requested in self._rejected_efforts:
            return next_effort(requested, self._rejected_efforts)
        return requested

    @override
    def supports_max_reasoning_effort(self) -> bool:
        """Always true: `max` is sent, and lowered by `generate` if rejected.

        The base check recognizes only OpenAI models, so it would lower `max`
        for other upstreams (e.g. Claude) that accept it.
        """
        return True

    @override
    def responses_model_info(self) -> CompatibleModelInfo:
        # LiteLLM converts Responses reasoning items to each upstream
        # provider's format: reasoning with no encrypted content (open models)
        # must be sent back as text, and some upstreams reject empty text
        return CompatibleModelInfo(
            self.model_family(),
            supports_max_reasoning_effort=self.supports_max_reasoning_effort(),
            replays_reasoning_text=True,
            omits_empty_tool_call_text=True,
        )

    @override
    def handle_bad_request(self, ex: APIStatusError) -> ModelOutput | Exception:
        message = _error_message(ex)
        if _PREFILL_REJECTED.search(message):
            return PrefillNotSupportedError(self.service_model_name(), message)
        output = litellm_error_model_output(self.service_model_name(), message)
        if output is None:
            # the base class's message heuristics, recording the upstream
            # message rather than LiteLLM's wrapping of it
            output = openai_refusal_model_output(
                self.service_model_name(),
                ex.code,
                ex.type,
                message,
                upstream_message(message),
            )
        return output if output is not None else super().handle_bad_request(ex)

    @override
    def handle_stream_error(
        self, ex: APIError | OpenAIResponseError
    ) -> ModelOutput | None:
        # status, validation and connection errors keep their retry handling
        if not isinstance(
            ex, APIStatusError | APIResponseValidationError | APIConnectionError
        ):
            message = (
                ex.message
                if isinstance(ex, OpenAIResponseError)
                else _error_message(ex)
            )
            output = litellm_error_model_output(self.service_model_name(), message)
            if output is not None:
                return output
        return super().handle_stream_error(ex)


class PrefillNotSupportedError(RuntimeError):
    """The model rejected a conversation that ends with an assistant message."""

    def __init__(self, model: str, message: str) -> None:
        super().__init__(
            f"LiteLLM proxy model '{model}' does not accept a conversation that "
            "ends with an assistant message (assistant prefill). The last "
            "message sent to generate() must be a user or tool message.\n\n"
            f"Proxy error: {upstream_message(message)}"
        )


def _error_message(ex: APIError) -> str:
    """The proxy's error message (the SDK's `message` prefixes the status)."""
    message = ex.body.get("message") if isinstance(ex.body, dict) else None
    return message if isinstance(message, str) else ex.message


def merged_model_info(
    primary: ModelInfo | None, secondary: ModelInfo | None
) -> ModelInfo:
    """`primary`, with the fields it lacks taken from `secondary`."""
    if primary is None:
        return secondary or ModelInfo()
    if secondary is None:
        return primary
    fill = {
        name: getattr(secondary, name)
        for name in ModelInfo.model_fields
        if getattr(primary, name) is None and getattr(secondary, name) is not None
    }
    merged = primary.model_copy(update=fill)
    # an input limit below the context window (e.g. gpt-5) comes with it
    if primary.input_tokens is None and "context_length" in fill:
        merged = ModelInfo(_input_tokens=secondary.input_tokens, **merged.model_dump())
    return merged
