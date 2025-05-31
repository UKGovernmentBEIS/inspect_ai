"""
Example usage of the Matrix Factorization Router.

This example demonstrates how to:
1. Create a router configuration
2. Use the router to route queries to different models
3. Analyze routing scores for debugging
"""

import asyncio
import torch
import numpy as np
from src.inspect_ai.model._routing.router_class import RouterClass, RouterClassConfig


async def create_sample_routing_matrix(n_models: int = 3, d_embedding: int = 1536, save_path: str = "sample_routing_matrix.pt"):
    """Create a sample routing matrix for demonstration purposes."""
    # Create a random matrix with some structure
    # In practice, this would be learned from training data
    routing_matrix = torch.randn(n_models, d_embedding)
    
    # Normalize rows to unit vectors for better routing behavior
    routing_matrix = torch.nn.functional.normalize(routing_matrix, p=2, dim=1)
    
    # Save the matrix
    torch.save(routing_matrix, save_path)
    print(f"Sample routing matrix saved to {save_path}")
    return save_path


async def main():
    # Step 1: Create a sample routing matrix (in practice, this would be pre-trained)
    matrix_path = await create_sample_routing_matrix()
    
    # Step 2: Configure the router
    config = RouterClassConfig(
        model_config={
            "embedding_model": "text-embedding-3-small"  # OpenAI embedding model
        },
        router_config={
            "router_path": matrix_path,
            "n_models": 3,
            "d_embedding": 1536  # Dimension for text-embedding-3-small
        }
    )
    
    # Step 3: Use the router
    async with RouterClass(config) as router:
        # Example queries that might route to different models
        queries = [
            "What is the capital of France?",  # Factual question
            "Write a creative story about a dragon",  # Creative task
            "Solve this math problem: 2x + 5 = 15",  # Mathematical reasoning
            "Translate 'hello' to Spanish",  # Translation task
        ]
        
        print("Routing queries...")
        print("-" * 50)
        
        # Route all queries at once
        model_indices = await router.forward(queries)
        
        for query, model_idx in zip(queries, model_indices):
            print(f"Query: {query[:50]}...")
            print(f"Routed to model: {model_idx}")
            print()
        
        # Route a single query
        single_query = "What's the weather like today?"
        single_result = await router.route_single(single_query)
        print(f"Single query routing:")
        print(f"Query: {single_query}")
        print(f"Routed to model: {single_result}")
        print()
        
        # Get detailed routing scores for analysis
        print("Detailed routing scores:")
        print("-" * 30)
        query_embeddings = await router._get_embeddings(queries[:2])  # Just first 2 for brevity
        scores = router.get_routing_scores(query_embeddings)
        
        for i, (query, score_row) in enumerate(zip(queries[:2], scores)):
            print(f"Query {i+1}: {query[:30]}...")
            for model_idx, score in enumerate(score_row):
                print(f"  Model {model_idx}: {score:.4f}")
            print()


if __name__ == "__main__":
    # Make sure you have OPENAI_API_KEY set in your environment
    import os
    if not os.getenv("OPENAI_API_KEY"):
        print("Warning: OPENAI_API_KEY environment variable not set")
        print("Please set it before running this example")
    else:
        asyncio.run(main()) 