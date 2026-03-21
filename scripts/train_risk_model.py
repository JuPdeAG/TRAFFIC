"""Train XGBoost risk scoring model from historical labelled data.

Usage
-----
    python scripts/train_risk_model.py [--epochs 200] [--lookback-days 90]

Inputs
------
Historical risk factor scores paired with observed outcomes (accident rate,
congestion severity) queried from InfluxDB + PostgreSQL.

Output
------
  ~/.cache/traffic_ai/models/risk_xgboost.json  (~50 KB)

Requirements (training-only):
  pip install xgboost scikit-learn pandas

XGBoost is Apache 2.0 — no commercial restrictions.
"""
from __future__ import annotations
import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

CACHE_DIR = Path(os.environ.get("MODEL_CACHE_DIR", Path.home() / ".cache" / "traffic_ai" / "models"))
MODEL_OUT = CACHE_DIR / "risk_xgboost.json"

FEATURE_ORDER = [
    "speed_deviation",
    "incident_proximity",
    "flow_density",
    "historical_baseline",
    "infrastructure_health",
    "time_day_pattern",
    "weather",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Train XGBoost risk scorer")
    parser.add_argument("--n-estimators", type=int, default=200)
    parser.add_argument("--max-depth", type=int, default=5)
    parser.add_argument("--lr", type=float, default=0.05)
    parser.add_argument("--lookback-days", type=int, default=90)
    args = parser.parse_args()

    try:
        import xgboost as xgb
        import pandas as pd
        import numpy as np
    except ImportError:
        logger.error("pip install xgboost pandas is required for training")
        sys.exit(1)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    logger.info("=== Traffic AI — XGBoost Risk Model Training ===")
    logger.info("Lookback: %d days | Estimators: %d | Depth: %d", args.lookback_days, args.n_estimators, args.max_depth)

    # 1. Load historical data from InfluxDB / PostgreSQL
    logger.info("Step 1/4 — Fetching historical factor data")
    df = fetch_historical_factors(args.lookback_days)

    if df is None or len(df) < 100:
        logger.warning("Not enough labelled data — generating synthetic training data")
        df = _synthetic_training_data(n=5000)

    logger.info("  %d training samples", len(df))

    # 2. Prepare features / target
    logger.info("Step 2/4 — Preparing features")
    X = df[FEATURE_ORDER].values.astype("float32")
    # Target: composite risk score (0-100), computed as weighted sum with noise
    # In production, replace with actual outcome labels (e.g. accident binary +
    # congestion severity observed 30 min later)
    y = df["risk_score"].values.astype("float32")

    from sklearn.model_selection import train_test_split
    X_train, X_val, y_train, y_val = train_test_split(X, y, test_size=0.2, random_state=42)

    # 3. Train
    logger.info("Step 3/4 — Training XGBoost regressor")
    dtrain = xgb.DMatrix(X_train, label=y_train, feature_names=FEATURE_ORDER)
    dval = xgb.DMatrix(X_val, label=y_val, feature_names=FEATURE_ORDER)

    params = {
        "objective": "reg:squarederror",
        "eval_metric": "rmse",
        "max_depth": args.max_depth,
        "eta": args.lr,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "min_child_weight": 3,
        "seed": 42,
    }
    evals_result = {}
    model = xgb.train(
        params,
        dtrain,
        num_boost_round=args.n_estimators,
        evals=[(dtrain, "train"), (dval, "val")],
        evals_result=evals_result,
        early_stopping_rounds=20,
        verbose_eval=20,
    )

    best_rmse = min(evals_result["val"]["rmse"])
    logger.info("  Best val RMSE: %.4f", best_rmse)

    # Feature importance
    try:
        import pandas as pd
        importance = pd.Series(model.get_score(importance_type="gain")).sort_values(ascending=False)
        logger.info("  Feature importance (gain):\n%s", importance.to_string())
    except Exception:
        pass

    # 4. Save
    logger.info("Step 4/4 — Saving model: %s", MODEL_OUT)
    model.save_model(str(MODEL_OUT))
    logger.info("Done. Model size: %.1f KB", MODEL_OUT.stat().st_size / 1e3)


def fetch_historical_factors(lookback_days: int):
    """Query InfluxDB for historical factor scores with labelled outcomes."""
    try:
        import pandas as pd

        # Set up Django-style event loop for async query
        from traffic_ai.config import settings  # noqa: PLC0415 — project import
        from traffic_ai.db.influx import query_points  # noqa: PLC0415

        async def _query():
            query = f"""
            from(bucket: "traffic_metrics")
              |> range(start: -{lookback_days * 24}h)
              |> filter(fn: (r) => r._measurement == "risk_factors")
              |> pivot(rowKey:["_time","segment_id"], columnKey:["_field"], valueColumn:"_value")
              |> sort(columns: ["_time"])
            """
            return await query_points(query)

        loop = asyncio.new_event_loop()
        try:
            points = loop.run_until_complete(_query())
        finally:
            loop.close()

        if not points:
            return None

        df = pd.DataFrame(points)
        for col in FEATURE_ORDER + ["risk_score"]:
            if col not in df.columns:
                df[col] = 0.0
        return df[FEATURE_ORDER + ["risk_score"]].dropna()

    except Exception as e:
        logger.warning("Could not fetch historical factors: %s", e)
        return None


def _synthetic_training_data(n: int = 5000):
    """Generate synthetic labelled training data for initial model bootstrap."""
    import pandas as pd
    import numpy as np
    from traffic_ai.analytics.risk_scorer import DEFAULT_WEIGHTS  # noqa: PLC0415

    rng = np.random.default_rng(42)
    data = {}
    for feat in FEATURE_ORDER:
        # Generate correlated but noisy factor scores
        data[feat] = np.clip(rng.normal(30, 25, n), 0, 100)

    df = pd.DataFrame(data)

    # Target = weighted sum + non-linear interaction + noise
    weights = DEFAULT_WEIGHTS
    score = sum(df[f] * weights.get(f, 0.0) for f in FEATURE_ORDER)
    # Add non-linearity: high speed_deviation × high flow_density amplifies risk
    score += df["speed_deviation"] * df["flow_density"] * 0.001
    score += rng.normal(0, 3, n)  # noise
    df["risk_score"] = np.clip(score, 0, 100).astype("float32")

    return df


if __name__ == "__main__":
    main()
