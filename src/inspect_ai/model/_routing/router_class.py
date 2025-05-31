"""
Router class for VLLMRouter using matrix factorization approach.
"""

import torch
import torch.nn as nn
import torch.nn.functional as F
from typing import List, Optional
from dataclasses import dataclass
from huggingface_hub import PyTorchModelHubMixin

try:
    from openai import OpenAI
    OPENAI_CLIENT = OpenAI()
except ImportError:
    OPENAI_CLIENT = None


@dataclass
class RouterClassConfig:
    """Configuration for RouterClass."""
    n_models: int
    d_embedding: int = 128  # Changed to match RouteLL default
    text_dim: int = 1536  # OpenAI embedding dimension
    embedding_model: str = "text-embedding-3-small"
    use_proj: bool = True
    num_classes: int = 1


class RouterClass(nn.Module, PyTorchModelHubMixin):
    """
    Router for model selection based on predicted accuracy.
    """
    
    def __init__(self, config: RouterClassConfig):
        super().__init__()
        self.config = config
        self._name = "AccuracyRouter"
        self.use_proj = config.use_proj
        self.embedding_model = config.embedding_model
        
        # Model embeddings
        self.P = nn.Embedding(config.n_models, config.d_embedding)
        
        # Text projection layer
        if self.use_proj:
            self.text_proj = nn.Sequential(
                nn.Linear(config.text_dim, config.d_embedding, bias=False)
            )
        else:
            assert config.text_dim == config.d_embedding, \
                f"text_dim {config.text_dim} must equal d_embedding {config.d_embedding} if not using projection"
        
        # Classifier - predicts accuracy probability
        self.classifier = nn.Sequential(
            nn.Linear(config.d_embedding, 1, bias=True)
        )
        
        # Initialize OpenAI client if available
        if OPENAI_CLIENT is None:
            raise RuntimeError("OpenAI client not available. Please install openai package.")
    
    def get_device(self):
        """Get the device of the model."""
        return self.P.weight.device
    
    async def _get_embeddings(self, queries: List[str]) -> torch.Tensor:
        """Get embeddings for a batch of queries using OpenAI API."""
        try:
            response = OPENAI_CLIENT.embeddings.create(
                model=self.embedding_model,
                input=queries
            )
            
            # Extract embeddings and convert to tensor
            embeddings = [data.embedding for data in response.data]
            embeddings_tensor = torch.tensor(embeddings, dtype=torch.float32, device=self.get_device())
            
            return embeddings_tensor
        except Exception as e:
            raise RuntimeError(f"Failed to get embeddings from OpenAI: {e}")
    
    def forward(self, model_ids: List[int], prompt: str) -> torch.Tensor:
        """
        Forward pass for pairwise comparison.
        
        Args:
            model_ids: List of model indices to compare
            prompt: Input prompt string
            
        Returns:
            Logits for model comparison
        """
        model_ids_tensor = torch.tensor(model_ids, dtype=torch.long, device=self.get_device())
        
        # Get model embeddings
        model_embeds = self.P(model_ids_tensor)
        model_embeds = F.normalize(model_embeds, p=2, dim=1)
        
        # Get prompt embedding
        prompt_embed = OPENAI_CLIENT.embeddings.create(
            input=[prompt], 
            model=self.embedding_model
        ).data[0].embedding
        prompt_embed = torch.tensor(prompt_embed, device=self.get_device())
        
        # Apply projection if needed
        if self.use_proj:
            prompt_embed = self.text_proj(prompt_embed)
        
        # Compute logits for each model
        logits = self.classifier(model_embeds * prompt_embed.unsqueeze(0)).squeeze()
        return logits
    
    @torch.no_grad()
    def pred_win_rate(self, model_a: int, model_b: int, prompt: str) -> float:
        """
        Predict win rate of model_a vs model_b on given prompt.
        
        Args:
            model_a: Index of first model
            model_b: Index of second model
            prompt: Input prompt
            
        Returns:
            Win rate probability (0-1)
        """
        logits = self.forward([model_a, model_b], prompt)
        winrate = torch.sigmoid(logits[0] - logits[1]).item()
        return winrate
    
    async def forward_batch(self, queries: List[str]) -> List[int]:
        """
        Route a batch of queries to models with highest predicted accuracy.
        
        Args:
            queries: List of query strings
            
        Returns:
            List of model indices for each query
        """
        if len(queries) == 0:
            return []
        
        # Get embeddings for all queries
        query_embeddings = await self._get_embeddings(queries)
        
        # Apply projection if needed
        if self.use_proj:
            query_embeddings = self.text_proj(query_embeddings)
        
        # Get all model embeddings
        all_model_ids = torch.arange(self.config.n_models, device=self.get_device())
        model_embeds = self.P(all_model_ids)
        model_embeds = F.normalize(model_embeds, p=2, dim=1)
        
        # Compute accuracy predictions for all query-model pairs
        accuracy_scores = []
        for query_embed in query_embeddings:
            # Compute scores for this query with all models
            combined = model_embeds * query_embed.unsqueeze(0)
            query_scores = torch.sigmoid(self.classifier(combined)).squeeze()
            accuracy_scores.append(query_scores)
        
        accuracy_scores = torch.stack(accuracy_scores)  # (batch_size, n_models)
        
        # Select model with highest predicted accuracy for each query
        selected_models = torch.argmax(accuracy_scores, dim=1)
        return selected_models.tolist()
    
    def load_weights(self, path: str):
        """Load trained weights from file."""
        self.load_state_dict(torch.load(path, map_location=self.get_device()))




