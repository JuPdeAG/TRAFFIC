"""XGBoost-based risk scorer — trained on historical factor data.

Architecture
------------
Input:  7 risk-factor scores (same as RiskScoringEngine)
Output: risk score 0-100

When a trained model file is present the XGBoost scorer replaces the
hand-crafted weighted sum.  When no model is present it falls back to
the existing RiskScoringEngine so the system always produces a score.

Training: see scripts/train_risk_model.py
Model file: ~/.cache/traffic_ai/models/risk_xgboost.json  (~50 KB)

XGBoost is Apache 2.0 — no commercial restrictions.
"""
from __future__ import annotations
import logging
import os
from pathlib import Path
from typing import Any

import numpy as np

from traffic_ai.analytics.risk_scorer import RiskFactors, RiskScoringEngine, DEFAULT_WEIGHTS

logger = logging.getLogger(__name__)

_CACHE_DIR = Path(
    os.environ.get("MODEL_CACHE_DIR", Path.home() / ".cache" / "traffic_ai" / "models")
)
XGB_MODEL_PATH = _CACHE_DIR / "risk_xgboost.json"

# Feature order must match training (same as RiskFactors.as_dict() key order)
FEATURE_ORDER = [
    "speed_deviation",
    "incident_proximity",
    "flow_density",
    "historical_baseline",
    "infrastructure_health",
    "time_day_pattern",
    "weather",
]


class MLRiskScoringEngine(RiskScoringEngine):
    """Drop-in replacement for RiskScoringEngine that uses XGBoost for scoring.

    Inherits all factor-gathering logic from RiskScoringEngine.
    Overrides only the final aggregation step (_weighted_sum / compute).
    """

    def __init__(
        self,
        db=None,
        weights=None,
        model_path: Path | None = None,
    ) -> None:
        super().__init__(db=db, weights=weights)
        self._model_path = model_path or XGB_MODEL_PATH
        self._xgb_model = None  # lazy load
        self._model_available: bool | None = None  # None = not yet checked

    # ── overrides ────────────────────────────────────────────────────────────

    async def compute(self, segment_id: str) -> float:
        factors = await self._gather_factors(segment_id)
        score = self._score_factors(factors)
        return round(min(max(score, 0.0), 100.0), 2)

    async def compute_with_explanation(self, segment_id: str) -> dict[str, Any]:
        factors = await self._gather_factors(segment_id)
        score = round(min(max(self._score_factors(factors), 0.0), 100.0), 2)
        model_name = "xgboost" if self._is_model_loaded() else "weighted_sum"
        return {
            "segment_id": segment_id,
            "score": score,
            "level": self.score_to_level(score),
            "factors": factors.as_dict(),
            "model": model_name,
            "computed_at": __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc
            ).isoformat(),
        }

    # ── scoring ───────────────────────────────────────────────────────────────

    def _score_factors(self, factors: RiskFactors) -> float:
        """Score via XGBoost if available, otherwise fall back to weighted sum."""
        xgb = self._try_load_model()
        if xgb is None:
            return self._weighted_sum(factors)

        try:
            feature_vec = np.array(
                [[factors.as_dict()[k] for k in FEATURE_ORDER]],
                dtype=np.float32,
            )
            import xgboost as xgb_lib  # noqa: PLC0415
            dmatrix = xgb_lib.DMatrix(feature_vec, feature_names=FEATURE_ORDER)
            pred = float(xgb.predict(dmatrix)[0])
            return min(max(pred, 0.0), 100.0)
        except Exception:
            logger.exception("XGBoost inference failed — falling back to weighted sum")
            return self._weighted_sum(factors)

    def _try_load_model(self):
        """Load XGBoost model lazily.  Returns None if model file is absent."""
        if self._model_available is False:
            return None
        if self._xgb_model is not None:
            return self._xgb_model
        if not self._model_path.exists():
            self._model_available = False
            logger.debug(
                "XGBoost risk model not found at %s — using weighted sum. "
                "Run scripts/train_risk_model.py to train.",
                self._model_path,
            )
            return None
        try:
            import xgboost as xgb  # noqa: PLC0415
            model = xgb.Booster()
            model.load_model(str(self._model_path))
            self._xgb_model = model
            self._model_available = True
            logger.info("Loaded XGBoost risk model from %s", self._model_path)
            return model
        except ImportError:
            logger.warning("xgboost package not installed — pip install xgboost")
            self._model_available = False
            return None
        except Exception:
            logger.exception("Failed to load XGBoost risk model")
            self._model_available = False
            return None

    def _is_model_loaded(self) -> bool:
        return self._xgb_model is not None
