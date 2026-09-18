"""Morphology-aware self-attention and Pre-LN encoder blocks.

Design carried over from the V3 masked-velocity pretraining project: the
one-dimensional ordered structure of a river section is injected into attention
through a learnable four-feature point-pair bias, so no positional encoding is
needed and physically distant points decouple naturally.
"""

from __future__ import annotations

import math

import torch
import torch.nn as nn
import torch.nn.functional as F


class RMSNorm(nn.Module):
    def __init__(self, dim: int, eps: float = 1e-6) -> None:
        super().__init__()
        self.weight = nn.Parameter(torch.ones(dim))
        self.eps = eps

    def forward(self, hidden: torch.Tensor) -> torch.Tensor:
        dtype = hidden.dtype
        hidden = hidden.float()
        hidden = hidden * torch.rsqrt(hidden.pow(2).mean(dim=-1, keepdim=True) + self.eps)
        return (hidden.to(dtype) * self.weight)


class MorphologyBiasedSelfAttention(nn.Module):
    """Multi-head self-attention with a four-feature point-pair bias."""

    def __init__(
        self,
        d_model: int,
        num_heads: int,
        dropout: float = 0.1,
        beta_x: float = 1.0,
        beta_d: float = 0.5,
        beta_bank: float = 0.5,
        beta_grad: float = 0.25,
    ) -> None:
        super().__init__()
        if d_model % num_heads != 0:
            raise ValueError("d_model must be divisible by num_heads")
        self.d_model = d_model
        self.num_heads = num_heads
        self.head_dim = d_model // num_heads
        self.beta_x = nn.Parameter(torch.tensor(float(beta_x)))
        self.beta_d = nn.Parameter(torch.tensor(float(beta_d)))
        self.beta_bank = nn.Parameter(torch.tensor(float(beta_bank)))
        self.beta_grad = nn.Parameter(torch.tensor(float(beta_grad)))
        self.q_proj = nn.Linear(d_model, d_model)
        self.k_proj = nn.Linear(d_model, d_model)
        self.v_proj = nn.Linear(d_model, d_model)
        self.out_proj = nn.Linear(d_model, d_model)
        self.attention_dropout = nn.Dropout(dropout)

    def _morphology_bias(self, morphology: torch.Tensor, dtype: torch.dtype) -> torch.Tensor:
        differences = torch.abs(morphology.unsqueeze(2) - morphology.unsqueeze(1))
        betas = torch.stack([
            self.beta_x.abs(), self.beta_d.abs(),
            self.beta_bank.abs(), self.beta_grad.abs(),
        ]).to(device=morphology.device, dtype=morphology.dtype)
        point_bias = -(differences * betas.view(1, 1, 1, 4)).sum(dim=-1)
        batch, points, _ = morphology.shape
        bias = torch.zeros(
            batch, points + 1, points + 1,
            device=morphology.device, dtype=morphology.dtype,
        )
        bias[:, 1:, 1:] = point_bias
        return bias.to(dtype=dtype).unsqueeze(1)

    def forward(
        self,
        hidden: torch.Tensor,
        morphology: torch.Tensor,
        token_mask: torch.Tensor,
    ) -> torch.Tensor:
        batch, length, _ = hidden.shape
        if morphology.shape != (batch, length - 1, 4):
            raise ValueError("morphology must align with point tokens")
        if token_mask.shape != (batch, length):
            raise ValueError("token_mask must have shape [B, N + 1]")

        def split_heads(tensor: torch.Tensor) -> torch.Tensor:
            return tensor.view(batch, length, self.num_heads, self.head_dim).transpose(1, 2)

        query = split_heads(self.q_proj(hidden))
        key = split_heads(self.k_proj(hidden))
        value = split_heads(self.v_proj(hidden))
        logits = torch.matmul(query, key.transpose(-2, -1)) / math.sqrt(self.head_dim)
        logits = logits + self._morphology_bias(morphology, logits.dtype)
        logits = logits.masked_fill(~token_mask[:, None, None, :], float("-inf"))
        weights = F.softmax(logits, dim=-1)
        weights = self.attention_dropout(weights)
        output = torch.matmul(weights, value)
        output = output.transpose(1, 2).contiguous().view(batch, length, self.d_model)
        return self.out_proj(output)


class EncoderBlock(nn.Module):
    """Pre-LN morphology-aware Transformer encoder block."""

    def __init__(
        self,
        d_model: int,
        num_heads: int,
        ffn_dim: int,
        dropout: float = 0.1,
        beta_x: float = 1.0,
        beta_d: float = 0.5,
        beta_bank: float = 0.5,
        beta_grad: float = 0.25,
    ) -> None:
        super().__init__()
        self.norm1 = RMSNorm(d_model)
        self.attention = MorphologyBiasedSelfAttention(
            d_model, num_heads, dropout, beta_x, beta_d, beta_bank, beta_grad,
        )
        self.residual_dropout = nn.Dropout(dropout)
        self.norm2 = RMSNorm(d_model)
        self.ffn = nn.Sequential(
            nn.Linear(d_model, ffn_dim),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(ffn_dim, d_model),
            nn.Dropout(dropout),
        )

    def forward(
        self,
        hidden: torch.Tensor,
        morphology: torch.Tensor,
        token_mask: torch.Tensor,
    ) -> torch.Tensor:
        hidden = hidden + self.residual_dropout(
            self.attention(self.norm1(hidden), morphology, token_mask)
        )
        hidden = hidden + self.ffn(self.norm2(hidden))
        return hidden * token_mask.unsqueeze(-1).to(hidden.dtype)
