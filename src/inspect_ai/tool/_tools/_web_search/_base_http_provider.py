import os
from abc import ABC, abstractmethod
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    stop_after_delay,
    wait_exponential_jitter,
)

from inspect_ai._util.content import ContentText
from inspect_ai._util.error import PrerequisiteError
from inspect_ai._util.httpx import httpx_should_retry, log_httpx_retry_attempt
from inspect_ai.util._concurrency import concurrency


class BaseHttpProvider(ABC):
    """Base class for HTTP-based web search providers (Exa, Tavily, etc.)."""

    def __init__(
        self,
        env_key_name: str,
        api_endpoint: str,
        provider_name: str,
        concurrency_key: str,
        options: dict[str, Any] | None = None,
    ):
        self.env_key_name = env_key_name
        self.api_endpoint = api_endpoint
        self.provider_name = provider_name
        self.concurrency_key = concurrency_key

        self.max_connections = self._extract_max_connections(options)
        self.api_options = self._prepare_api_options(options)
        self.api_key = self._validate_api_key()
        self.client = httpx.AsyncClient(timeout=30)

    @abstractmethod
    def prepare_headers(self, api_key: str) -> dict[str, str]:
        """Prepare HTTP headers for the request."""
        pass

    @abstractmethod
    def parse_response(self, response_data: dict[str, Any]) -> ContentText | None:
        """Parse the API response and extract content with citations."""
        pass

    @abstractmethod
    def set_default_options(self, options: dict[str, Any]) -> dict[str, Any]:
        """Set provider-specific default options."""
        pass

    def _extract_max_connections(self, options: dict[str, Any] | None) -> int:
        """Extract max_connections from options, defaulting to 10."""
        if not options:
            return 10
        max_conn = options.get("max_connections", 10)
        return int(max_conn) if max_conn is not None else 10

    def _prepare_api_options(self, options: dict[str, Any] | None) -> dict[str, Any]:
        """Prepare API options by removing max_connections and setting defaults."""
        if not options:
            api_options = {}
        else:
            # Remove max_connections as it's not an API option
            api_options = {k: v for k, v in options.items() if k != "max_connections"}

        # Apply provider-specific defaults
        return self.set_default_options(api_options)

    def _validate_api_key(self) -> str:
        """Validate that the required API key is set in environment."""
        api_key = os.environ.get(self.env_key_name)
        if not api_key:
            raise PrerequisiteError(
                f"{self.env_key_name} not set in the environment. Please ensure this variable is defined to use {self.provider_name} with the web_search tool.\n\nLearn more about the {self.provider_name} web search provider at https://inspect.aisi.org.uk/tools.html#{self.provider_name.lower()}-provider"
            )
        return api_key

    async def search(self, query: str) -> ContentText | None:
        """Execute a search query using the provider's API."""

        # Common retry logic for all HTTP providers
        @retry(
            wait=wait_exponential_jitter(),
            stop=stop_after_attempt(5) | stop_after_delay(60),
            retry=retry_if_exception(httpx_should_retry),
            before_sleep=log_httpx_retry_attempt(self.api_endpoint),
        )
        async def _search() -> httpx.Response:
            response = await self.client.post(
                self.api_endpoint,
                headers=self.prepare_headers(self.api_key),
                json={"query": query, **self.api_options},
            )
            response.raise_for_status()
            return response

        async with concurrency(self.concurrency_key, self.max_connections):
            response_data = (await _search()).json()
            return self.parse_response(response_data)
