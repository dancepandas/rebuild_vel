"""Model arms and single-section inference for the web service.

The three checkpoints are the Aether family: one architecture trained to three
objectives, offered side by side so a reviewer can see where they part company
on a real measurement, rather than reading a table of averages.

* ``aether-p``  physics-constrained - morphology-biased attention, five physical
                loss terms.  **The project's main model.**
* ``aether-m``  the pure arm - z-score target, pure attention + RoPE, no
                physical prior
* ``aether-y``  the transform arm - Yeo-Johnson target transform, low-flow first

Checkpoints are 330 MB each and are loaded on first use, so a session that
never opens an arm never pays for it.
"""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path
from typing import Any, Optional

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

#: arm id -> checkpoint.  ``runs/`` is not tracked, so these are defaults for
#: this machine; override with --arms <json> to point at another set.
DEFAULT_ARMS: dict[str, dict[str, str]] = {
    "aether-p": {
        "label": "Aether-P",
        "note": "主模型 · 物理约束",
        "checkpoint": "runs/v1/attempt5_ep70gate/best.pt",
    },
    "aether-m": {
        "label": "Aether-M",
        "note": "纯净版 · 纯注意力 + RoPE",
        "checkpoint": "runs/v1_mse/best.pt",
    },
    "aether-y": {
        "label": "Aether-Y",
        "note": "变换版 · Yeo-Johnson",
        "checkpoint": "runs/v1_mse_bc/best_by_rmse.pt",
    },
}

#: |prediction - platform value| above this marks a line for human review; the
#: project's reporting framework treats model/platform disagreement as a flag,
#: not as proof the model is wrong (the platform target is a manual product).
DISAGREEMENT_THRESHOLD = 1.0

#: A measuring line with no water column over it cannot carry a surface
#: velocity, so its reconstruction is forced to zero.  The model is a
#: regression over the whole section with no hard morphological constraint, so
#: nothing in the architecture stops it from reading a nonzero velocity off a
#: dry line - and such a reading is not a modelling error to be averaged away,
#: it is a value that cannot exist.  The panel draws only what has passed this
#: valve.  Note this is `<= 0`, not the 1 cm the corpus calls a dry line: a
#: line with 5 mm of water is a real (if tiny) water column and is left to the
#: model.
VALVE_MAX_DEPTH = 0.0


def apply_dry_valve(pred: np.ndarray, depth: np.ndarray) -> np.ndarray:
    """Zero the reconstruction wherever the line has no water over it."""
    depth = np.asarray(depth, dtype=np.float64)
    out = np.array(pred, dtype=np.float64)
    # written as `~(depth > 0)` rather than `depth <= 0` so a NaN depth - which
    # should not occur, since the quality gate rejects it - reads as dry and
    # gets zeroed instead of slipping through the comparison
    out[~(depth > VALVE_MAX_DEPTH)] = 0.0
    return out


class ArmUnavailable(RuntimeError):
    """The arm's checkpoint is missing or failed to load."""


class Arm:
    """One checkpoint, loaded lazily and kept warm."""

    def __init__(self, arm_id: str, spec: dict[str, str], device: str = "cpu") -> None:
        self.id = arm_id
        self.spec = spec
        self.label = spec.get("label", arm_id)
        self.note = spec.get("note", "")
        self.device = device
        self._lock = threading.Lock()
        self._model: Any = None
        self._norm: Any = None
        self._torch: Any = None

    @property
    def checkpoint(self) -> Path:
        return (REPO_ROOT / self.spec["checkpoint"]).resolve()

    def available(self) -> tuple[bool, str]:
        if not self.checkpoint.is_file():
            return False, f"checkpoint not found: {self.spec['checkpoint']}"
        return True, ""

    def info(self) -> dict[str, Any]:
        ok, why = self.available()
        return {"id": self.id, "label": self.label, "note": self.note,
                "checkpoint": self.spec["checkpoint"], "available": ok,
                "reason": why}

    def load(self) -> None:
        if self._model is not None:
            return
        with self._lock:
            if self._model is not None:
                return
            ok, why = self.available()
            if not ok:
                raise ArmUnavailable(why)
            import torch

            from rebuild_vel.dataset import NormStats
            from rebuild_vel.model.rebuild import RebuildVelocityModel

            checkpoint = torch.load(self.checkpoint, map_location="cpu", weights_only=False)
            config = checkpoint["config"]
            norm = NormStats.from_dict(config["norm"])
            model = RebuildVelocityModel(
                d_model=config.get("d_model", 768),
                num_heads=config.get("num_heads", 12),
                num_layers=config.get("num_layers", 14),
                ffn_dim=config.get("ffn_dim", 2304),
                dropout=0.0,
                raw_hidden=config.get("raw_hidden", 64),
                pure_attention=config.get("pure_attention", False),
            ).to(self.device)
            model.load_state_dict(checkpoint["model"])
            model.eval()
            self._torch = torch
            self._norm = norm
            self._model = model

    # -- inference ---------------------------------------------------------
    def predict(self, section: dict[str, Any], k: int) -> np.ndarray:
        """Physical surface velocity for the first ``k`` lines of ``section``.

        The dry-line valve is applied here, at the inference result, so that
        every consumer of an arm - the panel's chart and its metrics alike -
        sees the same numbers and neither has to remember to apply it.
        """
        self.load()
        torch = self._torch
        from rebuild_vel.dataset import build_sample, collate_sections

        sample = build_sample(section, self._norm)
        batch = collate_sections([sample])
        batch = {key: value.to(self.device) for key, value in batch.items()}
        with torch.no_grad():
            output = self._model.forward_batch(batch)
        raw = output["velocity_pred"][0, :k].cpu().numpy()
        pred = np.asarray(self._norm.physical_target(raw), dtype=np.float64)
        return apply_dry_valve(pred, np.asarray(section["depth"], dtype=np.float64)[:k])

    @property
    def norm(self) -> Any:
        self.load()
        return self._norm


class ArmRegistry:
    """Lazy, thread-safe collection of arms."""

    def __init__(self, specs: Optional[dict[str, dict[str, str]]] = None,
                 device: str = "cpu") -> None:
        specs = specs or DEFAULT_ARMS
        self.arms = {arm_id: Arm(arm_id, spec, device) for arm_id, spec in specs.items()}
        self.device = device

    @staticmethod
    def from_file(path: str | Path, device: str = "cpu") -> "ArmRegistry":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        return ArmRegistry(payload, device)

    def info(self) -> list[dict[str, Any]]:
        return [arm.info() for arm in self.arms.values()]

    def get(self, arm_id: str) -> Arm:
        if arm_id not in self.arms:
            raise KeyError(f"unknown arm: {arm_id}")
        return self.arms[arm_id]

    def predict_all(self, section: dict[str, Any], k: int,
                    wanted: Optional[list[str]] = None) -> dict[str, np.ndarray]:
        """Run every requested arm; a broken arm is reported, not fatal."""
        out: dict[str, np.ndarray] = {}
        errors: dict[str, str] = {}
        for arm_id, arm in self.arms.items():
            if wanted and arm_id not in wanted:
                continue
            try:
                out[arm_id] = arm.predict(section, k)
            except Exception as exc:  # noqa: BLE001 - one arm must not sink the panel
                errors[arm_id] = f"{type(exc).__name__}: {exc}"
        if errors and not out:
            raise ArmUnavailable("; ".join(f"{k}: {v}" for k, v in errors.items()))
        return out
