"""Supervised reconstruction loss: full-section MSE + physics consistency.

Physics terms are computed on every real point (no masking in this task) and
follow the V3 pretraining project's formulation: smoothness, velocity-depth
positive correlation, near-bank limits, and gradient-protected smoothness.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

import torch
import torch.nn as nn
import torch.nn.functional as F


@dataclass(frozen=True)
class LossConfig:
    # lambdas pinned to the V3 pretraining run (validated on 99,616 sections);
    # the larger defaults used earlier in this repo were never ablated
    lambda_smooth: float = 0.05
    lambda_depth_corr: float = 0.02
    lambda_bank: float = 0.01
    lambda_bank_zero: float = 0.02
    lambda_grad: float = 0.01
    bank_threshold: float = 0.2
    depth_threshold: float = 0.1
    v_bank_limit: float = 0.6
    bank_zero_tau: float = 0.2
    depth_zero_tau: float = 0.2
    grad_smooth_gamma: float = 2.0
    corr_softplus_beta: float = 5.0
    mode: str = "full"  # "full" | "mse_only"


class RebuildPhysicsLoss(nn.Module):
    """Full-section MSE plus physics regularizers for ordered sections."""

    def __init__(self, config: LossConfig, *, v_zero_norm: float) -> None:
        super().__init__()
        self.config = config
        self.v_zero_norm = float(v_zero_norm)

    @staticmethod
    def _zero(prediction: torch.Tensor) -> torch.Tensor:
        return prediction.sum() * 0.0

    def forward(
        self,
        prediction: torch.Tensor,   # [B, K] standardized
        target: torch.Tensor,       # [B, K] standardized
        line_mask: torch.Tensor,   # [B, K]
        morphology: torch.Tensor,   # [B, K, 4]
    ) -> Dict[str, torch.Tensor]:
        if prediction.shape != target.shape or prediction.shape != line_mask.shape:
            raise ValueError("prediction, target and line_mask shapes must match")
        points = line_mask.bool()
        if not points.any():
            raise ValueError("line_mask selects at least one point")

        diff = (prediction - target).square()
        mse = diff.masked_select(points).mean()

        if self.config.mode == "mse_only":
            zero = self._zero(prediction)
            return {
                "loss": mse, "mse": mse.detach(), "smooth": zero,
                "depth_corr": zero, "bank": zero, "bank_zero": zero,
                "grad_smooth": zero,
            }

        depth = morphology[..., 1]
        bank = morphology[..., 2]
        gradient = morphology[..., 3]

        # smoothness on adjacent pairs (all real pairs count)
        difference = prediction[:, 1:] - prediction[:, :-1]
        pair_mask = points[:, 1:] & points[:, :-1]
        pair_count = pair_mask.sum()
        if pair_count.item() == 0:
            smooth = grad_smooth = self._zero(prediction)
        else:
            mask_f = pair_mask.to(difference.dtype)
            smooth = (difference.square() * mask_f).sum() / pair_count.to(difference.dtype)
            pair_gradient = torch.maximum(gradient[:, 1:], gradient[:, :-1])
            weight = torch.exp(-self.config.grad_smooth_gamma * pair_gradient)
            grad_smooth = (difference.square() * weight * mask_f).sum() / mask_f.sum()

        # velocity-depth positive correlation per section
        corr_losses = []
        for row in range(prediction.shape[0]):
            mask = points[row]
            if int(mask.sum().item()) < 3:
                continue
            v = prediction[row, mask]
            d = depth[row, mask]
            v_c = v - v.mean()
            d_c = d - d.mean()
            v_sd = torch.sqrt(v_c.square().mean())
            d_sd = torch.sqrt(d_c.square().mean())
            if v_sd.detach().item() < 1e-6 or d_sd.detach().item() < 1e-6:
                continue
            corr = (v_c * d_c).mean() / (v_sd * d_sd + 1e-6)
            corr_losses.append(F.softplus(-corr, beta=self.config.corr_softplus_beta))
        depth_corr = (
            torch.stack(corr_losses).mean() if corr_losses else self._zero(prediction)
        )

        # near-bank cap and bank-zero pull
        bank_mask = points & (bank < self.config.bank_threshold) & (depth < self.config.depth_threshold)
        bank_count = bank_mask.sum()
        if bank_count.item() == 0:
            bank_loss = self._zero(prediction)
        else:
            excess = F.relu(prediction - self.config.v_bank_limit).square()
            bank_loss = excess.masked_select(bank_mask).mean()

        weight = (
            torch.exp(-bank / self.config.bank_zero_tau)
            * torch.exp(-depth / self.config.depth_zero_tau)
            * points.to(prediction.dtype)
        )
        weight_sum = weight.sum()
        if weight_sum.detach().item() <= 1e-8:
            bank_zero = self._zero(prediction)
        else:
            bank_zero = (weight * (prediction - self.v_zero_norm).square()).sum() / weight_sum

        total = (
            mse
            + self.config.lambda_smooth * smooth
            + self.config.lambda_depth_corr * depth_corr
            + self.config.lambda_bank * bank_loss
            + self.config.lambda_bank_zero * bank_zero
            + self.config.lambda_grad * grad_smooth
        )
        return {
            "loss": total,
            "mse": mse.detach(),
            "smooth": smooth.detach(),
            "depth_corr": depth_corr.detach(),
            "bank": bank_loss.detach(),
            "bank_zero": bank_zero.detach(),
            "grad_smooth": grad_smooth.detach(),
        }
