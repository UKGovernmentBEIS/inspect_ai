from typing_extensions import override

from .._generate_config import GenerateConfig
from .openai_compatible import OpenAICompatibleAPI


class FireworksAIAPI(OpenAICompatibleAPI):
    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
        emulate_tools: bool = False,
    ) -> None:
        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            config=config,
            service="Fireworks",
            service_base_url="https://api.fireworks.ai/inference/v1",
            emulate_tools=emulate_tools,
        )

    @override
    def canonical_name(self) -> str:
        """Canonical model name for model info database lookup.

        Fireworks model names carry no creator component (they look like
        accounts/fireworks/models/deepseek-r1-0528), so the bare name can't
        identify a database entry: DeepSeek's own API served R1-0528 at 64K
        while Fireworks serves the open weights at 160K, and both are keyed by
        the same model name under different organizations. Strip the account
        prefix and key the model under `fireworks`, where the synced catalog
        records what Fireworks actually serves.
        """
        return f"fireworks/{self._model_slug()}"

    @override
    def input_tokens_name(self) -> str:
        """Model name used for looking up model input tokens."""
        from inspect_ai.model._model_info import _get_model_info_direct

        if _get_model_info_direct(self.canonical_name()) is None:
            # Not in the synced catalog (added since the last sync, a private
            # deployment, or a model Fireworks reports no context length for).
            # Fall back to the bare name so it can still fuzzy-match the
            # creator's entry rather than resolving to nothing.
            return self._model_slug()
        return super().input_tokens_name()

    def _model_slug(self) -> str:
        """Model name with the Fireworks account prefix removed."""
        prefix = "accounts/fireworks/models/"
        name = self.service_model_name()
        if name.startswith(prefix):
            name = name[len(prefix) :]
        return name

    @override
    def should_stream(self, config: GenerateConfig) -> bool:
        return config.max_tokens is not None and config.max_tokens > 16000
