"""Train LSTM congestion prediction model and export to ONNX.

Usage
-----
    python scripts/train_congestion_model.py [--epochs 30] [--lookback-days 90]

Inputs
------
1. Madrid loop detector historical data  (datos.madrid.es CSV archives, 2013-present)
2. Open-Meteo historical weather archive  (free, no API key needed)
3. Optionally Barcelona / DGT loop data (same CSV format)

Output
------
  ~/.cache/traffic_ai/models/congestion_lstm.onnx  (~1-3 MB)

Training takes ~5-15 minutes on CPU for 90 days of Madrid data.

Requirements (training-only, not needed at runtime):
  pip install torch onnx scikit-learn pandas requests statsmodels
"""
from __future__ import annotations
import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ── Paths ────────────────────────────────────────────────────────────────────
CACHE_DIR = Path(os.environ.get("MODEL_CACHE_DIR", Path.home() / ".cache" / "traffic_ai" / "models"))
SCALER_PATH = CACHE_DIR / "congestion_scaler.json"
ONNX_OUT = CACHE_DIR / "congestion_lstm.onnx"

# ── Madrid historical data — CKAN API ────────────────────────────────────────
# datos.madrid.es does NOT have predictable URL slugs; file URLs must be
# enumerated via the datos.gob.es CKAN API (which mirrors the Madrid catalogue).
# Dataset: "Tráfico. Histórico de datos del tráfico desde 2013"
# datos.gob.es identifier: l01280796-trafico-historico-de-datos-del-trafico-desde-20131
# CKAN package_show endpoint (no auth needed):
MADRID_CKAN_API = (
    "https://datos.gob.es/en/catalogo/l01280796-trafico-historico-"
    "de-datos-del-trafico-desde-20131.json"
)

# Columns in the 15-min measurement-point CSV (confirmed, semicolon-delimited):
#   idelem; tipo_elem; distrito; cod_cent; nombre; utm_x; utm_y;
#   longitud; latitud; fecha; intensidad; ocupacion; carga; nivelservicio;
#   error; subError
# 'intensidad' = vehicles/hour, 'ocupacion' = % occupancy, 'carga' = 0-100
# Note: no speed column in most historical files — we derive from carga.

# Open-Meteo historical archive — free, no key, CC BY 4.0
# Madrid city centre (lat=40.4168, lon=-3.7038)
# VERIFIED API parameter names (windspeed_10m, NOT wind_speed_10m;
# visibility is NOT available — use cloud_cover_low + weather_code for fog)
OPENMETEO_HIST_URL = (
    "https://archive-api.open-meteo.com/v1/archive"
    "?latitude=40.4168&longitude=-3.7038"
    "&start_date={start}&end_date={end}"
    "&hourly=temperature_2m,precipitation,windspeed_10m,cloud_cover_low,weather_code"
    "&timezone=Europe%2FMadrid"
)


# ── Feature columns (must match ml/congestion_model.py) ────────────────────
FEATURE_COLS = [
    "speed_kmh", "occupancy_pct", "flow_veh_per_min",
    "hour_sin", "hour_cos", "dow_sin", "dow_cos",
    "precipitation_mm", "wind_speed_kmh", "temperature_c",
]
SEQ_LEN = 12   # 12 × 5-min = 60-min lookback
HORIZONS = [15, 30, 60]  # predict 3 horizons simultaneously (minutes)
N_FEATURES = len(FEATURE_COLS)  # 10


def main() -> None:
    parser = argparse.ArgumentParser(description="Train LSTM congestion model")
    parser.add_argument("--epochs", type=int, default=30, help="Training epochs")
    parser.add_argument("--lookback-days", type=int, default=90, help="Days of historical data")
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--hidden-size", type=int, default=128, help="LSTM hidden units")
    parser.add_argument("--num-layers", type=int, default=2)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--no-download", action="store_true", help="Skip data download (use cache)")
    args = parser.parse_args()

    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    logger.info("=== Traffic AI — LSTM Congestion Model Training ===")
    logger.info("Lookback: %d days | Epochs: %d | Hidden: %d", args.lookback_days, args.epochs, args.hidden_size)

    # 1. Fetch data
    logger.info("Step 1/5 — Fetching historical data")
    sensor_df = fetch_madrid_historical(args.lookback_days, skip_download=args.no_download)
    weather_df = fetch_openmeteo_historical(args.lookback_days)

    if sensor_df is None or len(sensor_df) < SEQ_LEN * 10:
        logger.error("Not enough sensor data to train. Download failed or too few rows.")
        sys.exit(1)

    # 2. Merge + engineer features
    logger.info("Step 2/5 — Feature engineering (%d sensor rows)", len(sensor_df))
    df = merge_features(sensor_df, weather_df)

    # 3. Build sequences
    logger.info("Step 3/5 — Building training sequences")
    X, y, scaler_params = build_sequences(df)
    logger.info("  X shape: %s  y shape: %s", X.shape, y.shape)

    # Save scaler params (used at inference time inside the ONNX graph or as pre-processing)
    with open(SCALER_PATH, "w") as f:
        json.dump(scaler_params, f)
    logger.info("  Scaler saved: %s", SCALER_PATH)

    # 4. Train
    logger.info("Step 4/5 — Training")
    model = train(X, y, args)

    # 5. Export to ONNX
    logger.info("Step 5/5 — Exporting to ONNX: %s", ONNX_OUT)
    export_onnx(model, ONNX_OUT)
    logger.info("Done. Model size: %.1f MB", ONNX_OUT.stat().st_size / 1e6)


# ── Data fetching ─────────────────────────────────────────────────────────────


def fetch_madrid_historical(lookback_days: int, skip_download: bool = False):
    """Download Madrid historical traffic CSVs via datos.gob.es CKAN API.

    The datos.madrid.es portal does not have predictable download URLs —
    resource IDs must be enumerated from the CKAN catalogue JSON.  We download
    the most recent monthly files that cover the requested lookback window.

    Column schema (15-min measurement-point files, confirmed):
      idelem; tipo_elem; distrito; cod_cent; nombre; utm_x; utm_y;
      longitud; latitud; fecha; intensidad; ocupacion; carga; nivelservicio
      - intensidad  = vehicles/hour (flow)
      - ocupacion   = road occupancy 0-100 %
      - carga       = congestion index 0-100 (used as speed proxy)
    Note: most historical files do NOT contain a speed column.
    """
    try:
        import pandas as pd
        import requests
    except ImportError:
        logger.error("pip install pandas requests is required for training")
        return None

    raw_dir = CACHE_DIR / "madrid_raw"
    raw_dir.mkdir(exist_ok=True)

    # Try to get resource list from datos.gob.es CKAN
    resource_urls = _fetch_madrid_resource_urls(skip_download)

    dfs = []
    today = datetime.now(timezone.utc).date()
    cutoff = today - timedelta(days=lookback_days)

    for url, filename in resource_urls:
        csv_path = raw_dir / filename
        if not csv_path.exists() and not skip_download:
            try:
                logger.info("  Downloading %s ...", filename)
                r = requests.get(url, timeout=120)
                if r.status_code == 200:
                    csv_path.write_bytes(r.content)
                else:
                    logger.debug("HTTP %d for %s", r.status_code, url)
                    continue
            except Exception as e:
                logger.debug("Skip %s: %s", filename, e)
                continue

        if csv_path.exists():
            try:
                df = _load_madrid_csv(csv_path)
                if df is not None:
                    dfs.append(df)
            except Exception as e:
                logger.debug("Could not parse %s: %s", csv_path, e)

    if not dfs:
        logger.warning("No Madrid CSV files loaded — using synthetic data for demo.")
        return _synthetic_sensor_data(lookback_days)

    full = pd.concat(dfs, ignore_index=True)
    return _normalise_madrid_df(full)


def _fetch_madrid_resource_urls(skip_download: bool) -> list[tuple[str, str]]:
    """Enumerate Madrid traffic CSV download URLs from datos.gob.es CKAN."""
    try:
        import requests
        cache_file = CACHE_DIR / "madrid_resources.json"
        if cache_file.exists() and not skip_download:
            import time
            if time.time() - cache_file.stat().st_mtime < 86400:  # 24h cache
                with open(cache_file) as f:
                    import json as _json
                    return _json.load(f)

        r = requests.get(MADRID_CKAN_API, timeout=30)
        if r.status_code != 200:
            logger.warning("datos.gob.es CKAN returned %d", r.status_code)
            return []

        data = r.json()
        # CKAN package_show response has resources list
        resources = data.get("result", data).get("resources", [])
        pairs = []
        for res in resources:
            url = res.get("url") or res.get("download_url", "")
            name = res.get("name") or res.get("id", "unknown")
            if url.endswith(".csv") or "csv" in url.lower():
                filename = f"madrid_{name}.csv"
                pairs.append((url, filename))

        if pairs:
            with open(cache_file, "w") as f:
                import json as _json
                _json.dump(pairs, f)
        return pairs
    except Exception as e:
        logger.warning("Could not enumerate Madrid resources: %s", e)
        return []


def _load_madrid_csv(path):
    """Load a Madrid traffic CSV, trying both semicolon and comma separators."""
    import pandas as pd

    for sep in (";", ","):
        for enc in ("utf-8", "latin-1", "iso-8859-1"):
            try:
                df = pd.read_csv(path, sep=sep, encoding=enc, low_memory=False, nrows=5)
                if len(df.columns) > 3:
                    return pd.read_csv(path, sep=sep, encoding=enc, low_memory=False)
            except Exception:
                continue
    return None


def _normalise_madrid_df(df):
    """Standardise column names from Madrid CSV to our internal schema.

    Confirmed 15-min measurement-point columns (semicolon delimited):
      idelem, tipo_elem, distrito, cod_cent, nombre, utm_x, utm_y,
      longitud, latitud, fecha, intensidad, ocupacion, carga, nivelservicio

    The 'carga' column (0-100 congestion index) is used to derive a
    pseudo-speed when no velocidad column is present:
      speed_proxy = free_flow_speed × (1 - carga/100)
    Free-flow speed defaults to 80 km/h (M-30 typical).
    """
    import pandas as pd

    # Lower-case all column names for consistent matching
    df.columns = [c.strip().lower() for c in df.columns]

    rename = {
        "intensidad": "flow_count",
        "ocupacion": "occupancy_pct",
        "velocidad": "speed_kmh",
        "carga": "carga",
        "fecha": "fecha",
        "idelem": "sensor_id",
    }
    df = df.rename(columns={k: v for k, v in rename.items() if k in df.columns})

    for col in ("flow_count", "occupancy_pct", "carga"):
        if col not in df.columns:
            df[col] = 0.0
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    # Derive speed from carga when not directly available
    if "speed_kmh" not in df.columns:
        FREE_FLOW = 80.0  # km/h — conservative M-30 free-flow speed
        df["speed_kmh"] = FREE_FLOW * (1.0 - df["carga"].clip(0, 100) / 100.0)
    else:
        df["speed_kmh"] = pd.to_numeric(df["speed_kmh"], errors="coerce").fillna(0)

    # Flow: intensidad is vehicles/hour → convert to per-min
    df["flow_veh_per_min"] = df["flow_count"] / 60.0

    # Hour of day from fecha timestamp
    if "fecha" in df.columns:
        try:
            df["hour"] = pd.to_datetime(df["fecha"], errors="coerce").dt.hour.fillna(0).astype(int)
            df["date"] = pd.to_datetime(df["fecha"], errors="coerce").dt.date
        except Exception:
            df["hour"] = 0
            df["date"] = None
    elif "hour" not in df.columns:
        df["hour"] = 0

    return df


def _synthetic_sensor_data(days: int):
    """Generate realistic synthetic data when real CSV is unavailable."""
    import pandas as pd
    import numpy as np

    logger.info("Generating synthetic sensor data (%d days)", days)
    n = days * 24 * 12  # 5-min intervals
    rng = np.random.default_rng(42)
    t = np.arange(n)
    # Rush-hour pattern
    hours = (t * 5 // 60) % 24
    rush = ((hours >= 7) & (hours <= 9)) | ((hours >= 16) & (hours <= 19))
    speed_base = np.where(rush, 45.0, 90.0)
    speed = np.clip(speed_base + rng.normal(0, 8, n), 5, 130)
    flow = np.clip(np.where(rush, 60.0, 20.0) + rng.normal(0, 5, n), 0, 120)
    occ = np.clip(np.where(rush, 55.0, 15.0) + rng.normal(0, 5, n), 0, 100)
    return pd.DataFrame({
        "speed_kmh": speed,
        "flow_veh_per_min": flow / 5.0,
        "occupancy_pct": occ,
        "hour": hours,
        "date": pd.date_range("2025-01-01", periods=n, freq="5min").date,
    })


def fetch_openmeteo_historical(lookback_days: int):
    """Fetch weather from Open-Meteo historical archive (free, CC BY 4.0)."""
    try:
        import pandas as pd
        import requests
    except ImportError:
        return None

    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=lookback_days + 1)
    url = OPENMETEO_HIST_URL.format(start=start, end=today)

    cached = CACHE_DIR / f"openmeteo_{start}_{today}.json"
    if cached.exists():
        with open(cached) as f:
            data = json.load(f)
    else:
        try:
            r = requests.get(url, timeout=60)
            r.raise_for_status()
            data = r.json()
            with open(cached, "w") as f:
                json.dump(data, f)
        except Exception as e:
            logger.warning("Open-Meteo fetch failed: %s — using zero weather", e)
            return None

    try:
        hourly = data.get("hourly", {})
        df = pd.DataFrame({
            "datetime": pd.to_datetime(hourly["time"]),
            "temperature_c": hourly.get("temperature_2m", [0] * len(hourly["time"])),
            "precipitation_mm": hourly.get("precipitation", [0] * len(hourly["time"])),
            # API param is 'windspeed_10m' (confirmed) not 'wind_speed_10m'
            "wind_speed_kmh": hourly.get("windspeed_10m", [0] * len(hourly["time"])),
            # visibility_m is NOT in Open-Meteo archive; use cloud_cover_low +
            # weather_code as fog proxy (codes 45=fog, 48=rime fog)
            "cloud_cover_low_pct": hourly.get("cloud_cover_low", [0] * len(hourly["time"])),
            "weather_code": hourly.get("weather_code", [0] * len(hourly["time"])),
        })
        # Derive a fog_factor 0-1: fog codes or high low-cloud cover
        df["fog_factor"] = (
            (df["weather_code"].isin([45, 48])).astype(float) * 0.7
            + (df["cloud_cover_low_pct"].clip(0, 100) / 100.0) * 0.3
        ).clip(0, 1)
        return df
    except Exception as e:
        logger.warning("Could not parse Open-Meteo response: %s", e)
        return None


# ── Feature engineering ───────────────────────────────────────────────────────


def merge_features(sensor_df, weather_df):
    """Merge sensor and weather data on hour, add cyclical time features."""
    import pandas as pd
    import numpy as np

    df = sensor_df.copy()

    if weather_df is not None:
        try:
            weather_df = weather_df.copy()
            weather_df["hour"] = weather_df["datetime"].dt.hour
            wx_cols = [c for c in ("temperature_c", "precipitation_mm", "wind_speed_kmh", "fog_factor")
                       if c in weather_df.columns]
            wx_hourly = weather_df.groupby("hour")[wx_cols].mean().reset_index()
            df = df.merge(wx_hourly, on="hour", how="left")
        except Exception as e:
            logger.warning("Weather merge failed: %s", e)

    defaults = {"temperature_c": 15.0, "precipitation_mm": 0.0, "wind_speed_kmh": 10.0, "fog_factor": 0.0}
    for col, default in defaults.items():
        if col not in df.columns:
            df[col] = default

    # Cyclical time features
    df["hour_sin"] = np.sin(2 * np.pi * df["hour"] / 24)
    df["hour_cos"] = np.cos(2 * np.pi * df["hour"] / 24)

    # Day of week — approximate from date if available
    if "date" in df.columns:
        try:
            df["dow"] = pd.to_datetime(df["date"]).dt.dayofweek
        except Exception:
            df["dow"] = 0
    else:
        df["dow"] = 0

    df["dow_sin"] = np.sin(2 * np.pi * df["dow"] / 7)
    df["dow_cos"] = np.cos(2 * np.pi * df["dow"] / 7)

    return df.dropna(subset=["speed_kmh"])


# ── Sequence building ─────────────────────────────────────────────────────────


def build_sequences(df):
    """Slide a window over the dataframe to create (X, y) training pairs."""
    import numpy as np

    feat_arr = df[FEATURE_COLS].values.astype(np.float32)

    # Compute mean/std for standardisation (saved as JSON scaler)
    mean = feat_arr.mean(axis=0)
    std = np.where(feat_arr.std(axis=0) > 1e-6, feat_arr.std(axis=0), 1.0)
    scaler = {"mean": mean.tolist(), "std": std.tolist(), "features": FEATURE_COLS}

    feat_norm = (feat_arr - mean) / std

    speed_col = FEATURE_COLS.index("speed_kmh")
    max_horizon_steps = max(HORIZONS) // 5  # steps for 60-min horizon

    X_list, y_list = [], []
    total = len(feat_norm)
    for i in range(SEQ_LEN, total - max_horizon_steps):
        x = feat_norm[i - SEQ_LEN:i]  # (SEQ_LEN, N_FEATURES)
        # Multi-horizon target: speed at 15, 30, 60 min ahead
        targets = [feat_arr[i + (h // 5), speed_col] for h in HORIZONS]
        X_list.append(x)
        y_list.append(targets)

    X = np.stack(X_list, axis=0)
    y = np.array(y_list, dtype=np.float32)
    return X, y, scaler


# ── Model definition ──────────────────────────────────────────────────────────


def build_model(hidden_size: int, num_layers: int):
    """Build PyTorch LSTM model."""
    try:
        import torch
        import torch.nn as nn
    except ImportError:
        logger.error("pip install torch is required for training")
        sys.exit(1)

    class CongestionLSTM(nn.Module):
        def __init__(self, n_features: int, hidden: int, layers: int, n_outputs: int):
            super().__init__()
            self.lstm = nn.LSTM(
                n_features, hidden, layers,
                batch_first=True, dropout=0.2 if layers > 1 else 0.0,
            )
            self.fc = nn.Sequential(
                nn.Linear(hidden, hidden // 2),
                nn.ReLU(),
                nn.Dropout(0.1),
                nn.Linear(hidden // 2, n_outputs),
            )

        def forward(self, x):
            out, _ = self.lstm(x)
            return self.fc(out[:, -1, :])  # last time step → output

    return CongestionLSTM(N_FEATURES, hidden_size, num_layers, len(HORIZONS))


# ── Training loop ─────────────────────────────────────────────────────────────


def train(X, y, args):
    """Train the LSTM and return the fitted model."""
    try:
        import torch
        import torch.nn as nn
        from torch.utils.data import DataLoader, TensorDataset
    except ImportError:
        logger.error("pip install torch is required for training")
        sys.exit(1)

    import numpy as np

    # 80/20 train/val split
    split = int(len(X) * 0.8)
    X_train, X_val = X[:split], X[split:]
    y_train, y_val = y[:split], y[split:]

    train_ds = TensorDataset(torch.from_numpy(X_train), torch.from_numpy(y_train))
    val_ds = TensorDataset(torch.from_numpy(X_val), torch.from_numpy(y_val))

    train_loader = DataLoader(train_ds, batch_size=args.batch_size, shuffle=True)
    val_loader = DataLoader(val_ds, batch_size=args.batch_size)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    logger.info("  Training on %s (%d train, %d val samples)", device, len(train_ds), len(val_ds))

    model = build_model(args.hidden_size, args.num_layers).to(device)
    opt = torch.optim.Adam(model.parameters(), lr=args.lr)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(opt, patience=3, factor=0.5)
    criterion = nn.HuberLoss()

    best_val = float("inf")
    best_state = None

    for epoch in range(1, args.epochs + 1):
        model.train()
        train_loss = 0.0
        for xb, yb in train_loader:
            xb, yb = xb.to(device), yb.to(device)
            opt.zero_grad()
            pred = model(xb)
            loss = criterion(pred, yb)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step()
            train_loss += loss.item() * len(xb)

        model.eval()
        val_loss = 0.0
        with torch.no_grad():
            for xb, yb in val_loader:
                xb, yb = xb.to(device), yb.to(device)
                val_loss += criterion(model(xb), yb).item() * len(xb)

        train_loss /= len(train_ds)
        val_loss /= len(val_ds)
        scheduler.step(val_loss)

        if val_loss < best_val:
            best_val = val_loss
            best_state = {k: v.cpu().clone() for k, v in model.state_dict().items()}

        if epoch % 5 == 0 or epoch == 1:
            logger.info("  Epoch %3d/%d  train=%.4f  val=%.4f", epoch, args.epochs, train_loss, val_loss)

    if best_state is not None:
        model.load_state_dict(best_state)
    logger.info("  Best val loss: %.4f", best_val)
    return model.cpu()


# ── ONNX export ───────────────────────────────────────────────────────────────


def export_onnx(model, output_path: Path) -> None:
    """Export PyTorch model to ONNX."""
    try:
        import torch
        import onnx
    except ImportError:
        logger.error("pip install torch onnx is required for export")
        sys.exit(1)

    dummy_input = torch.zeros(1, SEQ_LEN, N_FEATURES)
    model.eval()
    # Use legacy exporter (dynamo=False) for compatibility with torch 2.x on Windows
    torch.onnx.export(
        model,
        (dummy_input,),
        str(output_path),
        input_names=["sequence"],
        output_names=["predictions"],
        dynamic_axes={"sequence": {0: "batch"}, "predictions": {0: "batch"}},
        opset_version=18,
        dynamo=False,
    )
    # Validate
    import onnx as onnx_lib
    onnx_lib.checker.check_model(str(output_path))
    logger.info("ONNX model validated OK")


if __name__ == "__main__":
    main()
