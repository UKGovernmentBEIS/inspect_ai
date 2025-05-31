import atexit
import logging
import os
from subprocess import Popen
from typing import Any
from inspect_ai.model._routing.router_class import RouterClass, RouterClassConfig
from openai import APIStatusError
from typing_extensions import override
import asyncio

from inspect_ai._util.error import PrerequisiteError, pip_dependency_error
from inspect_ai._util.local_server import (
    configure_devices,
    merge_env_server_args,
    start_local_server,
    terminate_process,
)
from inspect_ai.model._chat_message import ChatMessage
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._model_call import ModelCall
from inspect_ai.model._model_output import ModelOutput
from inspect_ai.tool._tool_choice import ToolChoice
from inspect_ai.tool._tool_info import ToolInfo
from inspect_ai.model._model import ModelAPI

from .openai_compatible import OpenAICompatibleAPI
from .vllm import VLLMAPI


"""
the vllmrouter is a class that routes requests to the appropriate model.
1) starts a new vllm server if it doesn't exist for each one of the models.
2) given the query an a routing procedure, it computes the appropriate model to use.
3) it then routes the query to the appropriate model.

requirements:
- the routing procedure is provided by the user.
- the router should be compatible with batches


vllmrouter:
    - model 1:
        - vllmapi
    - model 2:
        - vllmapi
    - routing procedure
        - modelrouter
"""

logger = logging.getLogger(__name__)


class VLLMRouter(ModelAPI):
    """
    Router for managing multiple vLLM models and routing requests between them.

    This class:
    1. Manages multiple vLLM servers for different models
    2. Routes requests to appropriate models based on a user-provided routing procedure
    3. Supports batch processing of requests
    """

    def __init__(
        self,
        model_name: str,
        base_url: str | None = None,
        api_key: str | None = None,
        config: GenerateConfig = GenerateConfig(),
        **model_args: Any,
    ) -> None:
        # Initialize parent class
        super().__init__(
            model_name=model_name,
            base_url=base_url,
            api_key=api_key,
            config=config,
        )

        # Extract models from model_args
        models_config = model_args.get("models", {})
        if isinstance(models_config, dict):
            # Handle named models (e.g., {"reasoning": "model1", "non_reasoning": "model2"})
            self.model_names = list(models_config.values())
            self.model_roles = {role: model for role, model in models_config.items()}
        elif isinstance(models_config, list):
            # Handle list of models
            self.model_names = models_config
            self.model_roles = {
                f"model_{i}": model for i, model in enumerate(models_config)
            }
        else:
            raise ValueError("models must be a dict or list")

        if not self.model_names:
            raise ValueError("At least one model must be specified")

        # Extract ports if provided
        ports = model_args.get("ports", None)
        if ports is not None:
            assert len(self.model_names) == len(ports), (
                "ports must be provided for each model"
            )

        logger.info(
            f"Initializing VLLMRouter with models: {self.model_names} and ports: {ports}"
        )

        # Initialize VLLM models
        self.models = {}

        for i, model_name in enumerate(self.model_names):
            self.models[model_name] = VLLMAPI(
                model_name=model_name,
                config=config,
                port=ports[i] if ports is not None else None,
            )

        # Initialize routing procedure
        routing_config = model_args.get("routing_config", {})
        router_config = RouterClassConfig(
            n_models=len(self.models),
            d_embedding=routing_config.get("d_embedding", 128),
            text_dim=routing_config.get("text_dim", 1536),
            embedding_model=routing_config.get(
                "embedding_model", "text-embedding-3-small"
            ),
            use_proj=routing_config.get("use_proj", True),
        )
        self.routing_procedure = RouterClass(router_config)

        # Load router weights if provided
        router_weights_path = routing_config.get("weights_path")
        if router_weights_path:
            self.routing_procedure.load_weights(router_weights_path)

    def _extract_query_text(self, messages: list[ChatMessage]) -> str:
        """Extract text content from ChatMessage list for routing."""
        # Combine all message content into a single string
        text_parts = []
        for msg in messages:
            if hasattr(msg, "text") and msg.text:
                text_parts.append(msg.text)
            elif hasattr(msg, "content") and msg.content:
                # Handle different ChatMessage formats
                if isinstance(msg.content, str):
                    text_parts.append(msg.content)
                elif isinstance(msg.content, list):
                    # Handle content that might be a list of parts
                    for part in msg.content:
                        if isinstance(part, dict) and "text" in part:
                            text_parts.append(part["text"])
                        elif isinstance(part, str):
                            text_parts.append(part)

        return " ".join(text_parts) if text_parts else ""

    async def _route_query(self, query_text: str) -> str:
        """Route a single query to the best model."""
        try:
            # Use the routing procedure to select the best model
            model_indices = await self.routing_procedure.forward_batch([query_text])
            selected_model_index = model_indices[0]
            selected_model_name = self.model_names[selected_model_index]

            logger.info(
                f"Routing query to model: {selected_model_name} (index: {selected_model_index})"
            )
            return selected_model_name
        except Exception as e:
            logger.warning(f"Routing failed, falling back to first model: {e}")
            # Fallback to first model if routing fails
            return self.model_names[0]

    async def generate(
        self,
        input: list[ChatMessage],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> ModelOutput | tuple[ModelOutput | Exception, ModelCall]:
        """Generate response by routing to the appropriate model."""
        try:
            # Extract query text for routing
            query_text = self._extract_query_text(input)

            # Route to the best model
            selected_model_name = await self._route_query(query_text)
            selected_model = self.models[selected_model_name]

            logger.info(f"Generating response using model: {selected_model_name}")

            # Generate response using the selected model
            result = await selected_model.generate(input, tools, tool_choice, config)

            # If result is a tuple, modify the ModelCall to indicate which model was used
            if isinstance(result, tuple):
                output, model_call = result
                # Update model call to show which model was actually used
                if hasattr(model_call, "request") and model_call.request:
                    model_call.request["routed_to_model"] = selected_model_name
                return output, model_call
            else:
                return result

        except Exception as e:
            logger.error(f"Error in VLLMRouter.generate: {e}")
            # Return error as ModelOutput
            return ModelOutput.from_content(
                content=f"Router error: {str(e)}",
                stop_reason="unknown",
            )

    async def generate_batch(
        self,
        inputs: list[list[ChatMessage]],
        tools: list[ToolInfo],
        tool_choice: ToolChoice,
        config: GenerateConfig,
    ) -> list[ModelOutput | tuple[ModelOutput | Exception, ModelCall]]:
        """Generate responses for a batch of inputs by routing each to appropriate models."""
        try:
            # Extract query texts for routing
            query_texts = [
                self._extract_query_text(input_msgs) for input_msgs in inputs
            ]

            # Route all queries at once
            model_indices = await self.routing_procedure.forward_batch(query_texts)

            # Group inputs by selected model for efficient batch processing
            model_batches: dict[str, list[tuple[int, list[ChatMessage]]]] = {}
            for i, model_index in enumerate(model_indices):
                model_name = self.model_names[model_index]
                if model_name not in model_batches:
                    model_batches[model_name] = []
                model_batches[model_name].append((i, inputs[i]))

            # Process each model's batch
            results: list[ModelOutput | tuple[ModelOutput | Exception, ModelCall]] = [
                None
            ] * len(inputs)  # type: ignore

            for model_name, batch_items in model_batches.items():
                model = self.models[model_name]
                batch_inputs = [item[1] for item in batch_items]

                logger.info(
                    f"Processing batch of {len(batch_inputs)} queries with model: {model_name}"
                )

                # Generate responses for this model's batch
                if hasattr(model, "generate_batch"):
                    batch_results = await model.generate_batch(
                        batch_inputs, tools, tool_choice, config
                    )
                else:
                    # Fallback to individual generation if batch not supported
                    batch_results = []
                    for batch_input in batch_inputs:
                        result = await model.generate(
                            batch_input, tools, tool_choice, config
                        )
                        batch_results.append(result)

                # Place results back in correct positions
                for (original_index, _), result in zip(batch_items, batch_results):
                    # Update model call to show which model was used
                    if isinstance(result, tuple):
                        output, model_call = result
                        if hasattr(model_call, "request") and model_call.request:
                            model_call.request["routed_to_model"] = model_name
                        results[original_index] = (output, model_call)
                    else:
                        results[original_index] = result

            return results

        except Exception as e:
            logger.error(f"Error in VLLMRouter.generate_batch: {e}")
            # Return error for all inputs
            error_output = ModelOutput.from_content(
                content=f"Router batch error: {str(e)}",
                stop_reason="unknown",
            )
            return [error_output] * len(inputs)

    @override
    def connection_key(self) -> str:
        """Scope for enforcing max_connections."""
        return f"vllm-router-{'+'.join(self.model_names)}"

    @override
    def should_retry(self, ex: Exception) -> bool:
        """Determine if an exception should trigger a retry."""
        # Delegate to the first model's retry logic
        return self.models[self.model_names[0]].should_retry(ex)

    async def aclose(self) -> None:
        """Close all model clients and cleanup servers."""
        logger.info("Closing VLLMRouter and all managed models")

        # Close all models
        for model in self.models.values():
            try:
                await model.aclose()
            except Exception as e:
                logger.warning(f"Error closing model: {e}")

    def close(self) -> None:
        """Close all models synchronously."""
        logger.info("Closing VLLMRouter models synchronously")

        # Close all models
        for model in self.models.values():
            try:
                model.close()
            except Exception as e:
                logger.warning(f"Error closing model: {e}")

    @property
    def model_names_list(self) -> list[str]:
        """Get list of managed model names."""
        return self.model_names

    def get_model_stats(self) -> dict[str, Any]:
        """Get statistics about managed models."""
        stats = {}
        for name, model in self.models.items():
            stats[name] = {
                "server_running": getattr(model, "server_is_running", False),
                "port": getattr(model, "port", None),
                "base_url": getattr(model, "base_url", None),
            }
        return stats
