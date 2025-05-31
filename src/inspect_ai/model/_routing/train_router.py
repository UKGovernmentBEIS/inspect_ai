"""
Training script for VLLMRouter using binary accuracy labels.

This module provides functionality to train routing matrices for the VLLMRouter
based on evaluation datasets and model performance characteristics.
"""

import asyncio
import json
import random
import numpy as np
import pandas as pd  # Add pandas import
import torch
import torch.nn as nn
import torch.nn.functional as F
from torch.optim import Adam
from torch.utils.data import DataLoader, Dataset
from tqdm import tqdm
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

from inspect_ai.model import get_model
from inspect_ai.model._routing.router_class import RouterClass, RouterClassConfig

# Set random seeds for reproducibility
torch.manual_seed(42)
np.random.seed(42)
random.seed(42)


@dataclass
class TrainingConfig:
    """Configuration for router training."""

    train_csv_path: str  # Changed from dataset_name to CSV paths
    test_csv_path: Optional[str] = None  # Optional test CSV
    models: Dict[str, str]  # model_name -> model_path
    embedding_model: str = "text-embedding-3-small"
    num_samples: Optional[int] = None
    output_path: str = "router_weights.pt"

    # Training hyperparameters
    dim: int = 128
    batch_size: int = 64
    num_epochs: int = 100
    learning_rate: float = 3e-4
    weight_decay: float = 1e-5
    alpha: float = 0.1  # Noise factor for training stability
    use_proj: bool = True

    # Data split (only used if test_csv_path is None)
    train_split: float = 0.95


class AccuracyDataset(Dataset):
    """Dataset for query-model accuracy pairs."""

    def __init__(self, data: List[dict], model_ids: Dict[str, int]):
        """
        Args:
            data: List of dicts with keys: 'query_idx', 'model_name', 'is_correct'
            model_ids: Mapping from model names to indices
        """
        self.model_ids = model_ids
        self.query_indices = torch.tensor(
            [sample["query_idx"] for sample in data], dtype=torch.int64
        )
        self.model_indices = torch.tensor(
            [model_ids[sample["model_name"]] for sample in data], dtype=torch.int64
        )
        self.labels = torch.tensor(
            [float(sample["is_correct"]) for sample in data], dtype=torch.float32
        )

    def __len__(self):
        return len(self.query_indices)

    def __getitem__(self, index):
        return self.query_indices[index], self.model_indices[index], self.labels[index]

    def get_dataloader(self, batch_size: int, shuffle: bool = True) -> DataLoader:
        return DataLoader(self, batch_size, shuffle=shuffle)


class AccuracyTrainingModel(nn.Module):
    """Model for training on binary accuracy labels."""

    def __init__(
        self,
        dim: int,
        num_models: int,
        num_queries: int,
        text_dim: int = 1536,
        use_proj: bool = True,
        embeddings_path: Optional[str] = None,
    ):
        super().__init__()
        self.use_proj = use_proj

        # Model embeddings
        self.P = nn.Embedding(num_models, dim)

        # Query embeddings (frozen during training)
        self.Q = nn.Embedding(num_queries, text_dim).requires_grad_(False)
        if embeddings_path and Path(embeddings_path).exists():
            embeddings = np.load(embeddings_path)
            self.Q.weight.data.copy_(torch.tensor(embeddings))

        # Text projection
        if self.use_proj:
            self.text_proj = nn.Linear(text_dim, dim, bias=False)
        else:
            assert text_dim == dim, (
                f"text_dim {text_dim} must equal dim {dim} if not using projection"
            )

        # Classifier - predicts probability of correctness
        self.classifier = nn.Linear(
            dim, 1, bias=True
        )  # Added bias for better calibration

    def get_device(self):
        return self.P.weight.device

    def forward(self, query_ids, model_ids, test=False, alpha=0.05):
        """
        Forward pass for accuracy prediction.

        Args:
            query_ids: Tensor of query indices
            model_ids: Tensor of model indices
            test: Whether in test mode (no noise)
            alpha: Noise factor for training

        Returns:
            Logits predicting accuracy for each query-model pair
        """
        query_ids = query_ids.to(self.get_device())
        model_ids = model_ids.to(self.get_device())

        # Get embeddings
        model_embeds = self.P(model_ids)
        model_embeds = F.normalize(model_embeds, p=2, dim=1)

        query_embeds = self.Q(query_ids)
        if not test:
            # Add noise for training stability
            query_embeds += torch.randn_like(query_embeds) * alpha

        if self.use_proj:
            query_embeds = self.text_proj(query_embeds)

        # Element-wise multiplication and classification
        combined = model_embeds * query_embeds
        logits = self.classifier(combined).squeeze()

        return logits

    @torch.no_grad()
    def predict_accuracy(self, query_ids, model_ids):
        """Predict accuracy probability for query-model pairs."""
        logits = self.forward(query_ids, model_ids, test=True)
        return torch.sigmoid(logits)


class RouterTrainer:
    """Trainer for VLLMRouter using binary accuracy labels."""

    def __init__(self, config: TrainingConfig):
        self.config = config
        # Extract model names from CSV column names (score_match_reasoning, score_match_non_reasoning)
        # We'll determine this when loading the CSV
        self.model_names = []
        self.model_ids = {}

        # Router config for final model (will be set after loading CSV)
        self.router_config = None

    def load_csv_data(self) -> Tuple[pd.DataFrame, Optional[pd.DataFrame]]:
        """Load training and optionally test CSV data."""
        print(f"Loading training data from {self.config.train_csv_path}...")
        train_df = pd.read_csv(self.config.train_csv_path)

        test_df = None
        if self.config.test_csv_path:
            print(f"Loading test data from {self.config.test_csv_path}...")
            test_df = pd.read_csv(self.config.test_csv_path)

        # Extract model names from score columns
        score_columns = [
            col for col in train_df.columns if col.startswith("score_match_")
        ]
        self.model_names = [col.replace("score_match_", "") for col in score_columns]
        self.model_ids = {name: i for i, name in enumerate(self.model_names)}

        print(f"Found models: {self.model_names}")

        # Set up router config now that we know the number of models
        self.router_config = RouterClassConfig(
            n_models=len(self.model_names),
            d_embedding=self.config.dim,
            text_dim=1536 if "small" in self.config.embedding_model else 3072,
            embedding_model=self.config.embedding_model,
            use_proj=self.config.use_proj,
        )

        return train_df, test_df

    def prepare_accuracy_data(self, df: pd.DataFrame) -> List[dict]:
        """Convert CSV data to accuracy data format."""
        accuracy_data = []

        for query_idx, row in df.iterrows():
            for model_name in self.model_names:
                score_col = f"score_match_{model_name}"
                # Convert score to binary (assuming 'C' = correct = True, others = False)
                is_correct = row[score_col] == "C"

                accuracy_data.append(
                    {
                        "query_idx": query_idx,
                        "model_name": model_name,
                        "is_correct": is_correct,
                    }
                )

        return accuracy_data

    def get_query_embeddings(self, df: pd.DataFrame) -> np.ndarray:
        """Get embeddings for all queries in the dataframe."""
        print("Getting query embeddings...")
        from openai import OpenAI

        client = OpenAI()

        embeddings = []
        for _, row in tqdm(df.iterrows(), total=len(df), desc="Embedding queries"):
            query = row["query"]
            embedding = (
                client.embeddings.create(
                    input=[query], model=self.config.embedding_model
                )
                .data[0]
                .embedding
            )
            embeddings.append(embedding)

        return np.array(embeddings)

    async def train_router(self):
        """Train the routing matrix using CSV accuracy data."""
        # Load CSV data
        train_df, test_df = self.load_csv_data()

        # Limit samples if specified
        if self.config.num_samples:
            train_df = train_df.head(self.config.num_samples)
            if test_df is not None:
                test_df = test_df.head(self.config.num_samples)

        # Get query embeddings for training data
        query_embeddings = self.get_query_embeddings(train_df)

        # Save query embeddings
        embeddings_path = "query_embeddings.npy"
        np.save(embeddings_path, query_embeddings)

        # Prepare accuracy data
        train_accuracy_data = self.prepare_accuracy_data(train_df)

        if test_df is not None:
            # Use provided test set
            test_query_embeddings = self.get_query_embeddings(test_df)
            # For test data, we need to adjust query indices to be relative to combined embeddings
            test_accuracy_data = []
            for item in self.prepare_accuracy_data(test_df):
                item["query_idx"] += len(train_df)  # Offset by training data size
                test_accuracy_data.append(item)

            # Combine embeddings
            all_embeddings = np.vstack([query_embeddings, test_query_embeddings])
            np.save(embeddings_path, all_embeddings)
        else:
            # Split training data
            random.shuffle(train_accuracy_data)
            split_idx = int(len(train_accuracy_data) * self.config.train_split)
            test_accuracy_data = train_accuracy_data[split_idx:]
            train_accuracy_data = train_accuracy_data[:split_idx]

        # Create data loaders
        train_dataset = AccuracyDataset(train_accuracy_data, self.model_ids)
        test_dataset = AccuracyDataset(test_accuracy_data, self.model_ids)
        train_loader = train_dataset.get_dataloader(
            self.config.batch_size, shuffle=True
        )
        test_loader = test_dataset.get_dataloader(1024, shuffle=False)

        # Initialize training model
        device = "cuda" if torch.cuda.is_available() else "cpu"
        num_queries = (
            len(query_embeddings)
            if test_df is None
            else len(query_embeddings) + len(test_df)
        )

        training_model = AccuracyTrainingModel(
            dim=self.config.dim,
            num_models=len(self.model_ids),
            num_queries=num_queries,
            use_proj=self.config.use_proj,
            embeddings_path=embeddings_path,
        ).to(device)

        # Training setup
        optimizer = Adam(
            training_model.parameters(),
            lr=self.config.learning_rate,
            weight_decay=self.config.weight_decay,
        )
        loss_fn = nn.BCEWithLogitsLoss(reduction="mean")

        # Training loop
        print("Starting training...")
        best_test_acc = -1
        progress_bar = tqdm(total=self.config.num_epochs)

        for epoch in range(self.config.num_epochs):
            train_loss = self._train_epoch(
                training_model,
                train_loader,
                optimizer,
                loss_fn,
                device,
                self.config.alpha,
            )
            test_loss, test_acc = self._evaluator(training_model, test_loader, device)

            if test_acc > best_test_acc:
                best_test_acc = test_acc
                # Save best model
                self._save_router_weights(training_model)

            progress_bar.set_postfix(
                {
                    "train_loss": f"{train_loss:.4f}",
                    "test_loss": f"{test_loss:.4f}",
                    "test_acc": f"{test_acc:.4f}",
                    "best_acc": f"{best_test_acc:.4f}",
                }
            )
            progress_bar.update(1)

        progress_bar.close()
        print(f"Training completed. Best test accuracy: {best_test_acc:.4f}")

    def _evaluator(self, net, test_loader, device):
        """Evaluate model performance on test set."""
        net.eval()
        loss_fn = nn.BCEWithLogitsLoss(reduction="sum")
        total_loss = 0.0
        correct = 0
        num_samples = 0

        with torch.no_grad():
            for query_ids, model_ids, labels in test_loader:
                query_ids = query_ids.to(device)
                model_ids = model_ids.to(device)
                labels = labels.to(device)

                logits = net(query_ids, model_ids, test=True)
                loss = loss_fn(logits, labels)

                # Accuracy calculation
                predictions = (torch.sigmoid(logits) > 0.5).float()
                correct += (predictions == labels).sum().item()
                total_loss += loss.item()
                num_samples += labels.shape[0]

        net.train()
        return total_loss / num_samples, correct / num_samples

    def _train_epoch(self, net, train_loader, optimizer, loss_fn, device, alpha):
        """Train for one epoch."""
        net.train()
        total_loss = 0.0
        num_samples = 0

        for query_ids, model_ids, labels in train_loader:
            query_ids = query_ids.to(device)
            model_ids = model_ids.to(device)
            labels = labels.to(device)

            logits = net(query_ids, model_ids, alpha=alpha)
            loss = loss_fn(logits, labels)

            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

            total_loss += loss.item() * len(labels)
            num_samples += len(labels)

        return total_loss / num_samples

    def _save_router_weights(self, training_model):
        """Save trained weights for inference router."""
        # Create inference router
        inference_router = RouterClass(self.router_config)

        # Copy weights from training model
        inference_router.P.weight.data.copy_(training_model.P.weight.data)
        if self.config.use_proj:
            inference_router.text_proj[0].weight.data.copy_(
                training_model.text_proj.weight.data
            )
        inference_router.classifier[0].weight.data.copy_(
            training_model.classifier.weight.data
        )
        inference_router.classifier[0].bias.data.copy_(
            training_model.classifier.bias.data
        )

        # Save model
        torch.save(
            {
                "model_state_dict": inference_router.state_dict(),
                "config": self.router_config.__dict__,
                "model_ids": self.model_ids,
            },
            self.config.output_path,
        )

        print(f"Saved router weights to {self.config.output_path}")


async def train_router_cli():
    """CLI interface for training routers."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Train VLLMRouter using CSV accuracy data"
    )
    parser.add_argument("--train-csv", required=True, help="Path to training CSV file")
    parser.add_argument("--test-csv", help="Path to test CSV file (optional)")
    parser.add_argument(
        "--output", default="router_weights.pt", help="Output file path"
    )
    parser.add_argument("--samples", type=int, help="Number of samples to use")
    parser.add_argument("--epochs", type=int, default=100, help="Training epochs")
    parser.add_argument("--lr", type=float, default=3e-4, help="Learning rate")
    parser.add_argument("--dim", type=int, default=128, help="Embedding dimension")
    parser.add_argument("--batch-size", type=int, default=64, help="Batch size")

    args = parser.parse_args()

    config = TrainingConfig(
        train_csv_path=args.train_csv,
        test_csv_path=args.test_csv,
        models={},  # Will be determined from CSV columns
        output_path=args.output,
        num_samples=args.samples,
        num_epochs=args.epochs,
        learning_rate=args.lr,
        dim=args.dim,
        batch_size=args.batch_size,
    )

    trainer = RouterTrainer(config)
    await trainer.train_router()


if __name__ == "__main__":
    asyncio.run(train_router_cli())
