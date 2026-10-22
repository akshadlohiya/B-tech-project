"""Learned NLOS range correction — the ai-module bias model, wired into the engine.

The power-gap rule in solver.py can only *down-weight* a blocked range. The
learned model (ai-module/uwb_ai/nlos_model.py, trained on real DW1000 links from
UTIL) predicts how many metres the blockage added, so the engine can also
*shorten* the range, then weight it by the remaining uncertainty.

Baseline alignment: the model was trained on UTIL's power-gap scale (LOS median
~13 dB), while each site reports gaps on its own scale (the sim and the DW3000
config use a 3 dB LOS gap, `ranging.power.fpToRxDeltaLosDbm`). Each gap is shifted
by (model LOS baseline - site LOS baseline) before prediction. Without this the
model reads every blocked sim link as clear and removes the NLOS down-weighting
(benchmark: 36 -> 50 cm mean error instead of 36 -> 16 cm). On real hardware the
site value must be the measured median LOS gap of the actual nodes.

One predict call per reading costs ~0.4 ms. If the model, its dependencies or its
metadata are missing, `load_learned_nlos` returns None and the engine keeps using
the rule.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Dict, Optional, Sequence, Tuple

import numpy as np

_AI_DIR = Path(__file__).resolve().parents[1] / "ai-module"
DEFAULT_MODEL_PATH = _AI_DIR / "models" / "nlos_bias_pd.joblib"

_cache: Dict[str, object] = {}   # model path -> NlosBiasModel (hot reloads rebuild the engine)

if str(_AI_DIR) not in sys.path:   # the engine also imports uwb_ai.zones / uwb_ai.predict
    sys.path.insert(0, str(_AI_DIR))


class LearnedNlos:
    def __init__(self, model, site_los_gap_db: float):
        from uwb_ai.nlos_model import bias_to_weight
        self._bias_to_weight = bias_to_weight
        self.model_los_gap_db = float(model.meta["los_gap_db"])
        self.site_los_gap_db = float(site_los_gap_db)
        self.shift_db = self.model_los_gap_db - self.site_los_gap_db
        self.model = model

    def bias(self, gap_db) -> np.ndarray:
        """Predicted NLOS bias (m) for site-scale power gaps (rxPower - fpPower)."""
        return self.model.predict((np.asarray(gap_db, dtype=float) + self.shift_db).reshape(-1, 1))

    def correct(self, ranges_m: Sequence[float], gaps_db: Sequence[float]) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """-> (corrected ranges, weights, predicted biases) for one cycle's links."""
        b = self.bias(gaps_db)
        r = np.maximum(np.asarray(ranges_m, dtype=float) - b, 0.0)
        return r, np.asarray(self._bias_to_weight(b), dtype=float), b


def load_learned_nlos(site_los_gap_db: float, path: Optional[os.PathLike] = None) -> Tuple[Optional[LearnedNlos], str]:
    """-> (LearnedNlos or None, reason). Never raises: any failure means 'use the rule'."""
    path = Path(path) if path else DEFAULT_MODEL_PATH
    try:
        from uwb_ai.nlos_model import NlosBiasModel
        if not path.exists():
            return None, f"model file not found: {path}"
        model = _cache.get(str(path))
        if model is None:
            model = _cache[str(path)] = NlosBiasModel.load(path)
        if model.feature_set != "pd":
            return None, f"model needs features {list(model.features)}; readings only carry the power gap"
        if "los_gap_db" not in model.meta:
            return None, "model has no los_gap_db (retrain with python -m uwb_ai.train_nlos)"
        return LearnedNlos(model, site_los_gap_db), f"learned bias model ({path.name})"
    except Exception as exc:   # missing sklearn/joblib, unreadable file, ...
        return None, f"could not load learned model ({type(exc).__name__}: {exc})"
