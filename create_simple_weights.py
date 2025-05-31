#!/usr/bin/env python3
"""
Create a simple dummy router weights file for testing.
"""

import pickle
import os


def create_simple_weights(output_path: str):
    """Create a simple dummy weights file."""

    # Create a simple dummy state dict
    dummy_weights = {
        "initialized": True,
        "n_models": 2,
        "model_names": ["non_reasoning", "reasoning"],
    }

    # Save as pickle for now
    with open(output_path, "wb") as f:
        pickle.dump(dummy_weights, f)

    print(f"Created simple dummy weights at: {output_path}")


if __name__ == "__main__":
    weights_path = "/home/ubuntu/inspect_ai/router_weights.pt"
    os.makedirs(os.path.dirname(weights_path), exist_ok=True)
    create_simple_weights(weights_path)
