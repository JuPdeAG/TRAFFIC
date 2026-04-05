# Stage 1: Build
FROM python:3.12-slim AS builder

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gdal-bin libgeos-dev libproj-dev gcc g++ \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /app
COPY pyproject.toml .
COPY src/ src/
RUN uv pip install --system --no-cache .

# Stage 2: Runtime
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 libgdal36 libgeos-c1t64 libproj25 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /app/src /app/src

ENV PYTHONPATH=/app/src
ENV MODEL_CACHE_DIR=/app/models

# Pre-download YOLOv6n ONNX at build time so vehicle detection works on first poll
RUN mkdir -p /app/models && \
    python -c "import sys; sys.path.insert(0, '/app/src'); from traffic_ai.ml.vehicle_detector import _ensure_model; _ensure_model('yolov6n')" && \
    echo "YOLOv6n model cached at build time"

# Bake in trained LSTM congestion model and its feature scaler
COPY models/congestion_lstm.onnx /app/models/congestion_lstm.onnx
COPY models/congestion_scaler.json /app/models/congestion_scaler.json

CMD ["uvicorn", "traffic_ai.main:app", "--host", "0.0.0.0", "--port", "8000"]
