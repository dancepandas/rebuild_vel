"""Input embeddings for raw-to-surface velocity reconstruction.

Each speed line becomes a token whose representation sums four pathways:

* morphology projection   (x, depth, bank, gradient)
* raw-statistics projection (coverage/mean/std/quantiles/angle - deliberately
  no confidence features, the platform confidence criterion is unreliable)
* raw-segment sequence encoding (per-segment MLP over [v, valid], masked
  mean pooling) - the core "原始流速" pathway
* section globals         (water level, max depth, width, original-value prop)
  added to the [SECTION] token

No line-source (algorithm vs interpolated) embedding: whatever raw
observations exist are the input; source flags carry no reconstruction signal.
Padding is handled purely by ``line_mask``.
"""

from __future__ import annotations

import torch
import torch.nn as nn

from ..dataset import N_GLOBAL, N_RAW_STATS


class RawSegmentEncoder(nn.Module):
    """Encode the per-video-segment raw velocity sequence of one line."""

    def __init__(self, hidden: int = 64, dropout: float = 0.1) -> None:
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(2, hidden),
            nn.GELU(),
            nn.Linear(hidden, hidden),
            nn.GELU(),
        )
        self.out = nn.Linear(hidden, hidden)
        self.dropout = nn.Dropout(dropout)
        self.hidden = hidden

    def forward(
        self,
        raw_v: torch.Tensor,        # [B, K, S] standardized raw velocities
        raw_valid: torch.Tensor,    # [B, K, S]
    ) -> torch.Tensor:
        features = torch.cat([
            raw_v.unsqueeze(-1),
            raw_valid.unsqueeze(-1),
        ], dim=-1)
        encoded = self.net(features)                     # [B, K, S, H]
        weights = raw_valid.unsqueeze(-1)                # plain masked pooling
        pooled = (encoded * weights).sum(dim=2) / weights.sum(dim=2).clamp(min=1e-6)
        no_signal = weights.sum(dim=2).squeeze(-1) < 1e-6
        pooled = pooled * (~no_signal).unsqueeze(-1).to(pooled.dtype)
        return self.dropout(self.out(pooled))


class SectionEmbeddings(nn.Module):
    """Embed line morphology, raw observations, and section globals."""

    def __init__(
        self,
        d_model: int,
        dropout: float = 0.1,
        raw_hidden: int = 64,
        n_raw_stats: int = N_RAW_STATS,
        n_global: int = N_GLOBAL,
    ) -> None:
        super().__init__()
        self.morphology_proj = nn.Linear(4, d_model)
        self.raw_stats_proj = nn.Linear(n_raw_stats, d_model)
        self.raw_segment_encoder = RawSegmentEncoder(raw_hidden, dropout)
        self.raw_proj = nn.Linear(raw_hidden, d_model)
        self.global_proj = nn.Linear(n_global, d_model)
        self.section_token = nn.Parameter(torch.empty(1, 1, d_model))
        self.dropout = nn.Dropout(dropout)

    def forward(
        self,
        morphology: torch.Tensor,     # [B, K, 4]
        raw_stats: torch.Tensor,      # [B, K, F]
        raw_seq_v: torch.Tensor,      # [B, K, S]
        raw_seq_valid: torch.Tensor,  # [B, K, S]
        line_mask: torch.Tensor,      # [B, K]
        global_features: torch.Tensor,  # [B, G]
    ) -> torch.Tensor:
        if morphology.ndim != 3 or morphology.shape[-1] != 4:
            raise ValueError("morphology must have shape [B, K, 4]")
        batch, points, _ = morphology.shape
        if raw_stats.shape[:2] != (batch, points):
            raise ValueError("raw_stats must align with morphology")
        if line_mask.shape != (batch, points):
            raise ValueError("line_mask must have shape [B, K]")

        padding = ~line_mask.bool()
        safe_stats = raw_stats.masked_fill(padding.unsqueeze(-1), 0.0)
        raw_embed = self.raw_segment_encoder(raw_seq_v, raw_seq_valid)
        raw_embed = raw_embed.masked_fill(padding.unsqueeze(-1), 0.0)

        point_hidden = (
            self.morphology_proj(morphology)
            + self.raw_stats_proj(safe_stats)
            + self.raw_proj(raw_embed)
        )
        point_hidden = self.dropout(point_hidden)
        point_hidden = point_hidden * line_mask.unsqueeze(-1).to(point_hidden.dtype)

        section_hidden = self.section_token.expand(batch, -1, -1)
        section_hidden = section_hidden + self.global_proj(global_features).unsqueeze(1)
        section_hidden = self.dropout(section_hidden)
        return torch.cat([section_hidden, point_hidden], dim=1)
