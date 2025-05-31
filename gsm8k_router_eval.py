"""
GSM8K evaluation with router-based model selection.

This evaluation uses a trained router to dynamically select between reasoning
and non-reasoning models for each query in the GSM8K dataset.
"""

import asyncio
import torch
import json
from pathlib import Path
from typing import Dict, List, Optional, Any

from inspect_ai import Task, eval
from inspect_ai.dataset import example_dataset, Sample
from inspect_ai.model import Model, get_model, GenerateConfig
from inspect_ai.scorer import match, Score, Target
from inspect_ai.solver import Solver, TaskState, generate, chain_of_thought

# Import router classes
from inspect_ai.model._routing.router_class import RouterClass, RouterClassConfig


class RouterSolver(Solver):
    """Solver that uses a trained router to select between reasoning and non-reasoning approaches."""

    def __init__(
        self,
        router_weights_path: str,
        reasoning_model: str,
        non_reasoning_model: str,
        device: str = "auto",
    ):
        """
        Initialize router solver.

        Args:
            router_weights_path: Path to trained router weights
            reasoning_model: Model name for reasoning model
            non_reasoning_model: Model name for non-reasoning model
            device: Device to run router on
        """
        self.router_weights_path = router_weights_path
        self.reasoning_model_name = reasoning_model
        self.non_reasoning_model_name = non_reasoning_model

        # Load router weights and config
        checkpoint = torch.load(router_weights_path, map_location="cpu")
        router_config_dict = checkpoint["config"]
        self.model_ids = checkpoint["model_ids"]

        # Create router config
        self.router_config = RouterClassConfig(**router_config_dict)

        # Initialize router
        self.router = RouterClass(self.router_config)
        self.router.load_state_dict(checkpoint["model_state_dict"])

        # Set device
        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        self.device = device
        self.router = self.router.to(device)
        self.router.eval()

        # Initialize models
        self.reasoning_model = get_model(reasoning_model)
        self.non_reasoning_model = get_model(non_reasoning_model)

        # Stats tracking
        self.routing_stats = {"reasoning": 0, "non_reasoning": 0}

        print(f"Router loaded with models: {list(self.model_ids.keys())}")
        print(f"Reasoning model: {reasoning_model}")
        print(f"Non-reasoning model: {non_reasoning_model}")

    async def route_query(self, query: str) -> str:
        """Route a single query to the appropriate model."""
        # Use router to select best model
        selected_models = await self.router.forward_batch([query])
        selected_model_idx = selected_models[0]

        # Map model index back to model name
        model_name = None
        for name, idx in self.model_ids.items():
            if idx == selected_model_idx:
                model_name = name
                break

        if model_name is None:
            # Fallback to reasoning model
            model_name = "reasoning"

        # Update stats
        self.routing_stats[model_name] += 1

        return model_name

    async def __call__(self, state: TaskState, generate: GenerateConfig) -> TaskState:
        """Solve the task using router-based model selection."""
        # Get the query from the current sample
        query = state.sample.input

        # Route the query
        selected_route = await self.route_query(query)

        # Store routing decision in metadata
        if state.metadata is None:
            state.metadata = {}
        state.metadata["selected_model"] = selected_route

        # Select appropriate model and solver
        if selected_route == "reasoning":
            model = self.reasoning_model
            solver = chain_of_thought()
        else:
            model = self.non_reasoning_model
            solver = generate()

        # Temporarily replace the model in the state
        original_model = state.model
        state.model = model

        try:
            # Apply the selected solver
            state = await solver(state, generate)
        finally:
            # Restore original model
            state.model = original_model

        return state


def gsm8k_router_task(
    router_weights_path: str,
    reasoning_model: str = "openai/gpt-4o-mini",
    non_reasoning_model: str = "openai/gpt-4o-mini",
    device: str = "auto",
    samples: Optional[int] = None,
) -> Task:
    """
    Create GSM8K task with router-based model selection.

    Args:
        router_weights_path: Path to trained router weights
        reasoning_model: Model name for reasoning queries
        non_reasoning_model: Model name for non-reasoning queries
        device: Device for router inference
        samples: Number of samples to use (None for all)

    Returns:
        Task object for inspect eval
    """
    # Load dataset
    dataset = example_dataset("gsm8k")
    if samples:
        dataset = dataset[:samples]

    # Create router solver
    router_solver = RouterSolver(
        router_weights_path=router_weights_path,
        reasoning_model=reasoning_model,
        non_reasoning_model=non_reasoning_model,
        device=device,
    )

    return Task(
        dataset=dataset,
        solver=router_solver,
        scorer=match(),
        metadata={
            "router_weights_path": router_weights_path,
            "reasoning_model": reasoning_model,
            "non_reasoning_model": non_reasoning_model,
            "samples": samples,
        },
    )


# Create evaluation tasks with different configurations
def gsm8k_router_qwen_deepseek():
    """GSM8K with router using Qwen and Deepseek models."""
    return gsm8k_router_task(
        router_weights_path="router_weights.pt",
        reasoning_model="Qwen/Qwen2.5-7b-Instruct",
        non_reasoning_model="deepseek-ai/DeepSeek-R1-Distill-Qwen-7B",
    )


# Export the main evaluation function
__all__ = [
    "gsm8k_router_task",
    "gsm8k_router_qwen_deepseek",
]
