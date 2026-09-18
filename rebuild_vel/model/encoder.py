"""Unified bidirectional encoder for complete river cross-sections."""

from __future__ import annotations

from typing import Dict

import torch
import torch.nn as nn

from .attention import EncoderBlock, RMSNorm
from .embeddings import SectionEmbeddings


class HydroSectionEncoder(nn.Module):
    """Encode all speed lines jointly; expose line- and section-level states."""

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
    ) -> None:
        super().__init__()
        if num_layers < 1:
            raise ValueError("num_layers must be positive")
        self.init_std = float(init_std)
        self.embeddings = SectionEmbeddings(d_model, dropout, raw_hidden=raw_hidden)
        self.layers = nn.ModuleList([
            EncoderBlock(
                d_model, num_heads, ffn_dim, dropout,
                beta_x, beta_d, beta_bank, beta_grad,
            )
            for _ in range(num_layers)
        ])
        self.final_norm = RMSNorm(d_model)
        self.apply(self._initialize_module)
        nn.init.trunc_normal_(self.embeddings.section_token, std=self.init_std)

    def _initialize_module(self, module: nn.Module) -> None:
        if isinstance(module, (nn.Linear, nn.Embedding)):
            nn.init.trunc_normal_(module.weight, std=self.init_std)
            if isinstance(module, nn.Linear) and module.bias is not None:
                nn.init.zeros_(module.bias)
        elif isinstance(module, RMSNorm):
            nn.init.ones_(module.weight)

    def forward(
        self,
        morphology: torch.Tensor,
        raw_stats: torch.Tensor,
        raw_seq_v: torch.Tensor,
        raw_seq_valid: torch.Tensor,
        line_mask: torch.Tensor,
        global_features: torch.Tensor,
    ) -> Dict[str, torch.Tensor]:
        line_mask = line_mask.bool()
        hidden = self.embeddings(
            morphology, raw_stats, raw_seq_v, raw_seq_valid,
            line_mask, global_features,
        )
        section_mask = torch.ones(
            line_mask.shape[0], 1, dtype=torch.bool, device=line_mask.device,
        )
        token_mask = torch.cat([section_mask, line_mask], dim=1)
        for layer in self.layers:
            hidden = layer(hidden, morphology, token_mask)
        hidden = self.final_norm(hidden)
        hidden = hidden * token_mask.unsqueeze(-1).to(hidden.dtype)
        return {
            "point_embeddings": hidden[:, 1:],
            "section_embedding": hidden[:, 0],
        }
