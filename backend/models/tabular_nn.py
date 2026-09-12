"""Deep Tabular Neural Network architecture for popularity prediction."""
import torch
import torch.nn as nn


class PopularityTabularNN(nn.Module):
    """Deep Tabular Neural Network with Entity Embeddings and Residual connections."""

    def __init__(
        self,
        num_categories: int = 14,
        num_media_types: int = 4,
        num_continuous: int = 31,
        cat_embed_dim: int = 16,
        media_embed_dim: int = 8,
        weekend_embed_dim: int = 4,
        hidden_dim: int = 256,
    ):
        super().__init__()

        # Entity Embeddings
        self.category_embed = nn.Embedding(num_categories, cat_embed_dim)
        self.media_embed = nn.Embedding(num_media_types, media_embed_dim)
        self.weekend_embed = nn.Embedding(2, weekend_embed_dim)

        total_embed_dim = cat_embed_dim + media_embed_dim + weekend_embed_dim
        input_dim = total_embed_dim + num_continuous

        # Input projection
        self.input_bn = nn.BatchNorm1d(num_continuous)
        self.fc_in = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.BatchNorm1d(hidden_dim),
            nn.GELU(),
            nn.Dropout(0.15),
        )

        # Residual Block
        self.res_fc1 = nn.Linear(hidden_dim, hidden_dim)
        self.res_bn1 = nn.BatchNorm1d(hidden_dim)
        self.res_act1 = nn.GELU()
        self.res_drop1 = nn.Dropout(0.15)
        self.res_fc2 = nn.Linear(hidden_dim, hidden_dim)
        self.res_bn2 = nn.BatchNorm1d(hidden_dim)
        self.res_act2 = nn.GELU()

        # Head
        self.head = nn.Sequential(
            nn.Linear(hidden_dim, 128),
            nn.BatchNorm1d(128),
            nn.GELU(),
            nn.Dropout(0.10),
            nn.Linear(128, 64),
            nn.GELU(),
            nn.Linear(64, 1),
        )

    def forward(
        self,
        cat_ids: torch.Tensor,
        media_ids: torch.Tensor,
        weekend_ids: torch.Tensor,
        continuous_feats: torch.Tensor,
    ) -> torch.Tensor:
        # Embeddings
        e_cat = self.category_embed(cat_ids)
        e_media = self.media_embed(media_ids)
        e_weekend = self.weekend_embed(weekend_ids)

        # Normalize continuous features
        norm_cont = self.input_bn(continuous_feats)

        # Concatenate
        x = torch.cat([e_cat, e_media, e_weekend, norm_cont], dim=-1)

        # Input block
        h = self.fc_in(x)

        # Residual block
        res = self.res_act1(self.res_bn1(self.res_fc1(h)))
        res = self.res_drop1(res)
        res = self.res_bn2(self.res_fc2(res))
        h = self.res_act2(h + res)

        # Output prediction
        out = self.head(h)
        return out.squeeze(-1)
