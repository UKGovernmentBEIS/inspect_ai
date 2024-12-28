# run_hellaswag.py
import asyncio
from inspect_ai import eval_async
from inspect_ai.model._providers.noise_hf import NoiseHuggingFaceAPI


async def main():
    # Create model with direct noise params
    model = NoiseHuggingFaceAPI(
        model_name="microsoft/Phi-3-mini-4k-instruct",
        noise_std=0.00,
        noise_percentage=1.0,
    )

    # Run eval with this model
    await eval_async(
        tasks="sandbag_hellaswag.py",  # Path to your task file
        model=model,  # Pass the configured model directly
    )


if __name__ == "__main__":
    asyncio.run(main())
