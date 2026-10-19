"""Learned NLOS range-bias model for DW1000 links.

Given a link's signal diagnostics the model predicts its NLOS range bias
(metres, >= 0 in expectation). The location engine can then
  * correct the range:   r_corrected = r_measured - bias_hat
  * down-weight it:      w = 1 / (1 + (bias_hat / BIAS_SCALE_M)^2)
which replaces the hand-tuned power-gap rule in location-engine/solver.py.

Why a regressor and not an NLOS classifier: in UTIL, foam/cardboard/plastic
block the path but add no range error, so "is it blocked?" is the wrong
question. What matters to the solver is "how long is this range?".

Feature sets (pick the one your firmware can report):
  * "pd":     power gap (rxPower - fpPower, dB). Works with today's hardware
              JSON {range, rxPower, fpPower}.
  * "pd_snr": power gap + first-path SNR. Needs the firmware to also send the
              DW1000 receive quality.

Range is deliberately NOT a feature: in UTIL every NLOS link is 3.94 m long,
so a model given range learns "3.94 m => NLOS" (97% CV accuracy, meaningless).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, Sequence

import joblib
import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor

FEATURE_SETS: Dict[str, Sequence[str]] = {
    "pd": ("power_dif",),
    "pd_snr": ("power_dif", "snr"),
}

BIAS_SCALE_M = 0.10   # predicted bias at which a link's weight halves
MIN_WEIGHT = 0.1      # down-weight, never drop: a 3-anchor fix needs all three


def make_estimator(seed: int = 0) -> HistGradientBoostingRegressor:
    # min_samples_leaf is large on purpose: samples within a trial are highly
    # correlated, and small leaves memorise individual recordings.
    return HistGradientBoostingRegressor(
        max_iter=200, learning_rate=0.1, min_samples_leaf=200,
        l2_regularization=1.0, early_stopping=True, random_state=seed,
    )


@dataclass
class NlosBiasModel:
    feature_set: str = "pd"
    estimator: HistGradientBoostingRegressor = field(default_factory=make_estimator)
    meta: dict = field(default_factory=dict)

    @property
    def features(self) -> Sequence[str]:
        return FEATURE_SETS[self.feature_set]

    def fit(self, X: np.ndarray, bias: np.ndarray) -> "NlosBiasModel":
        self.estimator.fit(np.asarray(X, dtype=float), np.asarray(bias, dtype=float))
        return self

    def predict(self, X: np.ndarray) -> np.ndarray:
        """Predicted bias (m) for each row of X (columns ordered as `features`).
        Clipped at 0: NLOS only ever lengthens a range."""
        X = np.atleast_2d(np.asarray(X, dtype=float))
        return np.maximum(self.estimator.predict(X), 0.0)

    def _row(self, rx_power_dbm: float, fp_power_dbm: float, snr: Optional[float]):
        vals = {"power_dif": rx_power_dbm - fp_power_dbm, "snr": snr}
        if any(vals[f] is None for f in self.features):
            raise ValueError(f"feature set {self.feature_set!r} needs {list(self.features)}")
        return [vals[f] for f in self.features]

    def bias(self, rx_power_dbm: float, fp_power_dbm: float, snr: Optional[float] = None) -> float:
        return float(self.predict([self._row(rx_power_dbm, fp_power_dbm, snr)])[0])

    def correct(self, range_m: float, rx_power_dbm: float, fp_power_dbm: float,
                snr: Optional[float] = None) -> tuple:
        """-> (corrected range, weight) for one link."""
        b = self.bias(rx_power_dbm, fp_power_dbm, snr)
        return max(range_m - b, 0.0), float(bias_to_weight(b))

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"feature_set": self.feature_set, "estimator": self.estimator, "meta": self.meta}, path)

    @classmethod
    def load(cls, path: Path) -> "NlosBiasModel":
        d = joblib.load(path)
        return cls(feature_set=d["feature_set"], estimator=d["estimator"], meta=d.get("meta", {}))


def bias_to_weight(bias_m, scale: float = BIAS_SCALE_M, min_weight: float = MIN_WEIGHT):
    w = 1.0 / (1.0 + (np.maximum(bias_m, 0.0) / scale) ** 2)
    return np.maximum(w, min_weight)


def feature_matrix(samples, feature_set: str) -> np.ndarray:
    """Build X from util_loader.LinkSamples."""
    cols = {"power_dif": samples.power_dif, "snr": samples.snr}
    return np.column_stack([cols[f] for f in FEATURE_SETS[feature_set]])
