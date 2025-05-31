#!/usr/bin/env python3
"""
Example usage of VLLMRouter for routing queries between multiple vLLM models.

This example demonstrates:
1. Setting up multiple vLLM models
2. Configuring the router with routing weights
3. Generating responses with automatic model selection
4. Batch processing with routing
"""

import asyncio
from inspect_ai.model._providers.model_router import VLLMRouter
from inspect_ai.model._generate_config import GenerateConfig
from inspect_ai.model._chat_message import ChatMessage


async def main():
    """Example usage of VLLMRouter."""

    # Define models to use
    models = [
        "microsoft/DialoGPT-medium",  # Model 0 - good for conversation
        "microsoft/DialoGPT-small",  # Model 1 - faster but less capable
    ]

    # Optional: specify ports for each model
    ports = [8001, 8002]

    # Configure routing
    routing_config = {
        "d_embedding": 128,
        "text_dim": 1536,
        "embedding_model": "text-embedding-3-small",
        "use_proj": True,
        # "weights_path": "/path/to/trained/router/weights.pt"  # Optional: pre-trained weights
    }

    # Create router
    router = VLLMRouter(
        models=models,
        ports=ports,
        config=GenerateConfig(max_tokens=100, temperature=0.7),
        model_args={"routing_config": routing_config},
    )

    try:
        print("VLLMRouter initialized successfully!")
        print(f"Managing models: {router.model_names_list}")
        print(f"Model stats: {router.get_model_stats()}")

        # Example 1: Single query
        print("\n=== Single Query Example ===")
        messages = [ChatMessage(role="user", content="What is the capital of France?")]

        result = await router.generate(
            input=messages,
            tools=[],
            tool_choice="auto",
            config=GenerateConfig(max_tokens=50),
        )

        if isinstance(result, tuple):
            output, model_call = result
            routed_model = model_call.request.get("routed_to_model", "unknown")
            print(f"Response from {routed_model}: {output.content}")
        else:
            print(f"Response: {result.content}")

        # Example 2: Batch queries
        print("\n=== Batch Query Example ===")
        batch_messages = [
            [ChatMessage(role="user", content="Tell me a joke")],
            [ChatMessage(role="user", content="Explain quantum physics")],
            [ChatMessage(role="user", content="What's the weather like?")],
        ]

        batch_results = await router.generate_batch(
            inputs=batch_messages,
            tools=[],
            tool_choice="auto",
            config=GenerateConfig(max_tokens=50),
        )

        for i, result in enumerate(batch_results):
            if isinstance(result, tuple):
                output, model_call = result
                routed_model = model_call.request.get("routed_to_model", "unknown")
                print(f"Query {i + 1} -> {routed_model}: {output.content[:100]}...")
            else:
                print(f"Query {i + 1}: {result.content[:100]}...")

        # Example 3: Different types of queries to see routing decisions
        print("\n=== Routing Decision Examples ===")
        test_queries = [
            "Write a simple Python function",  # Technical query
            "How are you feeling today?",  # Conversational query
            "Solve this math problem: 2+2=?",  # Simple query
            "Explain the theory of relativity in detail",  # Complex query
        ]

        for query in test_queries:
            messages = [ChatMessage(role="user", content=query)]
            result = await router.generate(
                input=messages,
                tools=[],
                tool_choice="auto",
                config=GenerateConfig(max_tokens=30),
            )

            if isinstance(result, tuple):
                output, model_call = result
                routed_model = model_call.request.get("routed_to_model", "unknown")
                print(f"'{query[:30]}...' -> {routed_model}")
            else:
                print(f"'{query[:30]}...' -> response received")

    except Exception as e:
        print(f"Error: {e}")

    finally:
        # Clean up
        print("\nCleaning up...")
        await router.aclose()
        print("Router closed successfully!")


if __name__ == "__main__":
    asyncio.run(main())
