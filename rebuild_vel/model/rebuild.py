"""Supervised raw-to-surface velocity reconstruction model."""

from __future__ import annotations

from typing import Dict, Optional

import torch
import torch.nn as nn

from .encoder import HydroSectionEncoder


class RebuildVelocityModel(nn.Module):
    """Per-line surface-velocity regression head on top of the encoder."""

    def __init__(
        self,
        d_model: int = 256,
        num_heads: int = 8,
        num_layers: int = 6,
        ffn_dim: int = 512,
        dropout: float = 0.1,
        beta_x: float = 1.0,
        beta_d: float = 0.5,
        beta_bank: float = 0.5,
        beta_grad: float = 0.25,
        init_std: float = 0.02,
        raw_hidden: int = 64,
        encoder: Optional[HydroSectionEncoder] = None,
    ) -> None:
        super().__init__()
        self.encoder = encoder or HydroSectionEncoder(
            d_model=d_model,
            num_heads=num_heads,
            num_layers=num_layers,
            ffn_dim=ffn_dim,
            dropout=dropout,
            beta_x=beta_x,
            beta_d=beta_d,
            beta_bank=beta_bank,
            beta_grad=beta_grad,
            init_std=init_std,
            raw_hidden=raw_hidden,
        )
        self.reconstruction_head = nn.Linear(d_model, 1)
        nn.init.trunc_normal_(self.reconstruction_head.weight, std=init_std)
        nn.init.zeros_(self.reconstruction_head.bias)

    def forward(
        self,
        morphology: torch.Tensor,
        raw_stats: torch.Tensor,
        raw_seq_v: torch.Tensor,
        raw_seq_valid: torch.Tensor,
        line_mask: torch.Tensor,
        global_features: torch.Tensor,
    ) -> Dict[str, torch.Tensor]:
        encoded = self.encoder(
            morphology, raw_stats, raw_seq_v, raw_seq_valid,
            line_mask, global_features,
        )
        velocity_pred = self.reconstruction_head(encoded["point_embeddings"]).squeeze(-1)
        return {"velocity_pred": velocity_pred, **encoded}

    def forward_batch(self, batch: Dict[str, torch.Tensor]) -> Dict[str, torch.Tensor]:
        return self(
            morphology=batch["morphology"],
            raw_stats=batch["raw_stats"],
            raw_seq_v=batch["raw_seq_v"],
            raw_seq_valid=batch["raw_seq_valid"],
            line_mask=batch["line_mask"],
            global_features=batch["global_features"],
        )
