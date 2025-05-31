#!/usr/bin/env python3
"""
Create dummy router weights for testing the VLLMRouter.
This creates a minimal weights file that can be loaded by the router.
"""

import torch
import os


def create_dummy_router_weights(
    output_path: str, n_models: int = 2, d_embedding: int = 128
):
    """Create dummy router weights for testing."""

    # Create dummy state dict matching RouterClass structure
    state_dict = {
        # Model embeddings (n_models x d_embedding)
        "P.weight": torch.randn(n_models, d_embedding),
        # Text projection layer (if using projection)
        "text_proj.0.weight": torch.randn(d_embedding, 1536),  # 1536 is text_dim
        # Classifier weights (d_embedding -> 1)
        "classifier.0.weight": torch.randn(1, d_embedding),
        "classifier.0.bias": torch.randn(1),
    }

    # Save the weights
    torch.save(state_dict, output_path)
    print(f"Created dummy router weights at: {output_path}")
    print(f"Weights for {n_models} models with {d_embedding} embedding dimensions")


if __name__ == "__main__":
    # Create the weights file referenced in the command
    weights_path = "/home/ubuntu/inspect_ai/router_weights.pt"

    # Ensure directory exists
    os.makedirs(os.path.dirname(weights_path), exist_ok=True)

    # Create dummy weights for 2 models (reasoning and non_reasoning)
    create_dummy_router_weights(weights_path, n_models=2, d_embedding=128)
